import io
import json
import re
import socket
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import docker
import segno
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, jsonify, render_template, request, send_file

import ai
import backups
import builder
import mc
import worlds
from worldmap import WorldMap

app = Flask(__name__)

DATA_FILE = mc.DATA_DIR / "history.json"
DESIGN_DIR = mc.DATA_DIR / "designs"
BEDROCKCONNECT_PORT = 19132
# A Featured Server hostname the DNS container redirects to HOST_IP
DNS_TEST_NAME = "hivebedrock.network"

# Settings keys we expose through the API
SETTINGS_KEYS = ("gamemode", "difficulty", "allow-cheats", "max-players")

# Chatter from the dashboard's own commands that would drown out the console panel
LOG_NOISE = re.compile(r"Target data:|No targets matched selector|\d+ blocks filled|Successfully found the block"
                       r"|Cannot test for block outside|icking area|Saving\.\.\.|Data saved\.|Changes to the world are resumed"
                       r"|^\S+/db/|^- dashboard_build|dashboard_undo_|^\s*$")


def body() -> dict:
    return request.get_json(silent=True) or {}


def fail(message, status=400):
    return jsonify({"success": False, "error": str(message)}), status


# ---------------------------------------------------------------------------
# Persistent history
# ---------------------------------------------------------------------------

def _load_history():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text())
            # Keep only the last 24 hours
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            data["player_counts"] = [
                p for p in data.get("player_counts", []) if p["time"] > cutoff
            ]
            return data
        except Exception:
            pass
    return {"player_counts": [], "peak_players": 0, "total_unique": 0, "known_players": []}


def _save_history(data):
    mc.DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


history = _load_history()


# ---------------------------------------------------------------------------
# Scheduled polling – runs every 30 seconds
# ---------------------------------------------------------------------------

def poll_server():
    global history
    info = mc.ping_bedrock(mc.SERVER_HOST, mc.SERVER_PORT)
    mc.players.refresh()
    online = info.get("players_online", len(mc.players.connected)) if info else 0

    # Update history
    history["player_counts"].append({
        "time": datetime.utcnow().isoformat(),
        "count": online,
    })
    # Trim to 24h
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    history["player_counts"] = [p for p in history["player_counts"] if p["time"] > cutoff]
    if online > history.get("peak_players", 0):
        history["peak_players"] = online
    for p in mc.players.connected:
        if p not in history.get("known_players", []):
            history.setdefault("known_players", []).append(p)
    history["total_unique"] = len(history.get("known_players", []))
    _save_history(history)


# ---------------------------------------------------------------------------
# World map (one renderer per world, created on demand)
# ---------------------------------------------------------------------------

_map: WorldMap | None = None
_map_world = None
_map_lock = threading.Lock()


def world_map() -> WorldMap:
    global _map, _map_world
    with _map_lock:
        world = mc.active_world()
        if _map is None or _map_world != world:
            slug = re.sub(r"[^A-Za-z0-9_-]+", "_", world)
            _map = WorldMap(mc.WORLDS_DIR / world, mc.DATA_DIR / "map" / slug)
            _map_world = world
        return _map


def refresh_map():
    try:
        world_map().refresh()
    except Exception as e:
        print(f"[map] refresh failed: {e}", flush=True)


def save_and_redraw(force: bool = True) -> dict:
    """Ask the server to write the world to disk right now, then redraw the map."""
    if mc.server_running():
        try:
            mc.flush_world()
        finally:
            mc.resume_world()
    return world_map().refresh(force=force)


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(poll_server, "interval", seconds=30)
scheduler.add_job(refresh_map, "interval", seconds=30, max_instances=1, coalesce=True)
# A snapshot every few hours while people are playing, plus one kept per day
scheduler.add_job(backups.scheduled_backup, "interval", hours=3, args=["auto"], max_instances=1, coalesce=True)
scheduler.add_job(backups.scheduled_backup, "cron", hour=4, minute=0, args=["daily"], max_instances=1, coalesce=True)
scheduler.start()

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    info = mc.ping_bedrock(mc.SERVER_HOST, mc.SERVER_PORT)
    if info is None:
        return jsonify({
            "online": False,
            "motd": "",
            "players_online": 0,
            "players_max": 0,
            "latency": 0,
            "gamemode": "Unknown",
            "version": "Unknown",
            "map_name": "Unknown",
            "error": "Server is not answering",
        })
    props = mc.read_properties()
    mc.players.refresh()
    return jsonify({
        "online": True,
        "motd": info.get("motd") or props.get("server-name", ""),
        "players_online": info.get("players_online", len(mc.players.connected)),
        "players_max": info.get("players_max") or int(props.get("max-players") or 0),
        "latency": info["latency"],
        "gamemode": info.get("gamemode") or props.get("gamemode", "Unknown").capitalize(),
        "version": info.get("version") or mc.installed_version(),
        "map_name": info.get("map_name") or props.get("level-name", "Unknown"),
    })


@app.route("/api/players")
def api_players():
    mc.players.refresh()
    return jsonify({
        "connected": sorted(mc.players.connected),
        "recent_events": mc.players.events,
    })


@app.route("/api/stats")
def api_stats():
    try:
        container = mc.container()
        stats = container.stats(stream=False)

        # CPU
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                       stats["precpu_stats"]["system_cpu_usage"]
        num_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0

        # Memory
        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 1)
        mem_mb = mem_usage / (1024 * 1024)
        mem_percent = (mem_usage / mem_limit) * 100.0

        # Network
        net_stats = stats.get("networks", {})
        rx_bytes = sum(v.get("rx_bytes", 0) for v in net_stats.values())
        tx_bytes = sum(v.get("tx_bytes", 0) for v in net_stats.values())

        # Uptime
        info = container.attrs
        started = info.get("State", {}).get("StartedAt", "")

        return jsonify({
            "running": True,
            "cpu_percent": round(cpu_percent, 1),
            "memory_mb": round(mem_mb, 1),
            "memory_percent": round(mem_percent, 1),
            "network_rx_mb": round(rx_bytes / (1024 * 1024), 2),
            "network_tx_mb": round(tx_bytes / (1024 * 1024), 2),
            "started_at": started,
        })
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})


@app.route("/api/history")
def api_history():
    return jsonify(history)


@app.route("/api/logs")
def api_logs():
    try:
        lines = int(request.args.get("lines", 50))
        logs = mc.container().logs(tail=lines * 8).decode("utf-8", errors="replace")
        kept = [line for line in logs.splitlines() if not LOG_NOISE.search(line)]
        return jsonify({"logs": kept[-lines:]})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e)})


@app.route("/api/server/<action>", methods=["POST"])
def api_server_action(action):
    if action not in ("start", "stop", "restart"):
        return jsonify({"error": "Invalid action"}), 400
    try:
        getattr(mc.container(), action)()
        return jsonify({"success": True, "action": action})
    except docker.errors.NotFound:
        return jsonify({"success": False, "error": "Server isn't set up yet. Run ./start.sh on the computer."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/command", methods=["POST"])
def api_command():
    """Send a command to the Bedrock server console."""
    cmd = body().get("command", "").strip()
    if not cmd:
        return jsonify({"error": "No command provided"}), 400
    try:
        mc.send(cmd)
        return jsonify({"output": ""})
    except Exception as e:
        return jsonify({"error": str(e)})


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

@app.route("/api/settings")
def api_settings_get():
    props = mc.read_properties()
    return jsonify({k: props.get(k, "") for k in SETTINGS_KEYS})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = body()
    updates = {}
    for key in SETTINGS_KEYS:
        if key in data:
            updates[key] = str(data[key])
    if not updates:
        return jsonify({"error": "No valid settings provided"}), 400
    if not mc.PROPERTIES_FILE.exists():
        return jsonify({"success": False, "error": "The world is still being created. Try again in a minute."}), 409
    try:
        mc.write_properties(updates)
        worlds.remember_current()
        # Restart the container so changes take effect
        mc.container().restart()
        return jsonify({"success": True, "updated": updates})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Setup check – is every piece a console needs actually working?
# ---------------------------------------------------------------------------

def _guess_host_ip() -> str:
    """Best-effort LAN address when HOST_IP wasn't provided (running outside Docker)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return ""


def host_ip() -> str:
    return mc.HOST_IP or _guess_host_ip()


def _dns_lookup(server: str, name: str, timeout: float = 2.0) -> str:
    """Ask `server` for the A record of `name`; returns the first IPv4 answer or ''."""
    query = struct.pack(">HHHHHH", 0x4D43, 0x0100, 1, 0, 0, 0)
    query += b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    query += struct.pack(">HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(query, (server, 53))
        data, _ = s.recvfrom(512)
    answers = struct.unpack(">H", data[6:8])[0]
    pos = len(query)  # the answer section starts right after the echoed question
    for _ in range(answers):
        while data[pos] and data[pos] < 0xC0:  # owner name: labels...
            pos += data[pos] + 1
        pos += 2 if data[pos] >= 0xC0 else 1    # ...or a 2-byte pointer / root
        rtype, _, _, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        if rtype == 1 and rdlen == 4:
            return socket.inet_ntoa(data[pos:pos + 4])
        pos += rdlen
    return ""


# Each check goes through HOST_IP (this computer's LAN address) rather than the
# Docker-internal names, so it exercises the same path a console takes.

def _check_world(ip: str):
    if mc.ping_bedrock(ip, mc.SERVER_PORT):
        return True, "Running"
    return False, "Not answering. It takes a minute or two to load after starting; if it stays red, run ./start.sh on the computer."


def _check_bridge(ip: str):
    if mc.ping_bedrock(ip, BEDROCKCONNECT_PORT):
        return True, "Running"
    return False, "Not answering. Run ./start.sh on the computer."


def _check_dns(ip: str):
    try:
        answer = _dns_lookup(ip, DNS_TEST_NAME)
    except Exception:
        return False, "Not answering. Run ./start.sh on the computer."
    if answer == ip:
        return True, "Running"
    return False, f"Pointing at {answer or 'nothing'} instead of {ip}. Run ./start.sh on the computer."


SETUP_CHECKS = (
    ("world", "Minecraft world", _check_world),
    ("bridge", "Console server list", _check_bridge),
    ("dns", "Console shortcut (DNS)", _check_dns),
)


@app.route("/api/setup")
def api_setup():
    ip = host_ip()
    with ThreadPoolExecutor(max_workers=len(SETUP_CHECKS)) as pool:
        results = list(pool.map(lambda check: check[2](ip), SETUP_CHECKS))
    checks = [
        {"id": check_id, "label": label, "ok": ok, "detail": detail}
        for (check_id, label, _), (ok, detail) in zip(SETUP_CHECKS, results)
    ]
    # start.sh reads this form: one "ok|id|label" or "fail|id|label" line per check
    if request.args.get("format") == "text":
        lines = [f"{'ok' if c['ok'] else 'fail'}|{c['id']}|{c['label']}" for c in checks]
        return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; charset=utf-8"}
    return jsonify({
        "host_ip": ip,
        "server_port": mc.SERVER_PORT,
        "dashboard_url": f"http://{ip}:8080",
        "ready": all(c["ok"] for c in checks),
        "checks": checks,
    })


@app.route("/api/qr.svg")
def api_qr():
    """QR code that opens the dashboard on a phone."""
    out = io.BytesIO()
    segno.make(f"http://{host_ip()}:8080", error="m").save(
        out, kind="svg", scale=5, border=2, dark="#0d0d1a", light="#ffffff", xmldecl=False)
    return Response(out.getvalue(), mimetype="image/svg+xml")


# ---------------------------------------------------------------------------
# Messages to everyone in the game
# ---------------------------------------------------------------------------

@app.route("/api/announce", methods=["POST"])
def api_announce():
    # No selectors, quotes or control characters: this text goes straight into a command
    message = re.sub(r"[@\"\\\x00-\x1f§]", "", str(body().get("message", ""))).strip()[:80]
    if not message:
        return fail("Type a message first")
    try:
        mc.players.refresh()
        mc.send(f"title @a title {message}")
        mc.send(f"say {message}")
        mc.send("execute as @a at @s run playsound random.levelup @s")
        return jsonify({"success": True, "message": message, "players": len(mc.players.connected)})
    except Exception as e:
        return fail(e, 500)


# ---------------------------------------------------------------------------
# Per-player actions
# ---------------------------------------------------------------------------

# {p} is the player, {t} a second player. Both are checked against who is online.
PLAYER_ACTIONS = {
    "heal": ["effect {p} instant_health 1 255 true", "effect {p} saturation 1 255 true"],
    "kit": ["give {p} iron_sword", "give {p} iron_pickaxe", "give {p} iron_axe", "give {p} iron_shovel",
            "give {p} bread 16", "give {p} torch 32"],
    "creative": ["gamemode creative {p}"],
    "survival": ["gamemode survival {p}"],
    "op": ["op {p}"],
    "deop": ["deop {p}"],
    "bring_all": ["tp @a {p}"],
    "tp_to": ["tp {p} {t}"],
}


@app.route("/api/player", methods=["POST"])
def api_player():
    data = body()
    commands = PLAYER_ACTIONS.get(data.get("action"))
    if data.get("action") == "tp_spot":
        # A spot picked on the map: land on top of whatever is there
        try:
            x, z = int(data["x"]), int(data["z"])
        except (KeyError, TypeError, ValueError):
            return fail("Pick a spot on the map first")
        surface = world_map().surface_height(x, z)
        if surface is None:
            return fail("That spot isn't on the map yet")
        commands = [f"tp {{p}} {x} {surface + 1} {z}"]
    if not commands:
        return fail("Unknown action")
    try:
        player = mc.safe_player(str(data.get("player", "")))
        target = mc.safe_player(str(data.get("target", ""))) if any("{t}" in c for c in commands) else ""
        for command in commands:
            mc.send(command.format(p=player, t=target))
        return jsonify({"success": True})
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 500)


# ---------------------------------------------------------------------------
# Worlds
# ---------------------------------------------------------------------------

@app.route("/api/worlds")
def api_worlds():
    return jsonify({"worlds": worlds.list_worlds(), "active": mc.active_world()})


@app.route("/api/worlds/switch", methods=["POST"])
def api_worlds_switch():
    try:
        worlds.switch_world(str(body().get("name", "")))
        return jsonify({"success": True})
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 500)


@app.route("/api/worlds/create", methods=["POST"])
def api_worlds_create():
    data = body()
    try:
        worlds.create_world(str(data.get("name", "")), str(data.get("gamemode", "survival")),
                            str(data.get("difficulty", "easy")), str(data.get("seed", "")))
        return jsonify({"success": True})
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 500)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

@app.route("/api/backups")
def api_backups():
    return jsonify({"backups": backups.list_backups(), "active": mc.active_world()})


@app.route("/api/backups", methods=["POST"])
def api_backups_create():
    try:
        return jsonify({"success": True, "backup": backups.create_backup("manual")})
    except Exception as e:
        return fail(e, 500)


@app.route("/api/backups/restore", methods=["POST"])
def api_backups_restore():
    try:
        return jsonify({"success": True, "backup": backups.restore_backup(str(body().get("id", "")))})
    except ValueError as e:
        return fail(e)
    except Exception as e:
        return fail(e, 500)


@app.route("/api/backups/delete", methods=["POST"])
def api_backups_delete():
    try:
        backups.delete_backup(str(body().get("id", "")))
        return jsonify({"success": True})
    except ValueError as e:
        return fail(e)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

@app.route("/api/map/info")
def api_map_info():
    return jsonify({**world_map().info(), "world": mc.active_world()})


@app.route("/api/map/tile/<rx>/<rz>.png")
def api_map_tile(rx, rz):
    try:
        path = world_map().tile_path(int(rx), int(rz))
    except ValueError:
        path = None
    if path is None:
        return "", 204   # unexplored: nothing to draw there
    return send_file(path, mimetype="image/png", max_age=0)


@app.route("/api/map/refresh", methods=["POST"])
def api_map_refresh():
    try:
        return jsonify({"success": True, **save_and_redraw()})
    except Exception as e:
        return fail(e, 500)


@app.route("/api/map/players")
def api_map_players():
    mc.players.refresh()
    found = []
    for name in sorted(mc.players.connected):
        try:
            position = mc.player_position(name)
        except Exception:
            position = None
        if position:
            found.append({"name": name, "x": round(position[0], 1), "y": round(position[1], 1), "z": round(position[2], 1)})
    return jsonify({"players": found})


@app.route("/api/map/height")
def api_map_height():
    try:
        x, z = int(float(request.args["x"])), int(float(request.args["z"]))
    except (KeyError, ValueError):
        return fail("x and z are required")
    return jsonify({"x": x, "z": z, "y": world_map().surface_height(x, z)})


# ---------------------------------------------------------------------------
# AI builder
# ---------------------------------------------------------------------------

designs: dict[str, dict] = {}       # id -> record; "plan" is kept server-side only
_grids: dict[str, tuple] = {}       # id -> (grid, palette), rebuilt from the plan when needed


def _design_record(design_id: str) -> dict | None:
    if design_id in designs:
        return designs[design_id]
    path = DESIGN_DIR / f"{design_id}.json"
    if re.fullmatch(r"[0-9a-f]{12}", design_id) and path.exists():
        designs[design_id] = json.loads(path.read_text())
        return designs[design_id]
    return None


def _save_design(record: dict) -> None:
    DESIGN_DIR.mkdir(parents=True, exist_ok=True)
    (DESIGN_DIR / f"{record['id']}.json").write_text(json.dumps(record))


def _grid_for(record: dict):
    if record["id"] not in _grids:
        _grids[record["id"]] = builder.voxelize(record["plan"]["ops"])
    return _grids[record["id"]]


def register_design(record: dict, plan: dict) -> None:
    """Draw a plan, work out its size and materials, and store it as ready to build."""
    grid, palette = builder.voxelize(plan["ops"])
    _grids[record["id"]] = (grid, palette)
    record.update(
        status="ready", plan=plan, name=plan["name"], summary=plan["summary"],
        stats=builder.describe(grid, palette),
        commands=len(builder.to_commands(grid, palette, (0, 0, 0), skip_air=True)),
    )
    designs[record["id"]] = record
    _save_design(record)


def load_samples() -> None:
    """Ready-made designs shipped with the dashboard, so the builder works without an API key."""
    for path in sorted((Path(__file__).resolve().parent / "samples").glob("*.json")):
        design_id = uuid.uuid5(uuid.NAMESPACE_URL, path.name).hex[:12]
        if not (DESIGN_DIR / f"{design_id}.json").exists():
            try:
                register_design({"id": design_id, "prompt": "", "sample": True, "created": 0},
                                json.loads(path.read_text()))
            except Exception as e:
                print(f"[samples] {path.name}: {e}", flush=True)


def _run_design(record: dict) -> None:
    try:
        register_design(record, ai.design(record["prompt"]))
    except (ai.DesignError, builder.PlanError) as e:
        record.update(status="error", error=str(e))
    except Exception as e:
        record.update(status="error", error=f"Something went wrong: {e}")


def _public(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "plan"}


@app.route("/api/ai/status")
def api_ai_status():
    recent = []
    if DESIGN_DIR.exists():
        for path in sorted(DESIGN_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
            record = _design_record(path.stem)
            if record:
                recent.append(_public(record))
    return jsonify({"available": ai.available(), "model": ai.MODEL, "max_size": builder.SIZE,
                    "last_build": builder.last_build(), "recent": recent})


@app.route("/api/ai/design", methods=["POST"])
def api_ai_design():
    if not ai.available():
        return fail("Add your Anthropic API key to the .env file and run ./start.sh again.", 409)
    prompt = str(body().get("prompt", "")).strip()[:1500]
    if len(prompt) < 3:
        return fail("Describe what you'd like built")
    if any(d["status"] == "designing" for d in designs.values()):
        return fail("Claude is already working on a design. Give it a minute.", 409)
    record = {"id": uuid.uuid4().hex[:12], "prompt": prompt, "status": "designing", "created": time.time()}
    designs[record["id"]] = record
    threading.Thread(target=_run_design, args=(record,), daemon=True).start()
    return jsonify({"success": True, "design": _public(record)})


@app.route("/api/ai/design/<design_id>")
def api_ai_design_get(design_id):
    record = _design_record(design_id)
    if not record:
        return fail("No such design", 404)
    return jsonify({"design": _public(record)})


@app.route("/api/ai/design/<design_id>/<view>.png")
def api_ai_design_preview(design_id, view):
    record = _design_record(design_id)
    if not record or "plan" not in record or view not in ("top", "front"):
        return "", 404
    grid, palette = _grid_for(record)
    return Response(builder.preview_png(grid, palette, view), mimetype="image/png")


def _run_build(record: dict, origin, clear: bool) -> None:
    try:
        grid, palette = _grid_for(record)
        record["build"] = builder.place(grid, palette, origin, clear=clear, label=record.get("name", ""))
    except Exception as e:
        record.update(status="ready", build_error=str(e))
        return
    try:
        save_and_redraw()   # so the map already shows it when the browser hears it's done
    except Exception as e:
        print(f"[map] redraw after build failed: {e}", flush=True)
    record["status"] = "built"
    _save_design(record)


@app.route("/api/ai/build", methods=["POST"])
def api_ai_build():
    data = body()
    record = _design_record(str(data.get("id", "")))
    if not record or "plan" not in record:
        return fail("No such design", 404)
    if any(d["status"] == "building" for d in designs.values()):
        return fail("Another build is still going", 409)
    try:
        grid, palette = _grid_for(record)
        size = builder.describe(grid, palette)["size"]
        if data.get("player"):
            position = mc.player_position(str(data["player"]))
            if not position:
                return fail("Couldn't find where that player is")
            # A few blocks east of the player, centred on them north-south, at their feet
            origin = (int(position[0]) + 4, int(round(position[1])), int(position[2]) - size["z"] // 2)
        else:
            x, z = int(data["x"]), int(data["z"])
            y = data.get("y")
            if y in (None, ""):
                world_map().refresh()
                surface = world_map().surface_height(x, z)
                if surface is None:
                    return fail("That spot isn't on the map yet, so type a height (Y) too")
                y = surface + 1
            # The spot the user picked becomes the middle of the build's footprint
            origin = (x - size["x"] // 2, int(y), z - size["z"] // 2)
    except (KeyError, TypeError, ValueError) as e:
        return fail(f"Pick where to build it ({e})")
    record.update(status="building", build_error=None)
    threading.Thread(target=_run_build, args=(record, origin, bool(data.get("clear", True))), daemon=True).start()
    return jsonify({"success": True, "origin": origin, "design": _public(record)})


@app.route("/api/ai/undo", methods=["POST"])
def api_ai_undo():
    try:
        undone = builder.undo_last()
        save_and_redraw()
        return jsonify({"success": True, "undone": undone})
    except Exception as e:
        return fail(e, 500)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    poll_server()  # initial poll
    load_samples()
    threading.Thread(target=refresh_map, daemon=True).start()  # first map draw
    app.run(host="0.0.0.0", port=8080, debug=False)
