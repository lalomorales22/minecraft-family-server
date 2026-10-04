"""Turn a build plan (a list of simple shapes) into blocks in the world.

A plan is drawn into a 64x64x64 grid first, then the grid is merged into as few
`fill` commands as possible. The area is snapshotted with `structure save`
before anything is placed, which is what makes Undo work.
"""
import io
import json
import re
import threading
import time

import numpy as np
from PIL import Image

import mc
from worldmap import block_color

SIZE = 64                 # plans live in a SIZE^3 cube: x east, y up, z south
MAX_OPS = 2500
MAX_FILL_VOLUME = 32768   # Bedrock's limit per fill command
WORLD_MIN_Y, WORLD_MAX_Y = -64, 319
TICKING_AREA = "dashboard_build"
UNDO_FILE = mc.DATA_DIR / "last-build.json"

COLORS = ["white", "light_gray", "gray", "black", "brown", "red", "orange", "yellow", "lime", "green",
          "cyan", "light_blue", "blue", "purple", "magenta", "pink"]
WOODS = ["oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry"]

# Block id -> block states to add to the command ("" for none).
# Deliberately leaves out anything that burns, explodes, flows hot or runs commands.
BLOCKS: dict[str, str] = {name: "" for name in [
    "air",
    # stone and brick
    "stone", "cobblestone", "mossy_cobblestone", "stone_bricks", "mossy_stone_bricks", "cracked_stone_bricks",
    "chiseled_stone_bricks", "smooth_stone", "andesite", "polished_andesite", "diorite", "polished_diorite",
    "granite", "polished_granite", "deepslate", "cobbled_deepslate", "polished_deepslate", "deepslate_bricks",
    "deepslate_tiles", "tuff", "tuff_bricks", "calcite", "blackstone", "polished_blackstone",
    "polished_blackstone_bricks", "basalt", "brick_block", "mud_bricks", "packed_mud", "sandstone",
    "smooth_sandstone", "cut_sandstone", "red_sandstone", "quartz_block", "quartz_bricks", "smooth_quartz",
    "end_stone", "end_bricks", "purpur_block", "prismarine", "prismarine_bricks", "dark_prismarine",
    "obsidian", "crying_obsidian", "netherrack", "nether_brick", "red_nether_brick",
    # ground
    "dirt", "grass_block", "coarse_dirt", "podzol", "moss_block", "sand", "red_sand", "gravel", "clay",
    "snow", "ice", "packed_ice", "blue_ice", "mud", "water",
    # wood
    *[f"{w}_planks" for w in WOODS], "bamboo_planks", "crimson_planks", "warped_planks",
    *[f"{w}_log" for w in WOODS], "stripped_oak_log", "stripped_spruce_log", "stripped_birch_log",
    *[f"{w}_fence" for w in WOODS], *[f"{w}_slab" for w in WOODS],
    "stone_brick_slab", "smooth_stone_slab", "cobblestone_slab", "sandstone_slab", "quartz_slab",
    "cobblestone_wall", "stone_brick_wall", "bookshelf", "crafting_table", "hay_block",
    # colour
    *[f"{c}_wool" for c in COLORS], *[f"{c}_concrete" for c in COLORS],
    *[f"{c}_terracotta" for c in COLORS], *[f"{c}_stained_glass" for c in COLORS],
    *[f"{c}_carpet" for c in COLORS],
    "hardened_clay", "glass", "glass_pane", "tinted_glass", "iron_bars",
    # shiny
    "iron_block", "gold_block", "diamond_block", "emerald_block", "lapis_block", "redstone_block",
    "coal_block", "copper_block", "amethyst_block", "netherite_block",
    # light
    "glowstone", "sea_lantern", "shroomlight", "lantern", "torch", "end_rod", "lit_pumpkin",
    "pearlescent_froglight", "ochre_froglight", "verdant_froglight",
    # nature and fun
    "pumpkin", "melon_block", "red_mushroom_block", "brown_mushroom_block", "mushroom_stem", "honey_block",
    "slime", "bone_block", "poppy", "dandelion", "short_grass", "waterlily",
]}
# Leaves placed by command wither away unless they are marked as player-placed
BLOCKS.update({f"{w}_leaves": '["persistent_bit"=true]' for w in WOODS})
BLOCKS["azalea_leaves"] = '["persistent_bit"=true]'

# Placed after everything else because they need something to sit on
NEEDS_SUPPORT = {"torch", "lantern", "end_rod", "poppy", "dandelion", "short_grass", "waterlily"} | \
                {f"{c}_carpet" for c in COLORS}

AIR = 0
UNTOUCHED = -1


class PlanError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Shapes -> grid
# ---------------------------------------------------------------------------

def voxelize(ops: list[dict]):
    """Draw the ops in order. Returns (grid[x][y][z] of palette indices, palette of block ids)."""
    if len(ops) > MAX_OPS:
        raise PlanError(f"Too many steps ({len(ops)}); the limit is {MAX_OPS}")
    grid = np.full((SIZE, SIZE, SIZE), UNTOUCHED, dtype=np.int16)
    palette = ["air"]
    X, Y, Z = np.ogrid[0:SIZE, 0:SIZE, 0:SIZE]

    def index(block):
        if block not in BLOCKS:
            raise PlanError(f"Unknown block '{block}'")
        if block not in palette:
            palette.append(block)
        return palette.index(block)

    def span(a, b):
        return (min(a, b), max(a, b))

    for op in ops:
        kind = op.get("op")
        b = index(op.get("block", ""))
        if kind == "box":
            (x1, x2), (y1, y2), (z1, z2) = span(op["x1"], op["x2"]), span(op["y1"], op["y2"]), span(op["z1"], op["z2"])
            inside = (X >= x1) & (X <= x2) & (Y >= y1) & (Y <= y2) & (Z >= z1) & (Z <= z2)
            on_x, on_y, on_z = (X == x1) | (X == x2), (Y == y1) | (Y == y2), (Z == z1) | (Z == z2)
            mode = op.get("mode", "solid")
            if mode == "hollow":
                grid[inside] = AIR
                grid[inside & (on_x | on_y | on_z)] = b
            elif mode == "walls":
                grid[inside & (on_x | on_z)] = b
            elif mode == "frame":
                grid[inside & ((on_x & on_y) | (on_x & on_z) | (on_y & on_z))] = b
            else:
                grid[inside] = b
        elif kind in ("sphere", "dome"):
            r = max(0, op["r"])
            d2 = (X - op["x"]) ** 2 + (Y - op["y"]) ** 2 + (Z - op["z"]) ** 2
            ball = d2 <= (r + 0.5) ** 2
            if kind == "dome":
                ball = ball & (Y >= op["y"])
            if op.get("hollow"):
                core = d2 <= (r - 0.5) ** 2
                grid[ball & core] = AIR
                grid[ball & ~core] = b
            else:
                grid[ball] = b
        elif kind == "cylinder":
            r, h = max(0, op["r"]), max(1, op["h"])
            axis = op.get("axis", "y")
            along, start = {"y": (Y, op["y"]), "x": (X, op["x"]), "z": (Z, op["z"])}[axis]
            if axis == "y":
                d2 = (X - op["x"]) ** 2 + (Z - op["z"]) ** 2
            elif axis == "x":
                d2 = (Y - op["y"]) ** 2 + (Z - op["z"]) ** 2
            else:
                d2 = (X - op["x"]) ** 2 + (Y - op["y"]) ** 2
            length = (along >= start) & (along < start + h)
            disc = d2 <= (r + 0.5) ** 2
            if op.get("hollow"):
                core = d2 <= (r - 0.5) ** 2
                grid[length & disc & core] = AIR
                grid[length & disc & ~core] = b
            else:
                grid[length & disc] = b
        elif kind == "cone":
            r, h = max(0, op["r"]), max(1, op["h"])
            layer = Y - op["y"]
            radius = r * (1 - layer / h)
            d2 = (X - op["x"]) ** 2 + (Z - op["z"]) ** 2
            grid[(layer >= 0) & (layer < h) & (d2 <= (radius + 0.5) ** 2)] = b
        elif kind in ("pyramid", "gable"):
            (x1, x2), (z1, z2) = span(op["x1"], op["x2"]), span(op["z1"], op["z2"])
            layer = Y - op["y"]
            shrink_x = layer if kind == "pyramid" or op.get("ridge") == "z" else 0
            shrink_z = layer if kind == "pyramid" or op.get("ridge", "x") == "x" else 0
            inside = (layer >= 0) & (X >= x1 + shrink_x) & (X <= x2 - shrink_x) & \
                     (Z >= z1 + shrink_z) & (Z <= z2 - shrink_z)
            if op.get("hollow"):
                edge = np.zeros_like(inside)
                if kind == "pyramid" or op.get("ridge") == "z":
                    edge = edge | (X == x1 + shrink_x) | (X == x2 - shrink_x)
                if kind == "pyramid" or op.get("ridge", "x") == "x":
                    edge = edge | (Z == z1 + shrink_z) | (Z == z2 - shrink_z)
                grid[inside & edge] = b
            else:
                grid[inside] = b
        elif kind == "line":
            start = np.array([op["x1"], op["y1"], op["z1"]], dtype=float)
            end = np.array([op["x2"], op["y2"], op["z2"]], dtype=float)
            steps = int(np.abs(end - start).max())
            for i in range(steps + 1):
                x, y, z = np.rint(start + (end - start) * (i / steps if steps else 0)).astype(int)
                if 0 <= x < SIZE and 0 <= y < SIZE and 0 <= z < SIZE:
                    grid[x, y, z] = b
        else:
            raise PlanError(f"Unknown step '{kind}'")

    # Slide the build into the corner of the grid, so (0,0,0) really is its
    # lowest north-west corner however the plan was laid out.
    touched = np.nonzero(grid != UNTOUCHED)
    if len(touched[0]):
        grid = np.roll(grid, [-int(axis.min()) for axis in touched], axis=(0, 1, 2))
    return grid, palette


def describe(grid, palette) -> dict:
    """Size and materials of a drawn plan."""
    placed = grid > AIR
    if not placed.any():
        raise PlanError("The plan doesn't place any blocks")
    xs, ys, zs = np.nonzero(grid != UNTOUCHED)
    counts = np.bincount(grid[placed], minlength=len(palette))
    materials = sorted(((palette[i], int(n)) for i, n in enumerate(counts) if n and i != AIR), key=lambda m: -m[1])
    return {
        "size": {"x": int(xs.max() + 1), "y": int(ys.max() + 1), "z": int(zs.max() + 1)},
        "blocks": int(placed.sum()),
        "materials": [{"block": name, "count": n} for name, n in materials[:8]],
    }


def preview_png(grid, palette, view: str = "top", scale: int = 6) -> bytes:
    """A small picture of the plan: 'top' looks down, 'front' looks north from the south side."""
    colors = np.array([block_color(name) or (0, 0, 0) for name in palette], dtype=np.uint8)
    solid = grid > AIR
    if view == "front":
        solid, cells = solid[:, ::-1, ::-1], grid[:, ::-1, ::-1]       # nearest (south) first, top row first
        hit = solid.any(axis=2)
        first = np.argmax(solid, axis=2)
        idx = np.take_along_axis(cells, first[:, :, None], axis=2)[:, :, 0]
        depth = first
    else:
        solid_t, cells = solid[:, ::-1, :], grid[:, ::-1, :]           # highest y first
        hit = solid_t.any(axis=1)
        first = np.argmax(solid_t, axis=1)
        idx = np.take_along_axis(cells, first[:, None, :], axis=1)[:, 0, :]
        depth = first
    rgb = colors[np.where(hit, idx, 0)].astype(np.float32)
    nearest = depth[hit].min() if hit.any() else 0
    rgb *= (1.0 - np.clip(depth - nearest, 0, 40) * 0.009)[:, :, None]  # further away = darker
    rgba = np.dstack([rgb.astype(np.uint8), np.where(hit, 255, 0).astype(np.uint8)]).transpose(1, 0, 2)
    ys, xs = np.nonzero(rgba[:, :, 3])
    rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    image = Image.fromarray(np.ascontiguousarray(rgba), "RGBA")
    image = image.resize((image.width * scale, image.height * scale), Image.NEAREST)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


# ---------------------------------------------------------------------------
# Grid -> commands
# ---------------------------------------------------------------------------

def to_commands(grid, palette, origin: tuple[int, int, int], skip_air: bool = False) -> list[str]:
    """Merge the grid into boxes and write one fill command per box.

    `skip_air` leaves out the carved-out parts, for when the space was already emptied.
    """
    ox, oy, oz = origin
    done = grid == UNTOUCHED
    if skip_air:
        done |= grid == AIR
    boxes = []
    for y in range(SIZE):
        if done[:, y, :].all():
            continue
        for z in range(SIZE):
            for x in range(SIZE):
                if done[x, y, z]:
                    continue
                b = grid[x, y, z]
                x2 = x
                while x2 + 1 < SIZE and grid[x2 + 1, y, z] == b and not done[x2 + 1, y, z]:
                    x2 += 1
                z2 = z
                while z2 + 1 < SIZE and (grid[x:x2 + 1, y, z2 + 1] == b).all() and not done[x:x2 + 1, y, z2 + 1].any():
                    z2 += 1
                y2 = y
                width = (x2 - x + 1) * (z2 - z + 1)
                while (y2 + 1 < SIZE and width * (y2 + 2 - y) <= MAX_FILL_VOLUME
                       and (grid[x:x2 + 1, y2 + 1, z:z2 + 1] == b).all()
                       and not done[x:x2 + 1, y2 + 1, z:z2 + 1].any()):
                    y2 += 1
                done[x:x2 + 1, y:y2 + 1, z:z2 + 1] = True
                boxes.append((palette[b], x, y, z, x2, y2, z2))
    # Bottom-up, with anything that needs a block to sit on placed last
    boxes.sort(key=lambda box: (box[0] in NEEDS_SUPPORT, box[2]))
    commands = []
    for name, x1, y1, z1, x2, y2, z2 in boxes:
        states = f" {BLOCKS[name]}" if BLOCKS[name] else ""
        commands.append(f"fill {ox + x1} {oy + y1} {oz + z1} {ox + x2} {oy + y2} {oz + z2} {name}{states}")
    return commands


# ---------------------------------------------------------------------------
# Placing in the world
# ---------------------------------------------------------------------------

_build_lock = threading.Lock()


def _load_area(x1: int, z1: int, x2: int, z2: int, timeout: float = 90.0) -> None:
    """Keep the build area loaded (it may be far from any player, or nobody may be online)."""
    mc.send(f"tickingarea remove {TICKING_AREA}")
    mc.send(f"tickingarea add {x1} 0 {z1} {x2} 0 {z2} {TICKING_AREA} true")
    deadline = time.time() + timeout
    for x, z in ((x1, z1), (x2, z1), (x1, z2), (x2, z2)):
        while not mc.ask(f"testforblock {x} {WORLD_MIN_Y} {z} bedrock",
                         rf"Successfully found the block at {x},\s*{WORLD_MIN_Y},\s*{z}", timeout=2.5):
            if time.time() > deadline:
                mc.send(f"tickingarea remove {TICKING_AREA}")
                raise RuntimeError("That part of the world took too long to load. Try again.")


def _unload_area() -> None:
    try:
        mc.send(f"tickingarea remove {TICKING_AREA}")
    except Exception:
        pass


def _wait_until_idle(marker_xz: tuple[int, int], timeout: float) -> None:
    """Commands run in order, so once this probe is answered everything before it has run."""
    x, z = marker_xz
    mc.ask(f"testforblock {x} {WORLD_MIN_Y} {z} bedrock",
           rf"Successfully found the block at {x},\s*{WORLD_MIN_Y},\s*{z}", timeout=timeout)


def place(grid, palette, origin: tuple[int, int, int], clear: bool = True, label: str = "") -> dict:
    """Build the plan with its (0,0,0) corner at `origin`. Returns a small report."""
    if not mc.server_running():
        raise RuntimeError("The server isn't running")
    stats = describe(grid, palette)
    ox, oy, oz = (int(v) for v in origin)
    sx, sy, sz = stats["size"]["x"], stats["size"]["y"], stats["size"]["z"]
    if oy < WORLD_MIN_Y + 1 or oy + sy - 1 > WORLD_MAX_Y:
        raise PlanError(f"That's too high or too low: the build is {sy} blocks tall")
    x2, y2, z2 = ox + sx - 1, oy + sy - 1, oz + sz - 1

    commands = []
    if clear:
        step = max(1, MAX_FILL_VOLUME // (sx * sz))
        for y in range(oy, y2 + 1, step):
            commands.append(f"fill {ox} {y} {oz} {x2} {min(y + step - 1, y2)} {z2} air")
    commands += to_commands(grid, palette, (ox, oy, oz), skip_air=clear)

    with _build_lock:
        _load_area(ox, oz, x2, z2)
        try:
            started = time.time() - 1
            undo_name = f"dashboard_undo_{int(time.time())}"
            previous = last_build()
            if previous:
                mc.send(f"structure delete {previous['undo']}")
            mc.send(f"structure save {undo_name} {ox} {oy} {oz} {x2} {y2} {z2} disk")
            # Recorded before placing, so a build that fails halfway can still be undone
            report = {"label": label, "time": time.time(), "undo": undo_name,
                      "from": [ox, oy, oz], "to": [x2, y2, z2], "commands": len(commands)}
            mc.DATA_DIR.mkdir(parents=True, exist_ok=True)
            UNDO_FILE.write_text(json.dumps(report))
            mc.send_many(commands)
            # The server works through roughly 20 commands a second
            _wait_until_idle((ox, oz), timeout=60 + len(commands) / 8)
            log = mc.logs_since(started)
        finally:
            _unload_area()

    filled = sum(int(n) for n in re.findall(r"(\d+) blocks filled", log))
    errors = sorted(set(re.findall(r"ERROR\] (Syntax error[^\n]*|Cannot place blocks[^\n]*)", log)))
    report.update(blocks_changed=filled, errors=errors[:5])
    UNDO_FILE.write_text(json.dumps(report))
    return report


def last_build() -> dict | None:
    try:
        return json.loads(UNDO_FILE.read_text())
    except Exception:
        return None


def undo_last() -> dict:
    """Put the area back the way it was before the most recent build."""
    build = last_build()
    if not build:
        raise RuntimeError("Nothing to undo")
    if not mc.server_running():
        raise RuntimeError("The server isn't running")
    (x1, y1, z1), (x2, _, z2) = build["from"], build["to"]
    with _build_lock:
        _load_area(x1, z1, x2, z2)
        try:
            answer = mc.ask(f"structure load {build['undo']} {x1} {y1} {z1}",
                            r"Loaded a structure|can't be found|ERROR\] [^\n]*structure[^\n]*", timeout=30)
            if not answer or "Loaded" not in answer.group(0):
                raise RuntimeError("The saved copy of that area is gone, so it can't be undone")
            mc.send(f"structure delete {build['undo']}")
        finally:
            _unload_area()
    UNDO_FILE.unlink(missing_ok=True)
    return build
