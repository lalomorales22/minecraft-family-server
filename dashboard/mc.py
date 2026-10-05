"""Shared plumbing for talking to the Bedrock server container.

Everything the feature modules need: paths, server.properties, sending console
commands, reading their output back from the log, and who is online.
"""
import calendar
import os
import re
import socket
import struct
import threading
import time
from pathlib import Path

import docker

# Defaults work when running `python app.py` straight from a checkout;
# docker-compose.yml overrides them for the containerised dashboard.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_DIR / "dashboard" / "data"))
SERVER_DIR = Path(os.environ.get("SERVER_DATA_DIR", PROJECT_DIR / "server-data"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", PROJECT_DIR / "backups"))
PROPERTIES_FILE = SERVER_DIR / "server.properties"
WORLDS_DIR = SERVER_DIR / "worlds"

CONTAINER_NAME = "minecraft-bedrock"
SERVER_HOST = os.environ.get("SERVER_HOST", "localhost")
SERVER_PORT = 19133
# The LAN address consoles use to reach this computer (written by start.sh)
HOST_IP = os.environ.get("HOST_IP", "")

_docker_client = None


def container():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client.containers.get(CONTAINER_NAME)


def server_running() -> bool:
    try:
        return container().status == "running"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# server.properties
# ---------------------------------------------------------------------------

def read_properties() -> dict[str, str]:
    """Parse server.properties into a dict (ignoring comments)."""
    props: dict[str, str] = {}
    if PROPERTIES_FILE.exists():
        for line in PROPERTIES_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()
    return props


def write_properties(updates: dict[str, str]) -> None:
    """Update keys in server.properties, preserving comments; missing keys are appended."""
    remaining = dict(updates)
    new_lines = []
    for line in PROPERTIES_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    new_lines.extend(f"{key}={value}" for key, value in remaining.items())
    PROPERTIES_FILE.write_text("\n".join(new_lines) + "\n")


def active_world() -> str:
    return read_properties().get("level-name", "Bedrock level")


# ---------------------------------------------------------------------------
# Console commands
# ---------------------------------------------------------------------------

# Reading a command's answer means watching the log, so only one caller at a
# time may be waiting on output or their answers would get mixed up.
_capture_lock = threading.RLock()

COMMAND_FILE = ".dashboard-commands.txt"
# Same process lookup as the image's own send-command, done once for the whole
# batch, with a short pause every few lines so the console keeps up.
_BULK_SCRIPT = r"""
proc=$(find /proc -mindepth 2 -maxdepth 2 -name exe \( -lname '/data/bedrock_server-*' -o -lname /usr/local/bin/box64 \) -printf '%h' -quit)
[ -n "$proc" ] || exit 2
n=0
while IFS= read -r line; do
  echo "$line" > "$proc/fd/0"
  n=$((n+1))
  if [ $((n % 10)) -eq 0 ]; then sleep 0.05; fi
done < /data/""" + COMMAND_FILE


def send(command: str) -> None:
    """Send one command to the server console."""
    command = command.replace("\n", " ").replace("\r", " ").strip()
    result = container().exec_run(["send-command", command])
    if result.exit_code != 0:
        raise RuntimeError(result.output.decode("utf-8", errors="replace").strip() or "Server is not running")


def send_many(commands: list[str]) -> None:
    """Send a large batch of commands (used for builds)."""
    (SERVER_DIR / COMMAND_FILE).write_text("\n".join(c.replace("\n", " ") for c in commands) + "\n")
    try:
        result = container().exec_run(["bash", "-c", _BULK_SCRIPT])
        if result.exit_code != 0:
            raise RuntimeError("Server is not running")
    finally:
        (SERVER_DIR / COMMAND_FILE).unlink(missing_ok=True)


def logs_since(start: float) -> str:
    return container().logs(since=start).decode("utf-8", errors="replace")


def ask(command: str, pattern: str, timeout: float = 5.0) -> re.Match | None:
    """Send a command and wait for a log line matching `pattern`."""
    with _capture_lock:
        start = time.time() - 1
        before = len(re.findall(pattern, logs_since(start)))
        send(command)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            matches = list(re.finditer(pattern, logs_since(start)))
            if len(matches) > before:
                return matches[-1]
        return None


def flush_world(timeout: float = 30.0) -> list[tuple[str, int]]:
    """Make the server write the world to disk and pause further writes.

    Returns the (path relative to worlds/, length) list the server says is
    safe to copy. The caller MUST call resume_world() afterwards.
    """
    with _capture_lock:
        start = time.time() - 1
        send("save hold")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            send("save query")
            time.sleep(0.5)
            log = logs_since(start)
            ready = log.rfind("Files are now ready to be copied.")
            if ready != -1:
                listing = log[ready:].split("\n", 2)
                if len(listing) > 1:
                    return [(path, int(size)) for path, size in re.findall(r"\s*(.+?):(\d+)(?:,|$)", listing[1].strip())]
        raise RuntimeError("The server didn't finish saving in time")


def resume_world() -> None:
    try:
        send("save resume")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Is a Bedrock server answering?
# ---------------------------------------------------------------------------

RAKNET_MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")


def ping_bedrock(host: str, port: int, timeout: float = 3.0) -> dict | None:
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


def installed_version() -> str:
    """The server image names its binary bedrock_server-<version>."""
    binaries = sorted(SERVER_DIR.glob("bedrock_server-*"))
    return binaries[-1].name.removeprefix("bedrock_server-") if binaries else "Unknown"


# ---------------------------------------------------------------------------
# Who is online
# ---------------------------------------------------------------------------

class PlayerTracker:
    """Follows join/leave lines in the server log.

    Reads only what is new since the last look, so a burst of other log output
    (a big build, say) can't push the join lines out of view.
    """

    def __init__(self):
        self.connected: set[str] = set()
        self.events: list[dict] = []
        self._last_stamp = ""
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            try:
                box = container()
                kwargs = {"timestamps": True}
                if self._last_stamp:
                    # Docker's `since` is whole seconds; exact de-duplication is done on the stamp below
                    kwargs["since"] = _stamp_to_epoch(self._last_stamp)
                raw = box.logs(**kwargs).decode("utf-8", errors="replace")
            except Exception:
                self.connected = set()
                return
            for line in raw.splitlines():
                stamp, _, text = line.partition(" ")
                if stamp <= self._last_stamp:
                    continue
                self._last_stamp = stamp
                if "Starting Server" in text:
                    self.connected.clear()
                    continue
                joined = re.search(r"Player connected:\s*(.+?),\s*xuid", text)
                left = re.search(r"Player disconnected:\s*(.+?),\s*xuid", text)
                if joined:
                    name = joined.group(1).strip()
                    self.connected.add(name)
                    self.events.append({"player": name, "action": "joined", "time": _log_time(text)})
                elif left:
                    name = left.group(1).strip()
                    self.connected.discard(name)
                    self.events.append({"player": name, "action": "left", "time": _log_time(text)})
            self.events = self.events[-20:]


def _stamp_to_epoch(stamp: str) -> int:
    # 2026-10-04T22:49:15.856123456Z -> epoch seconds
    return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))


def _log_time(line: str) -> str:
    m = re.match(r"\[?([\d\-T: .]+)\]?", line)
    return m.group(1).strip() if m else time.strftime("%H:%M:%S")


players = PlayerTracker()


def safe_player(name: str) -> str:
    """Validate a player name for use inside a command and return it quoted."""
    players.refresh()
    if name not in players.connected or '"' in name or "\n" in name:
        raise ValueError(f"{name} isn't online")
    return f'"{name}"'


def player_position(name: str) -> tuple[float, float, float] | None:
    """Ask the server where a player is standing (feet position)."""
    match = ask(f"querytarget {safe_player(name)}", r"Target data: (\[.*\])", timeout=3)
    if not match:
        return None
    position = re.search(r'"position"\s*:\s*\{\s*"x"\s*:\s*(-?[\d.]+)\s*,\s*"y"\s*:\s*(-?[\d.]+)\s*,\s*"z"\s*:\s*(-?[\d.]+)',
                         match.group(1))
    if not position:
        return None
    x, y, z = (float(v) for v in position.groups())
    return x, y - 1.62, z  # the server reports eye height
