"""Several worlds side by side: list them, switch between them, make new ones."""
import json
import re
import time

import mc

SETTINGS_FILE = mc.DATA_DIR / "worlds.json"
# Remembered per world, so the creative world stays creative and the survival one stays survival
PER_WORLD = ("gamemode", "difficulty", "allow-cheats")
NAME_RULE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,29}$")


def _load() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    mc.DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def remember_current() -> None:
    """Store the active world's game settings (call after they change)."""
    props = mc.read_properties()
    data = _load()
    data[mc.active_world()] = {k: props.get(k, "") for k in PER_WORLD}
    _save(data)


def list_worlds() -> list[dict]:
    active = mc.active_world()
    saved = _load()
    props = mc.read_properties()
    worlds = []
    if mc.WORLDS_DIR.is_dir():
        for d in sorted(mc.WORLDS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            files = [p for p in d.rglob("*") if p.is_file()]
            settings = {k: props.get(k, "") for k in PER_WORLD} if d.name == active else saved.get(d.name, {})
            worlds.append({
                "name": d.name,
                "active": d.name == active,
                "size_mb": round(sum(p.stat().st_size for p in files) / 1048576, 1),
                "last_played": max((p.stat().st_mtime for p in files), default=0),
                "gamemode": settings.get("gamemode", ""),
            })
    return worlds


def _restart() -> None:
    box = mc.container()
    if box.status == "running":
        box.restart(timeout=30)
    else:
        box.start()


def switch_world(name: str) -> None:
    if name not in {w["name"] for w in list_worlds()}:
        raise ValueError("No such world")
    if name == mc.active_world():
        return
    remember_current()
    updates = {"level-name": name, "level-seed": ""}
    updates.update({k: v for k, v in _load().get(name, {}).items() if k in PER_WORLD and v})
    mc.write_properties(updates)
    _restart()


def create_world(name: str, gamemode: str, difficulty: str, seed: str = "") -> None:
    name = name.strip()
    if not NAME_RULE.match(name):
        raise ValueError("Use letters, numbers, spaces, - or _ (up to 30 characters)")
    if name.lower() in {w["name"].lower() for w in list_worlds()}:
        raise ValueError("A world with that name already exists")
    if gamemode not in ("survival", "creative", "adventure"):
        raise ValueError("Unknown gamemode")
    if difficulty not in ("peaceful", "easy", "normal", "hard"):
        raise ValueError("Unknown difficulty")
    if not re.fullmatch(r"-?\d{0,19}", seed.strip()):
        raise ValueError("A seed is a whole number")
    remember_current()
    cheats = "true" if gamemode == "creative" else mc.read_properties().get("allow-cheats", "false")
    mc.write_properties({
        "level-name": name, "level-seed": seed.strip(),
        "gamemode": gamemode, "difficulty": difficulty, "allow-cheats": cheats,
    })
    data = _load()
    data[name] = {"gamemode": gamemode, "difficulty": difficulty, "allow-cheats": cheats, "created": time.time()}
    _save(data)
    _restart()
