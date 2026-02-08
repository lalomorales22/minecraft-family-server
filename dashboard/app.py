import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import docker
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request
from mcstatus import BedrockServer

app = Flask(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_DIR / "dashboard" / "history.json"
PROPERTIES_FILE = PROJECT_DIR / "server-data" / "server.properties"
DOCKER_COMPOSE_DIR = str(PROJECT_DIR)
CONTAINER_NAME = "minecraft-bedrock"
SERVER_HOST = "localhost"
SERVER_PORT = 19133

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
    DATA_FILE.write_text(json.dumps(data, indent=2))


history = _load_history()

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
    try:
        server = BedrockServer.lookup(f"{SERVER_HOST}:{SERVER_PORT}")
        status = server.status()
        online = status.players.online
    except Exception:
        online = 0

    _parse_player_events()

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
    try:
        server = BedrockServer.lookup(f"{SERVER_HOST}:{SERVER_PORT}")
        status = server.status()
        return jsonify({
            "online": True,
            "motd": str(status.motd),
            "players_online": status.players.online,
            "players_max": status.players.max,
            "latency": round(status.latency, 1),
            "gamemode": status.gamemode if hasattr(status, "gamemode") else "Survival",
            "version": status.version.name if status.version else "Unknown",
            "map_name": status.map_name if hasattr(status, "map_name") else "FamilyWorld",
        })
    except Exception as e:
        return jsonify({
            "online": False,
            "motd": "",
            "players_online": 0,
            "players_max": 0,
            "latency": 0,
            "gamemode": "Unknown",
            "version": "Unknown",
            "map_name": "Unknown",
            "error": str(e),
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
        if action == "start":
            subprocess.run(["docker", "compose", "up", "-d"], cwd=DOCKER_COMPOSE_DIR, check=True)
        elif action == "stop":
            subprocess.run(["docker", "compose", "down"], cwd=DOCKER_COMPOSE_DIR, check=True)
        elif action == "restart":
            subprocess.run(["docker", "compose", "restart"], cwd=DOCKER_COMPOSE_DIR, check=True)
        return jsonify({"success": True, "action": action})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/command", methods=["POST"])
def api_command():
    """Send a command to the Bedrock server console."""
    cmd = request.json.get("command", "").strip()
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
    data = request.json or {}
    updates = {}
    for key in SETTINGS_KEYS:
        if key in data:
            updates[key] = str(data[key])
    if not updates:
        return jsonify({"error": "No valid settings provided"}), 400
    try:
        _write_properties(updates)
        # Restart the container so changes take effect
        subprocess.run(
            ["docker", "compose", "restart"],
            cwd=DOCKER_COMPOSE_DIR,
            check=True,
        )
        return jsonify({"success": True, "updated": updates})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    poll_server()  # initial poll
    app.run(host="0.0.0.0", port=8080, debug=False)
