"""A small read-only LevelDB reader for Bedrock worlds.

Bedrock stores its world in Mojang's LevelDB variant (zlib-compressed blocks).
This reads the files directly without taking the database lock, so it can look
at a world while the server has it open. Tables are immutable once written and
the log is append-only, which is what makes that safe; a file that disappears
mid-read (compaction) is simply skipped.

Only what the map needs is implemented: list keys with their newest sequence
number, and fetch values.
"""
import struct
import zlib
from functools import lru_cache
from pathlib import Path

TABLE_MAGIC = bytes.fromhex("57fb808b247547db")
LOG_BLOCK = 32768


def _varint(buf, pos):
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7


def _decompress(raw: bytes, kind: int) -> bytes:
    if kind == 0:
        return raw
    if kind == 2:
        return zlib.decompress(raw)
    if kind == 4:
        return zlib.decompress(raw, -15)
    raise ValueError(f"unsupported block compression {kind}")


@lru_cache(maxsize=64)
def _read_block(path: str, offset: int, size: int) -> bytes:
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(size + 1)
    return _decompress(raw[:size], raw[size])


def _block_entries(block: bytes):
    """Yield (key, value_offset, value_length) for each entry in a table block."""
    restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    end = len(block) - 4 - 4 * restarts
    pos = 0
    key = b""
    while pos < end:
        shared, pos = _varint(block, pos)
        unshared, pos = _varint(block, pos)
        value_len, pos = _varint(block, pos)
        key = key[:shared] + block[pos:pos + unshared]
        pos += unshared
        yield key, pos, value_len
        pos += value_len


class WorldDB:
    """Snapshot of the newest value location for every key that passes `wanted`."""

    def __init__(self, db_dir: Path, wanted):
        self.db_dir = Path(db_dir)
        # key -> (sequence, location); location is bytes (from the log) or
        # (path, block_offset, block_size, value_offset, value_length)
        self.index: dict[bytes, tuple] = {}
        deleted: dict[bytes, int] = {}

        def record(key, seq, kind, location):
            if kind == 0:
                if seq > deleted.get(key, -1):
                    deleted[key] = seq
            elif seq >= self.index.get(key, (-1,))[0]:
                self.index[key] = (seq, location)

        for path in sorted(self.db_dir.iterdir()):
            try:
                if path.suffix == ".ldb":
                    self._scan_table(path, wanted, record)
                elif path.suffix == ".log":
                    self._scan_log(path, wanted, record)
            except (FileNotFoundError, zlib.error, struct.error, IndexError, ValueError):
                continue  # compacted away or still being written; next refresh will see the result

        for key, seq in deleted.items():
            if key in self.index and self.index[key][0] < seq:
                del self.index[key]

    @staticmethod
    def _scan_table(path: Path, wanted, record):
        size = path.stat().st_size
        if size < 48:
            return
        with open(path, "rb") as f:
            f.seek(size - 48)
            footer = f.read(48)
            if footer[40:] != TABLE_MAGIC:
                return
            pos = 0
            _, pos = _varint(footer, pos)          # metaindex handle
            _, pos = _varint(footer, pos)
            index_offset, pos = _varint(footer, pos)
            index_size, pos = _varint(footer, pos)
            f.seek(index_offset)
            raw = f.read(index_size + 1)
        index_block = _decompress(raw[:index_size], raw[index_size])
        spath = str(path)
        for _, value_pos, value_len in _block_entries(index_block):
            block_offset, p = _varint(index_block, value_pos)
            block_size, _ = _varint(index_block, p)
            block = _read_block(spath, block_offset, block_size)
            for ikey, vpos, vlen in _block_entries(block):
                key = ikey[:-8]
                if wanted(key):
                    tag = int.from_bytes(ikey[-8:], "little")
                    record(key, tag >> 8, tag & 0xFF, (spath, block_offset, block_size, vpos, vlen))

    @staticmethod
    def _scan_log(path: Path, wanted, record):
        data = path.read_bytes()
        pos = 0
        partial = b""

        def batch(payload):
            if len(payload) < 12:
                return
            seq, count = struct.unpack_from("<QI", payload, 0)
            p = 12
            for i in range(count):
                kind = payload[p]
                key_len, p = _varint(payload, p + 1)
                key = payload[p:p + key_len]
                p += key_len
                value = b""
                if kind == 1:
                    value_len, p = _varint(payload, p)
                    value = payload[p:p + value_len]
                    p += value_len
                if wanted(key):
                    record(key, seq + i, kind, value)

        while pos + 7 <= len(data):
            left = LOG_BLOCK - (pos % LOG_BLOCK)
            if left < 7:
                pos += left
                continue
            _, length, kind = struct.unpack_from("<IHB", data, pos)
            if kind == 0 and length == 0:   # preallocated / padding
                pos += left
                continue
            payload = data[pos + 7:pos + 7 + length]
            pos += 7 + length
            if len(payload) < length:       # torn write at the tail
                break
            try:
                if kind == 1:
                    batch(payload)
                elif kind == 2:
                    partial = payload
                elif kind == 3:
                    partial += payload
                elif kind == 4:
                    batch(partial + payload)
                    partial = b""
            except IndexError:
                break

    def get(self, key: bytes) -> bytes | None:
        entry = self.index.get(key)
        if entry is None:
            return None
        location = entry[1]
        if isinstance(location, bytes):
            return location
        path, block_offset, block_size, vpos, vlen = location
        try:
            return _read_block(path, block_offset, block_size)[vpos:vpos + vlen]
        except (FileNotFoundError, zlib.error):
            return None


def read_nbt(buf: bytes, pos: int = 0):
    """Parse one little-endian NBT tag (Bedrock's on-disk flavour). Returns (value, next_pos)."""
    kind = buf[pos]
    name_len = struct.unpack_from("<H", buf, pos + 1)[0]
    return _nbt_payload(buf, pos + 3 + name_len, kind)


def _nbt_payload(buf, pos, kind):
    if kind == 1:
        return buf[pos], pos + 1
    if kind == 2:
        return struct.unpack_from("<h", buf, pos)[0], pos + 2
    if kind == 3:
        return struct.unpack_from("<i", buf, pos)[0], pos + 4
    if kind == 4:
        return struct.unpack_from("<q", buf, pos)[0], pos + 8
    if kind == 5:
        return struct.unpack_from("<f", buf, pos)[0], pos + 4
    if kind == 6:
        return struct.unpack_from("<d", buf, pos)[0], pos + 8
    if kind == 7:
        n = struct.unpack_from("<i", buf, pos)[0]
        return buf[pos + 4:pos + 4 + n], pos + 4 + n
    if kind == 8:
        n = struct.unpack_from("<H", buf, pos)[0]
        return buf[pos + 2:pos + 2 + n].decode("utf-8", errors="replace"), pos + 2 + n
    if kind == 9:
        item_kind = buf[pos]
        n = struct.unpack_from("<i", buf, pos + 1)[0]
        pos += 5
        items = []
        for _ in range(n):
            value, pos = _nbt_payload(buf, pos, item_kind)
            items.append(value)
        return items, pos
    if kind == 10:
        result = {}
        while True:
            child = buf[pos]
            if child == 0:
                return result, pos + 1
            name_len = struct.unpack_from("<H", buf, pos + 1)[0]
            name = buf[pos + 3:pos + 3 + name_len].decode("utf-8", errors="replace")
            result[name], pos = _nbt_payload(buf, pos + 3 + name_len, child)
    if kind == 11:
        n = struct.unpack_from("<i", buf, pos)[0]
        return list(struct.unpack_from(f"<{n}i", buf, pos + 4)), pos + 4 + 4 * n
    if kind == 12:
        n = struct.unpack_from("<i", buf, pos)[0]
        return list(struct.unpack_from(f"<{n}q", buf, pos + 4)), pos + 4 + 8 * n
    raise ValueError(f"unknown NBT tag {kind}")
