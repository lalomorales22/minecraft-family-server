"""World backups: zip snapshots taken while the server keeps running, and restore."""
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

import mc

# How many backups of each kind to keep per world. Manual ones are never pruned.
KEEP = {"auto": 8, "daily": 14, "before-restore": 3}
_lock = threading.Lock()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "world"


def _read_meta(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.comment.decode("utf-8"))
    except Exception:
        return None
    meta.update(id=path.name, size_mb=round(path.stat().st_size / 1048576, 1))
    return meta


def list_backups() -> list[dict]:
    if not mc.BACKUP_DIR.exists():
        return []
    found = [m for m in (_read_meta(p) for p in mc.BACKUP_DIR.glob("*.zip")) if m]
    return sorted(found, key=lambda m: m["time"], reverse=True)


def _find(backup_id: str) -> Path:
    # Only ever resolve ids that the listing itself produced
    if backup_id not in {b["id"] for b in list_backups()}:
        raise ValueError("No such backup")
    return mc.BACKUP_DIR / backup_id


def _world_changed_since(world_dir: Path, when: float) -> bool:
    return any(p.stat().st_mtime > when for p in world_dir.rglob("*") if p.is_file())


def create_backup(kind: str = "manual", world: str | None = None) -> dict:
    """Snapshot a world. Safe while people are playing: the server is asked to
    pause disk writes and say exactly how much of each file is valid."""
    with _lock:
        world = world or mc.active_world()
        world_dir = mc.WORLDS_DIR / world
        if not world_dir.is_dir():
            raise ValueError(f"World '{world}' doesn't exist yet")
        mc.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        target = mc.BACKUP_DIR / f"{_slug(world)}__{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}__{kind}.zip"
        partial = target.with_suffix(".partial")
        live = mc.server_running() and world == mc.active_world()
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                if live:
                    try:
                        for rel, length in mc.flush_world():
                            src = mc.WORLDS_DIR / rel
                            if src.is_file() and rel.split("/", 1)[0] == world:
                                with open(src, "rb") as f:
                                    z.writestr(rel.split("/", 1)[1], f.read(length))
                    finally:
                        mc.resume_world()
                else:
                    for src in sorted(world_dir.rglob("*")):
                        if src.is_file():
                            z.write(src, src.relative_to(world_dir).as_posix())
                if not z.namelist():
                    raise RuntimeError("Nothing to back up")
                z.comment = json.dumps({"world": world, "kind": kind, "time": now}).encode("utf-8")
            partial.rename(target)
        finally:
            partial.unlink(missing_ok=True)
        _prune(world)
        return _read_meta(target)


def _prune(world: str) -> None:
    for kind, keep in KEEP.items():
        same = [b for b in list_backups() if b["world"] == world and b["kind"] == kind]
        for old in same[keep:]:
            (mc.BACKUP_DIR / old["id"]).unlink(missing_ok=True)


def delete_backup(backup_id: str) -> None:
    _find(backup_id).unlink()


def restore_backup(backup_id: str) -> dict:
    """Put a world back the way it was. The current state is backed up first."""
    path = _find(backup_id)
    meta = _read_meta(path)
    world = meta["world"]
    world_dir = mc.WORLDS_DIR / world
    was_running = mc.server_running()
    is_active = world == mc.active_world()

    if world_dir.is_dir():
        create_backup("before-restore", world)

    with _lock:
        if was_running and is_active:
            mc.container().stop(timeout=30)
        aside = mc.WORLDS_DIR / f".{world}.replaced"
        shutil.rmtree(aside, ignore_errors=True)
        if world_dir.exists():
            world_dir.rename(aside)
        try:
            world_dir.mkdir(parents=True)
            with zipfile.ZipFile(path) as z:
                for member in z.namelist():
                    dest = (world_dir / member).resolve()
                    if not dest.is_relative_to(world_dir.resolve()):
                        raise ValueError("Backup contains an unsafe path")
                z.extractall(world_dir)
        except Exception:
            shutil.rmtree(world_dir, ignore_errors=True)
            if aside.exists():
                aside.rename(world_dir)
            raise
        finally:
            if was_running and is_active:
                mc.container().start()
        shutil.rmtree(aside, ignore_errors=True)
    return meta


def scheduled_backup(kind: str) -> None:
    """Called on a timer. Skips the backup when nobody has changed the world since the last one."""
    try:
        world = mc.active_world()
        world_dir = mc.WORLDS_DIR / world
        if not world_dir.is_dir():
            return
        previous = [b for b in list_backups() if b["world"] == world and b["kind"] in ("auto", "daily", "manual")]
        if previous and not _world_changed_since(world_dir, previous[0]["time"]):
            return
        create_backup(kind, world)
    except Exception as e:  # never let a failed backup kill the scheduler
        print(f"[backup] {kind} backup failed: {e}", flush=True)
