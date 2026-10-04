"""Top-down map of the overworld, rendered straight from the world files.

Tiles are 256x256 PNGs (one pixel per block, 16x16 chunks each) that the
dashboard shows with Leaflet. Rendering is incremental: a chunk is redrawn
only when the newest sequence number among its sub-chunks changes.
"""
import json
import struct
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from leveldb_reader import WorldDB, read_nbt

SUBCHUNK_TAG = 0x2F
MIN_Y_INDEX, MAX_Y_INDEX = -4, 19     # overworld: y -64 .. 319
REGION = 256

# ---------------------------------------------------------------------------
# Block colours
# ---------------------------------------------------------------------------

DYES = {
    "white": (233, 236, 236), "orange": (240, 118, 19), "magenta": (189, 68, 179),
    "light_blue": (58, 175, 217), "yellow": (248, 198, 39), "lime": (112, 185, 25),
    "pink": (237, 141, 172), "gray": (62, 68, 71), "light_gray": (142, 142, 134),
    "cyan": (21, 137, 145), "purple": (121, 42, 172), "blue": (53, 57, 157),
    "brown": (114, 71, 40), "green": (84, 109, 27), "red": (161, 39, 34), "black": (20, 21, 25),
}
WOODS = {
    "oak": (162, 130, 78), "spruce": (114, 84, 48), "birch": (192, 175, 121), "jungle": (160, 115, 80),
    "acacia": (168, 90, 50), "dark_oak": (66, 43, 20), "mangrove": (117, 54, 48), "cherry": (226, 178, 172),
    "pale_oak": (228, 217, 216), "bamboo": (193, 173, 80), "crimson": (101, 48, 70), "warped": (43, 104, 99),
}
LEAVES = {
    "oak": (60, 120, 40), "spruce": (61, 98, 61), "birch": (128, 167, 85), "jungle": (48, 140, 20),
    "acacia": (87, 135, 38), "dark_oak": (45, 95, 30), "mangrove": (70, 125, 45), "cherry": (240, 170, 205),
    "pale_oak": (170, 180, 165), "azalea": (90, 115, 45),
}
EXACT = {
    "grass_block": (94, 157, 52), "dirt": (134, 96, 67), "coarse_dirt": (119, 85, 59), "rooted_dirt": (144, 103, 76),
    "podzol": (90, 63, 24), "mycelium": (111, 98, 101), "farmland": (110, 75, 45), "dirt_path": (148, 121, 65),
    "grass_path": (148, 121, 65), "mud": (60, 57, 60), "moss_block": (89, 109, 45), "clay": (160, 166, 179),
    "stone": (125, 125, 125), "cobblestone": (122, 122, 122), "mossy_cobblestone": (110, 118, 94),
    "granite": (149, 103, 85), "diorite": (188, 188, 188), "andesite": (136, 136, 136),
    "deepslate": (80, 80, 82), "tuff": (108, 109, 102), "calcite": (223, 224, 220), "dripstone_block": (134, 107, 92),
    "gravel": (136, 126, 126), "sand": (219, 207, 163), "red_sand": (190, 102, 33),
    "sandstone": (216, 203, 155), "red_sandstone": (186, 99, 29),
    "water": (63, 118, 228), "flowing_water": (63, 118, 228), "lava": (207, 91, 20), "flowing_lava": (207, 91, 20),
    "snow": (249, 254, 254), "snow_layer": (249, 254, 254), "powder_snow": (248, 253, 253),
    "ice": (145, 183, 253), "packed_ice": (141, 180, 250), "blue_ice": (116, 167, 253),
    "bedrock": (85, 85, 85), "obsidian": (15, 10, 24), "crying_obsidian": (32, 10, 60),
    "netherrack": (97, 38, 38), "soul_sand": (81, 62, 50), "soul_soil": (75, 57, 46), "basalt": (73, 72, 77),
    "blackstone": (42, 36, 41), "glowstone": (171, 131, 84), "magma": (142, 63, 31), "end_stone": (219, 222, 158),
    "stone_bricks": (122, 121, 122), "mossy_stone_bricks": (115, 121, 105), "bricks": (150, 97, 83),
    "brick_block": (150, 97, 83), "nether_brick": (44, 21, 26), "quartz_block": (235, 229, 222),
    "smooth_stone": (158, 158, 158), "bookshelf": (117, 94, 59), "crafting_table": (119, 73, 42),
    "iron_block": (220, 220, 220), "gold_block": (246, 208, 61), "diamond_block": (98, 237, 228),
    "emerald_block": (42, 203, 87), "lapis_block": (30, 67, 140), "redstone_block": (175, 24, 5),
    "coal_block": (16, 15, 15), "copper_block": (192, 107, 79), "amethyst_block": (133, 97, 191),
    "netherite_block": (66, 61, 63), "tnt": (219, 68, 52), "hay_block": (166, 139, 12),
    "pumpkin": (198, 118, 24), "carved_pumpkin": (198, 118, 24), "lit_pumpkin": (220, 150, 40),
    "melon_block": (111, 145, 30), "cactus": (85, 127, 43), "waterlily": (32, 128, 48),
    "glass": (175, 213, 219), "tinted_glass": (44, 38, 46), "sea_lantern": (172, 199, 190),
    "prismarine": (99, 156, 151), "sponge": (195, 192, 74), "slime": (111, 192, 91), "honey_block": (251, 185, 52),
    "terracotta": (152, 94, 67), "hardened_clay": (152, 94, 67), "bone_block": (209, 206, 179),
    "seagrass": (63, 118, 228), "kelp": (63, 118, 228), "bubble_column": (63, 118, 228),
    "torch": (255, 216, 110), "lantern": (255, 200, 110), "campfire": (220, 130, 50), "fire": (230, 120, 30),
    "wheat": (190, 170, 80), "reeds": (130, 170, 90), "sugar_cane": (130, 170, 90),
}
# Thin things that shouldn't hide the ground under them
SEE_THROUGH_EXACT = {
    "air", "barrier", "structure_void", "light_block", "short_grass", "tall_grass", "tallgrass", "fern",
    "large_fern", "double_plant", "deadbush", "dead_bush", "vine", "ladder", "lever", "tripwire",
    "redstone_wire", "web", "snow_layer_thin", "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "sunflower", "lilac", "rose_bush", "peony",
    "brown_mushroom", "red_mushroom", "glow_lichen", "leaf_litter", "wildflowers", "pink_petals",
    "bush", "firefly_bush", "short_dry_grass", "tall_dry_grass", "sweet_berry_bush", "rail",
}
SEE_THROUGH_SUFFIX = ("_sapling", "_button", "_sign", "_tulip", "_rail", "_pressure_plate", "_banner", "_torch")


@lru_cache(maxsize=None)
def block_color(name: str):
    """RGB for a block id like 'minecraft:oak_planks', or None if it shouldn't show on the map."""
    name = name.split(":", 1)[-1]
    if name in SEE_THROUGH_EXACT or name.startswith("light_block") or name.endswith(SEE_THROUGH_SUFFIX):
        return None
    if name in EXACT:
        return EXACT[name]
    if "leaves" in name:
        return next((c for wood, c in LEAVES.items() if name.startswith(wood)), (60, 120, 40))
    for dye in sorted(DYES, key=len, reverse=True):   # light_blue before blue
        if name.startswith(dye + "_"):
            r, g, b = DYES[dye]
            if "terracotta" in name:
                return (r * 6 + 152 * 4) // 10, (g * 6 + 94 * 4) // 10, (b * 6 + 67 * 4) // 10
            return r, g, b
    for wood in sorted(WOODS, key=len, reverse=True):  # dark_oak before oak
        if name.startswith(("stripped_" + wood, wood + "_")):
            r, g, b = WOODS[wood]
            if name.endswith(("_log", "_wood", "_stem", "_hyphae")) and not name.startswith("stripped_"):
                return r * 2 // 3, g * 2 // 3, b * 2 // 3   # bark is darker than planks
            return r, g, b
    rules = (
        ("deepslate", (80, 80, 82)), ("blackstone", (42, 36, 41)), ("nether_brick", (44, 21, 26)),
        ("red_sandstone", (186, 99, 29)), ("sandstone", (216, 203, 155)), ("prismarine", (99, 156, 151)),
        ("quartz", (235, 229, 222)), ("copper", (192, 107, 79)), ("mud_brick", (137, 104, 79)),
        ("brick", (150, 97, 83)), ("cobble", (122, 122, 122)), ("stone", (125, 125, 125)),
        ("granite", (149, 103, 85)), ("diorite", (188, 188, 188)), ("andesite", (136, 136, 136)),
        ("tuff", (108, 109, 102)), ("basalt", (73, 72, 77)), ("purpur", (170, 126, 170)),
        ("end_stone", (219, 222, 158)), ("coral", (200, 90, 140)), ("ice", (145, 183, 253)),
        ("snow", (249, 254, 254)), ("sand", (219, 207, 163)), ("moss", (89, 109, 45)),
        ("mushroom", (150, 110, 85)), ("amethyst", (133, 97, 191)), ("sculk", (13, 30, 36)),
        ("glass", (175, 213, 219)), ("_ore", (125, 125, 125)), ("planks", (162, 130, 78)),
        ("log", (109, 85, 50)), ("wood", (109, 85, 50)), ("bamboo", (193, 173, 80)),
    )
    for needle, color in rules:
        if needle in name:
            return color
    return 160, 150, 165


# ---------------------------------------------------------------------------
# Chunk decoding
# ---------------------------------------------------------------------------

def _decode_subchunk(data: bytes):
    """Return (indices[x][z][y] as uint16 array, [block names]) or None for unknown formats."""
    version = data[0]
    if version == 9:
        pos = 3
    elif version == 8:
        pos = 2
    elif version == 1:
        pos = 1
    else:
        return None
    if data[1] == 0 and version != 1:
        return None
    bits = data[pos] >> 1
    pos += 1
    if bits == 0:
        indices = np.zeros((16, 16, 16), dtype=np.uint16)
        count = 1
        if data[pos] != 0x0A:   # some versions still write the count
            count = struct.unpack_from("<i", data, pos)[0]
            pos += 4
    else:
        per_word = 32 // bits
        words = -(-4096 // per_word)
        packed = np.frombuffer(data, dtype="<u4", count=words, offset=pos)
        pos += 4 * words
        shifts = (np.arange(per_word, dtype=np.uint32) * bits).astype(np.uint32)
        indices = ((packed[:, None] >> shifts) & ((1 << bits) - 1)).reshape(-1)[:4096]
        indices = indices.reshape(16, 16, 16).astype(np.uint16)
        count = struct.unpack_from("<i", data, pos)[0]
        pos += 4
    names = []
    for _ in range(count):
        entry, pos = read_nbt(data, pos)
        names.append(entry.get("name", "minecraft:air"))
    return indices, names


def render_chunk(get_subchunk, y_indices):
    """Find the top visible block of each column. Returns (rgb[z][x], height[z][x], found[z][x])."""
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)       # [x][z] while filling
    height = np.full((16, 16), -64, dtype=np.int16)
    found = np.zeros((16, 16), dtype=bool)
    for y_index in sorted(y_indices, reverse=True):
        data = get_subchunk(y_index)
        if not data:
            continue
        try:
            decoded = _decode_subchunk(data)
        except (struct.error, IndexError, ValueError, KeyError):
            decoded = None
        if decoded is None:
            continue
        indices, names = decoded
        colors = [block_color(n) for n in names]
        visible = np.array([c is not None for c in colors], dtype=bool)
        if not visible.any():
            continue
        palette = np.array([c or (0, 0, 0) for c in colors], dtype=np.uint8)
        solid = visible[indices]                                  # [x][z][y]
        any_solid = solid.any(axis=2)
        top = 15 - np.argmax(solid[:, :, ::-1], axis=2)           # highest solid y in each column
        take = any_solid & ~found
        if take.any():
            xs, zs = np.nonzero(take)
            ys = top[xs, zs]
            rgb[xs, zs] = palette[indices[xs, zs, ys]]
            height[xs, zs] = y_index * 16 + ys
            found |= take
        if found.all():
            break
    return rgb.transpose(1, 0, 2), height.T, found.T


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

class WorldMap:
    def __init__(self, world_dir: Path, out_dir: Path):
        self.world_dir = Path(world_dir)
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.regions: dict[tuple[int, int], dict] = {}
        self.chunk_seq: dict[tuple[int, int], int] = {}
        self.updated = 0.0
        self.version = 0
        self._signature = None
        self._lock = threading.Lock()

    # -- reading the world ---------------------------------------------------

    def _db_signature(self):
        try:
            return tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                                for p in (self.world_dir / "db").iterdir()))
        except FileNotFoundError:
            return None

    def spawn(self):
        try:
            nbt, _ = read_nbt((self.world_dir / "level.dat").read_bytes(), 8)
            return int(nbt.get("SpawnX", 0)), int(nbt.get("SpawnZ", 0))
        except Exception:
            return 0, 0

    def refresh(self, force: bool = False) -> dict:
        """Redraw whatever changed on disk. Cheap when nothing did."""
        with self._lock:
            signature = self._db_signature()
            if signature is None:
                return self.info()
            if signature == self._signature and not force:
                return self.info()

            def wanted(key):
                return len(key) == 10 and key[8] == SUBCHUNK_TAG

            db = WorldDB(self.world_dir / "db", wanted)
            chunks: dict[tuple[int, int], dict[int, int]] = {}
            for key, (seq, _) in db.index.items():
                cx, cz = struct.unpack_from("<ii", key, 0)
                y_index = struct.unpack_from("<b", key, 9)[0]
                chunks.setdefault((cx, cz), {})[y_index] = seq

            dirty = set()
            for (cx, cz), subchunks in chunks.items():
                stamp = max(subchunks.values()) * 31 + len(subchunks)
                if self.chunk_seq.get((cx, cz)) == stamp:
                    continue
                prefix = struct.pack("<ii", cx, cz) + bytes([SUBCHUNK_TAG])
                rgb, height, found = render_chunk(
                    lambda y: db.get(prefix + struct.pack("<b", y)), subchunks.keys())
                region_key = (cx >> 4, cz >> 4)
                region = self.regions.setdefault(region_key, {
                    "rgb": np.zeros((REGION, REGION, 3), dtype=np.uint8),
                    "height": np.full((REGION, REGION), -64, dtype=np.int16),
                    "alpha": np.zeros((REGION, REGION), dtype=bool),
                })
                px, pz = (cx & 15) * 16, (cz & 15) * 16
                region["rgb"][pz:pz + 16, px:px + 16] = rgb
                region["height"][pz:pz + 16, px:px + 16] = height
                region["alpha"][pz:pz + 16, px:px + 16] = found
                self.chunk_seq[(cx, cz)] = stamp
                dirty.add(region_key)

            for region_key in dirty:
                self._write_tile(region_key)
            self._signature = signature
            if dirty:
                self.updated = time.time()
                self.version += 1
            (self.out_dir / "meta.json").write_text(json.dumps(self.info()))
            return self.info()

    def _write_tile(self, region_key):
        region = self.regions[region_key]
        height = region["height"].astype(np.float32)
        # Light from the north-west: slopes facing it are brighter
        north = np.vstack([height[:1], height[:-1]])
        west = np.hstack([height[:, :1], height[:, :-1]])
        slope = np.clip((height - north) * 0.07 + (height - west) * 0.07, -0.28, 0.28)
        altitude = np.clip((height - 64) * 0.0025, -0.12, 0.15)
        shade = (1.0 + slope + altitude)[:, :, None]
        rgb = np.clip(region["rgb"].astype(np.float32) * shade, 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb, np.where(region["alpha"], 255, 0).astype(np.uint8)])
        rx, rz = region_key
        Image.fromarray(rgba, "RGBA").save(self.out_dir / f"r.{rx}.{rz}.png", optimize=False)

    # -- queries -------------------------------------------------------------

    def info(self) -> dict:
        keys = list(self.regions)
        spawn_x, spawn_z = self.spawn()
        return {
            "updated": self.updated,
            "version": self.version,
            "chunks": len(self.chunk_seq),
            "spawn": {"x": spawn_x, "z": spawn_z},
            "bounds": ({
                "min_x": min(k[0] for k in keys) * REGION, "max_x": (max(k[0] for k in keys) + 1) * REGION,
                "min_z": min(k[1] for k in keys) * REGION, "max_z": (max(k[1] for k in keys) + 1) * REGION,
            } if keys else None),
        }

    def tile_path(self, rx: int, rz: int) -> Path | None:
        path = self.out_dir / f"r.{rx}.{rz}.png"
        return path if (rx, rz) in self.regions and path.exists() else None

    def surface_height(self, x: int, z: int) -> int | None:
        """Y of the top block at (x, z), or None if that spot isn't on the map yet."""
        region = self.regions.get((x >> 8, z >> 8))
        if region is None or not region["alpha"][z & 255, x & 255]:
            return None
        return int(region["height"][z & 255, x & 255])
