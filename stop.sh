#!/bin/bash
# Stop the Minecraft server, console bridge, DNS and dashboard.
# Your world is saved in server-data/ and is not touched.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# docker compose needs HOST_IP to read the config, even just to stop
[ -f .env ] || export HOST_IP=127.0.0.1

echo "Stopping Minecraft Family Server..."
docker compose down
echo "Stopped. Run ./start.sh to bring it back."
