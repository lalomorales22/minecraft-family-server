#!/bin/bash
# ===========================================
#  Minecraft Bedrock Family Server - Startup
# ===========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

if [ -z "$LOCAL_IP" ]; then
    echo "ERROR: Could not detect local IP. Are you connected to Wi-Fi?"
    exit 1
fi

echo "============================================"
echo "  Minecraft Bedrock Family Server"
echo "============================================"
echo ""
echo "  Your server IP: $LOCAL_IP"
echo "  Bedrock server:   port 19133"
echo "  BedrockConnect:   port 19132"
echo "  DNS server:       port 53"
echo ""

# --- 1. Start the Bedrock server ---
echo "  [1/3] Starting Bedrock Dedicated Server..."
docker compose up -d
echo ""

# --- 2. Download BedrockConnect if not present ---
BCJAR="$SCRIPT_DIR/bedrockconnect/BedrockConnect-1.0-SNAPSHOT.jar"
if [ ! -f "$BCJAR" ]; then
    echo "  Downloading BedrockConnect..."
    mkdir -p "$SCRIPT_DIR/bedrockconnect"
    curl -L -o "$BCJAR" \
        "https://github.com/Pugmatt/BedrockConnect/releases/latest/download/BedrockConnect-1.0-SNAPSHOT.jar"
fi

# Write custom servers list
CUSTOM_SERVERS="$SCRIPT_DIR/bedrockconnect/custom_servers.json"
cat > "$CUSTOM_SERVERS" <<EOF
[{"name":"Family Server","iconUrl":"","address":"$LOCAL_IP","port":19133}]
EOF

# --- 3. Start DNS server (dnsmasq) ---
echo "  [2/3] Starting DNS server..."
echo "        (sudo required to bind to port 53)"

# Generate dnsmasq config with the actual local IP
DNSCONF="$SCRIPT_DIR/bedrockconnect/dnsmasq.conf"
sed "s/LOCALIP/$LOCAL_IP/g" "$DNSCONF" > /tmp/bedrockconnect-dnsmasq.conf

# Kill any existing dnsmasq for BedrockConnect
sudo killall dnsmasq 2>/dev/null

sudo /opt/homebrew/opt/dnsmasq/sbin/dnsmasq \
    -C /tmp/bedrockconnect-dnsmasq.conf \
    --pid-file=/tmp/bedrockconnect-dnsmasq.pid

if [ $? -eq 0 ]; then
    echo "  DNS server started."
else
    echo "  ERROR: DNS server failed to start!"
    echo "  Check if port 53 is already in use: sudo lsof -i :53"
    exit 1
fi

echo ""
echo "  [3/3] Starting BedrockConnect proxy..."
echo ""
echo "============================================"
echo "  ALL SYSTEMS RUNNING"
echo ""
echo "  CONSOLE SETUP (one-time):"
echo "  On each PS5/Switch, set DNS to:"
echo "    Primary DNS:   $LOCAL_IP"
echo "    Secondary DNS: 8.8.8.8"
echo ""
echo "  Then: Servers tab -> pick any Featured Server"
echo "  -> BedrockConnect menu will appear"
echo "  -> Select 'Family Server' to join"
echo "============================================"
echo ""
echo "  Press Ctrl+C to stop BedrockConnect"
echo ""

# --- Start BedrockConnect (runs in foreground) ---
java -jar "$BCJAR" nodb=true custom_servers="$CUSTOM_SERVERS" packet_limit=1024 global_packet_limit=200000
