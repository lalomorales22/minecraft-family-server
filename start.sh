#!/bin/bash
# ===========================================
#  Minecraft Family Server - Start
#  The only thing you need installed is Docker Desktop.
#  Safe to run again any time (e.g. if something stops working).
# ===========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

DASHBOARD_URL="http://localhost:8080"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Minecraft Family Server${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# ------------------------------------------
# 1. Docker installed and running?
# ------------------------------------------
if ! command -v docker &>/dev/null; then
    fail "Docker Desktop is not installed."
    echo ""
    echo "    1. Download it (free): https://www.docker.com/products/docker-desktop/"
    echo "    2. Install it and open it once"
    echo "    3. Run ./start.sh again"
    echo ""
    [ "$(uname)" = "Darwin" ] && open "https://www.docker.com/products/docker-desktop/" 2>/dev/null
    exit 1
fi

if ! docker info &>/dev/null; then
    echo -n "  Starting Docker Desktop (can take a minute) "
    if [ "$(uname)" = "Darwin" ]; then
        open -ga "Docker" 2>/dev/null || open -ga "Docker Desktop" 2>/dev/null
    fi
    for _ in $(seq 1 60); do
        docker info &>/dev/null && break
        echo -n "."
        sleep 2
    done
    echo ""
    if ! docker info &>/dev/null; then
        fail "Docker isn't running. Open Docker Desktop, wait for it to finish starting, then run ./start.sh again."
        exit 1
    fi
fi
ok "Docker is running"

# ------------------------------------------
# 2. Find this computer's address on the home network
#    (override with: HOST_IP=192.168.1.50 ./start.sh)
# ------------------------------------------
detect_ip() {
    if [ "$(uname)" = "Darwin" ]; then
        local iface
        iface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
        [ -n "$iface" ] && ipconfig getifaddr "$iface" 2>/dev/null && return
        ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null
    else
        ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}'
    fi
}

OLD_IP=$(sed -n 's/^HOST_IP=//p' .env 2>/dev/null)
HOST_IP="${HOST_IP:-$(detect_ip)}"

if [ -z "$HOST_IP" ]; then
    fail "Couldn't find this computer's network address. Is it connected to Wi-Fi or Ethernet?"
    exit 1
fi
ok "This computer's address: ${BOLD}${HOST_IP}${NC}"

# .env also holds things you add yourself (like ANTHROPIC_API_KEY), so only
# the lines this script owns are rewritten.
set_env() {
    touch .env
    grep -v "^$1=" .env > .env.tmp || true
    echo "$1=$2" >> .env.tmp
    mv .env.tmp .env
}
set_env HOST_IP "$HOST_IP"

# Local time zone, so the nightly backup runs at night and backups show local times
if [ -L /etc/localtime ]; then
    set_env TZ "$(readlink /etc/localtime | sed 's#.*/zoneinfo/##')"
fi

mkdir -p server-data players bedrockconnect dashboard/data backups

# First run only: starting settings for the world. After this the dashboard
# owns them (Server Settings and Worlds panels).
if [ ! -f server-data/server.properties ]; then
    cat > server-data/server.properties <<EOF
level-name=FamilyWorld
gamemode=creative
difficulty=normal
allow-cheats=true
max-players=10
EOF
fi
cat > bedrockconnect/custom_servers.json <<EOF
[{"name":"Family Server","iconUrl":"","address":"$HOST_IP","port":19133}]
EOF

# Carry over player history from the pre-Docker dashboard
if [ -f dashboard/history.json ] && [ ! -f dashboard/data/history.json ]; then
    mv dashboard/history.json dashboard/data/history.json
fi

# ------------------------------------------
# 3. Start everything
# ------------------------------------------
echo "  Starting the server (the first time downloads a few things)..."
if ! docker compose up -d --build --remove-orphans --quiet-pull >/tmp/minecraft-family-start.log 2>&1; then
    tail -15 /tmp/minecraft-family-start.log
    echo ""
    fail "Something couldn't start."
    if grep -qiE "address already in use|port is already allocated|ports are not available" /tmp/minecraft-family-start.log; then
        echo "    Another program is using a port this server needs (53, 19132, 19133 or 8080)."
        echo "    - If you ran an older version of this project: press Ctrl+C in its window, then  sudo killall dnsmasq"
        echo "    - On a Mac, turn off Internet Sharing (System Settings > General > Sharing)"
        echo "    - To see what's using port 53:  sudo lsof -nP -i :53"
    fi
    exit 1
fi
ok "Containers started"

# ------------------------------------------
# 4. Wait until it's really ready, then check each piece
#    The dashboard tests the same address + ports the consoles will use.
# ------------------------------------------
setup_check() { curl -s -m 15 "$DASHBOARD_URL/api/setup?format=text" 2>/dev/null; }
all_ok()      { [ -n "$1" ] && ! echo "$1" | grep -q "^fail"; }

echo -n "  Waiting for the Minecraft world to load "
CHECKS=""
HEALED=0
for i in $(seq 1 40); do
    CHECKS=$(setup_check)
    all_ok "$CHECKS" && break
    # Docker Desktop sometimes doesn't open a port the first time around;
    # recreating that one container fixes it. Try once.
    if [ "$HEALED" = 0 ] && [ "$i" -ge 5 ] && echo "$CHECKS" | grep -qE "^fail\|(bridge|dns)"; then
        HEALED=1
        docker compose up -d --force-recreate bedrockconnect dns >>/tmp/minecraft-family-start.log 2>&1
    fi
    echo -n "."
    sleep 3
done
echo ""

if [ -z "$CHECKS" ]; then
    warn "The dashboard isn't answering yet, so the setup couldn't be checked. Try ./start.sh again in a minute."
else
    while IFS='|' read -r status _ label; do
        [ -z "$label" ] && continue
        if [ "$status" = "ok" ]; then ok "$label"; else fail "$label"; fi
    done <<< "$CHECKS"
fi

if ! all_ok "$CHECKS"; then
    echo ""
    warn "Not everything is ready. If the world was still loading, wait a minute and"
    warn "check the Setup Check box in the dashboard. Otherwise run ./start.sh again."
    echo ""
    echo -e "  Dashboard: ${BOLD}${DASHBOARD_URL}${NC}"
    echo ""
    exit 1
fi

# ------------------------------------------
# 5. Tell the human what to do next
# ------------------------------------------
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  READY!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
if [ -n "$OLD_IP" ] && [ "$OLD_IP" != "$HOST_IP" ]; then
    echo -e "  ${YELLOW}${BOLD}This computer's address changed${NC}${YELLOW} ($OLD_IP -> $HOST_IP).${NC}"
    echo -e "  ${YELLOW}Update the Primary DNS on each console to the new number below.${NC}"
    echo ""
fi
echo "  On each PlayStation / Switch / Xbox (one time only):"
echo ""
echo -e "      Primary DNS:    ${BOLD}${HOST_IP}${NC}"
echo -e "      Secondary DNS:  ${BOLD}8.8.8.8${NC}"
echo ""
echo "  Then in Minecraft:  Play > Servers > The Hive > Family Server"
echo ""
echo "  Step-by-step guide for each console, plus server"
echo "  controls, are in the dashboard:"
echo ""
echo -e "      ${BOLD}${DASHBOARD_URL}${NC}        (this computer)"
echo -e "      ${BOLD}http://${HOST_IP}:8080${NC}   (phone / other devices)"
echo ""
echo "  You can close this window — the server keeps running, and comes"
echo "  back by itself after a restart. To turn it off:  ./stop.sh"
echo ""

if [ "$(uname)" = "Darwin" ] && [ -z "$NO_OPEN" ]; then
    open "$DASHBOARD_URL" 2>/dev/null
fi
