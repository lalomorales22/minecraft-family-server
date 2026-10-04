import json
import os
import re
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import docker
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Defaults work when running `python app.py` straight from a checkout;
# docker-compose.yml overrides them for the containerised dashboard.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_DIR / "dashboard" / "data"))
DATA_FILE = DATA_DIR / "history.json"
PROPERTIES_FILE = Path(os.environ.get("PROPERTIES_FILE", PROJECT_DIR / "server-data" / "server.properties"))
CONTAINER_NAME = "minecraft-bedrock"
SERVER_HOST = os.environ.get("SERVER_HOST", "localhost")
SERVER_PORT = 19133
BEDROCKCONNECT_PORT = 19132
# The LAN address consoles use to reach this computer (written by start.sh)
HOST_IP = os.environ.get("HOST_IP", "")
# A Featured Server hostname the DNS container redirects to HOST_IP
DNS_TEST_NAME = "hivebedrock.network"

# Settings keys we expose through the API
SETTINGS_KEYS = ("gamemode", "difficulty", "allow-cheats", "max-players")

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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


history = _load_history()

# ---------------------------------------------------------------------------
# Is a Bedrock server answering?
# ---------------------------------------------------------------------------

RAKNET_MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")


def _ping_bedrock(host: str, port: int, timeout: float = 3.0) -> dict | None:
    """Send a RakNet "unconnected ping". Returns None if nothing answers.

    Bedrock servers from 1.26.5x on answer in raknet mode *without* the usual
    "MCPE;name;protocol;version;online;max;..." description, so everything
    except `latency` is optional and callers fall back to server.properties.
    """
    start = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            ping = b"\x01" + struct.pack(">Q", int(time.time() * 1000)) + RAKNET_MAGIC + struct.pack(">Q", 2)
            s.sendto(ping, (host, port))
            data, _ = s.recvfrom(2048)
    except OSError:
        return None
    if not data or data[0] != 0x1C:
        return None
    info: dict = {"latency": round((time.monotonic() - start) * 1000, 1)}
    fields = data[35:].decode("utf-8", errors="replace").split(";")
    try:
        if len(fields) >= 6:
            info.update(motd=fields[1], version=fields[3],
                        players_online=int(fields[4]), players_max=int(fields[5]))
        if len(fields) >= 9:
            info.update(map_name=fields[7], gamemode=fields[8])
    except ValueError:
        pass
    return info


def _installed_version() -> str:
    """The server image names its binary bedrock_server-<version>."""
    binaries = sorted(PROPERTIES_FILE.parent.glob("bedrock_server-*"))
    return binaries[-1].name.removeprefix("bedrock_server-") if binaries else "Unknown"


# ---------------------------------------------------------------------------
# Track connected players by tailing Docker logs
# ---------------------------------------------------------------------------

connected_players: set[str] = set()
player_log: list[dict] = []  # recent join/leave events


def _parse_player_events():
    """Parse the Bedrock server Docker logs for connect/disconnect events."""
    global connected_players
    try:
        client = docker.from_env()
        container = client.containers.get(CONTAINER_NAME)
        # Get last 200 lines of logs
        logs = container.logs(tail=500).decode("utf-8", errors="replace")
        current = set()
        events = []
        for line in logs.splitlines():
            m_connect = re.search(r"Player connected:\s*(.+?)(?:,|\s*xuid)", line, re.IGNORECASE)
            m_disconnect = re.search(r"Player disconnected:\s*(.+?)(?:,|\s*xuid)", line, re.IGNORECASE)
            if m_connect:
                name = m_connect.group(1).strip()
                current.add(name)
                events.append({"player": name, "action": "joined", "time": _extract_time(line)})
            if m_disconnect:
                name = m_disconnect.group(1).strip()
                current.discard(name)
                events.append({"player": name, "action": "left", "time": _extract_time(line)})
        connected_players = current
        return events[-20:]  # last 20 events
    except Exception:
        return []


def _extract_time(line: str) -> str:
    m = re.match(r"\[?([\d\-T: .]+)\]?", line)
    if m:
        return m.group(1).strip()
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Scheduled polling – runs every 30 seconds
# ---------------------------------------------------------------------------

def poll_server():
    global history
    info = _ping_bedrock(SERVER_HOST, SERVER_PORT)
    _parse_player_events()
    online = info.get("players_online", len(connected_players)) if info else 0

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
    for p in connected_players:
        if p not in history.get("known_players", []):
            history.setdefault("known_players", []).append(p)
    history["total_unique"] = len(history.get("known_players", []))
    _save_history(history)


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(poll_server, "interval", seconds=30)
scheduler.start()

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    info = _ping_bedrock(SERVER_HOST, SERVER_PORT)
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
    props = _read_properties()
    _parse_player_events()
    return jsonify({
        "online": True,
        "motd": info.get("motd") or props.get("server-name", ""),
        "players_online": info.get("players_online", len(connected_players)),
        "players_max": info.get("players_max") or int(props.get("max-players") or 0),
        "latency": info["latency"],
        "gamemode": info.get("gamemode") or props.get("gamemode", "Unknown").capitalize(),
        "version": info.get("version") or _installed_version(),
        "map_name": info.get("map_name") or props.get("level-name", "Unknown"),
    })


@app.route("/api/players")
def api_players():
    events = _parse_player_events()
    return jsonify({
        "connected": sorted(connected_players),
        "recent_events": events,
    })


@app.route("/api/stats")
def api_stats():
    try:
        client = docker.from_env()
        container = client.containers.get(CONTAINER_NAME)
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
        client = docker.from_env()
        container = client.containers.get(CONTAINER_NAME)
        lines = int(request.args.get("lines", 50))
        logs = container.logs(tail=lines).decode("utf-8", errors="replace")
        return jsonify({"logs": logs.splitlines()})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e)})


@app.route("/api/server/<action>", methods=["POST"])
def api_server_action(action):
    if action not in ("start", "stop", "restart"):
        return jsonify({"error": "Invalid action"}), 400
    try:
        container = docker.from_env().containers.get(CONTAINER_NAME)
        getattr(container, action)()
        return jsonify({"success": True, "action": action})
    except docker.errors.NotFound:
        return jsonify({"success": False, "error": "Server isn't set up yet. Run ./start.sh on the computer."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/command", methods=["POST"])
def api_command():
    """Send a command to the Bedrock server console."""
    cmd = (request.get_json(silent=True) or {}).get("command", "").strip()
    if not cmd:
        return jsonify({"error": "No command provided"}), 400
    try:
        client = docker.from_env()
        container = client.containers.get(CONTAINER_NAME)
        result = container.exec_run(f"send-command {cmd}")
        return jsonify({"output": result.output.decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

def _read_properties() -> dict[str, str]:
    """Parse server.properties into a dict (ignoring comments)."""
    props: dict[str, str] = {}
    if PROPERTIES_FILE.exists():
        for line in PROPERTIES_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()
    return props


def _write_properties(updates: dict[str, str]) -> None:
    """Update specific keys in server.properties while preserving comments."""
    lines = PROPERTIES_FILE.read_text().splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            if key.strip() in updates:
                new_lines.append(f"{key.strip()}={updates[key.strip()]}")
                continue
        new_lines.append(line)
    PROPERTIES_FILE.write_text("\n".join(new_lines) + "\n")


@app.route("/api/settings")
def api_settings_get():
    props = _read_properties()
    return jsonify({k: props.get(k, "") for k in SETTINGS_KEYS})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.get_json(silent=True) or {}
    updates = {}
    for key in SETTINGS_KEYS:
        if key in data:
            updates[key] = str(data[key])
    if not updates:
        return jsonify({"error": "No valid settings provided"}), 400
    if not PROPERTIES_FILE.exists():
        return jsonify({"success": False, "error": "The world is still being created. Try again in a minute."}), 409
    try:
        _write_properties(updates)
        # Restart the container so changes take effect
        docker.from_env().containers.get(CONTAINER_NAME).restart()
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

def _check_world(host_ip: str):
    if _ping_bedrock(host_ip, SERVER_PORT):
        return True, "Running"
    return False, "Not answering. It takes a minute or two to load after starting; if it stays red, run ./start.sh on the computer."


def _check_bridge(host_ip: str):
    if _ping_bedrock(host_ip, BEDROCKCONNECT_PORT):
        return True, "Running"
    return False, "Not answering. Run ./start.sh on the computer."


def _check_dns(host_ip: str):
    try:
        answer = _dns_lookup(host_ip, DNS_TEST_NAME)
    except Exception:
        return False, "Not answering. Run ./start.sh on the computer."
    if answer == host_ip:
        return True, "Running"
    return False, f"Pointing at {answer or 'nothing'} instead of {host_ip}. Run ./start.sh on the computer."


SETUP_CHECKS = (
    ("world", "Minecraft world", _check_world),
    ("bridge", "Console server list", _check_bridge),
    ("dns", "Console shortcut (DNS)", _check_dns),
)


@app.route("/api/setup")
def api_setup():
    host_ip = HOST_IP or _guess_host_ip()
    with ThreadPoolExecutor(max_workers=len(SETUP_CHECKS)) as pool:
        results = list(pool.map(lambda check: check[2](host_ip), SETUP_CHECKS))
    checks = [
        {"id": check_id, "label": label, "ok": ok, "detail": detail}
        for (check_id, label, _), (ok, detail) in zip(SETUP_CHECKS, results)
    ]
    # start.sh reads this form: one "ok|id|label" or "fail|id|label" line per check
    if request.args.get("format") == "text":
        lines = [f"{'ok' if c['ok'] else 'fail'}|{c['id']}|{c['label']}" for c in checks]
        return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; charset=utf-8"}
    return jsonify({
        "host_ip": host_ip,
        "server_port": SERVER_PORT,
        "ready": all(c["ok"] for c in checks),
        "checks": checks,
    })


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    poll_server()  # initial poll
    app.run(host="0.0.0.0", port=8080, debug=False)
