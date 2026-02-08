#!/bin/bash
# Stop the Minecraft Bedrock server, BedrockConnect, and DNS
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Stopping Minecraft Bedrock server..."
docker compose down

echo "Stopping DNS server..."
if [ -f /tmp/bedrockconnect-dnsmasq.pid ]; then
    sudo kill "$(cat /tmp/bedrockconnect-dnsmasq.pid)" 2>/dev/null
    rm -f /tmp/bedrockconnect-dnsmasq.pid
else
    sudo killall dnsmasq 2>/dev/null
fi

echo "All services stopped."
