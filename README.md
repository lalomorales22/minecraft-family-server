# Minecraft Family Server
<img width="1037" height="1159" alt="Screenshot 2026-02-08 at 11 37 26 AM" src="https://github.com/user-attachments/assets/c072be3c-4906-49e6-b185-32ff57d7d29d" />

A self-hosted **Minecraft Bedrock Edition** dedicated server with a custom **Minecraft-themed web dashboard** for monitoring and management. Built for cross-play between **PS4, PS5, and Nintendo Switch**.

![Bedrock](https://img.shields.io/badge/Minecraft-Bedrock%20Edition-brightgreen)
![Docker](https://img.shields.io/badge/Docker-Powered-blue)
![Cross-Play](https://img.shields.io/badge/Cross--Play-PS4%20%7C%20PS5%20%7C%20Switch-orange)
[![GitHub](https://img.shields.io/badge/GitHub-lalomorales22%2Fminecraft--family--server-181717?logo=github)](https://github.com/lalomorales22/minecraft-family-server)

---

## What's Inside

| Component | Description |
|---|---|
| **Bedrock Dedicated Server** | Official Minecraft server running in Docker, always-on |
| **BedrockConnect** | DNS bridge that lets consoles (PS4/PS5/Switch) connect to the custom server |
| **Web Dashboard** | Minecraft-themed analytics panel with real-time monitoring |

### How It All Works Together

Consoles (PS4, PS5, Switch) can't type in custom server addresses — they can only connect to "Featured Servers" like The Hive. **BedrockConnect** gets around this by acting as a DNS server on your Mac. When a console tries to connect to a Featured Server, BedrockConnect intercepts the connection and shows you a server list instead, where your **Family Server** is waiting. Pick it, and you're redirected to the actual Bedrock server running in Docker.

```
Console → DNS lookup → BedrockConnect (port 19132) → Server list UI
                                                        ↓
                                              "Family Server" selected
                                                        ↓
                                          Bedrock Dedicated Server (port 19133)
```

## Features

### Dedicated Server
- 24/7 Minecraft Bedrock server running in Docker
- Persistent world data saved to `server-data/`
- Supports 10+ concurrent players with cross-play
- Auto-restarts on crash via Docker

### Web Dashboard
- **Real-time server status** — online/offline beacon, latency, version
- **Player tracking** — see who's connected, join/leave activity feed
- **Resource monitoring** — CPU, memory, network usage with visual bars
- **Player history chart** — 24-hour player count graph
- **Server console** — view logs and send commands from the browser
- **Server controls** — start, stop, restart with one click
- **Fully responsive** — works on desktop, tablet, and phone
- **Minecraft UI theme** — pixel fonts, block textures, dirt/stone aesthetic

---

## Requirements

- **macOS** (tested on macOS Sequoia / Darwin 25.x)
- **Docker Desktop** (for the Bedrock server)
- **Python 3.10+** (for the dashboard)
- **Java 17+** (for BedrockConnect)
- All consoles on the **same Wi-Fi / LAN** as the server
- A **free Microsoft / Xbox account** for each player

---

## Quick Start

### 1. Start the Minecraft Server + BedrockConnect

```bash
cd ~/Software/Minecraft
./start-server.sh
```

  - minecraft-server — starts Docker + DNS + BedrockConnect
  - minecraft-stop — stops everything                                           
  - minecraft-dashboard — starts the web dashboard on port 8080 

This starts:
- The Bedrock Dedicated Server on **port 19133** (Docker)
- BedrockConnect proxy + DNS on **port 19132 / port 53** (Java)

### 2. Start the Web Dashboard

In a second terminal:

```bash
cd ~/Software/Minecraft
./start-dashboard.sh
```

First run will create a Python virtual environment and install dependencies. The dashboard will be available at:

- **http://localhost:8080** (from your Mac)
- **http://`<YOUR_MAC_IP>`:8080** (from any device on your network)

---

## Device Setup

Every console needs two things:
1. **A Microsoft / Xbox account** signed into Minecraft (free — create one at [xbox.com/create-account](https://xbox.com/create-account))
2. **DNS settings changed** to point to your Mac's IP address

> **Find your Mac's IP address:** run `ipconfig getifaddr en0` in Terminal.
> Use this IP wherever you see `<YOUR_MAC_IP>` below.

---

### PlayStation 5

#### Step 1: Change DNS Settings

1. From the PS5 home screen, go to **Settings** (gear icon, top right)
2. Select **Network**
3. Select **Settings**
4. Select **Set Up Internet Connection**
5. Find your Wi-Fi network in the list and press the **Options button** (three lines) on your controller
6. Select **Advanced Settings**
7. Set the following:
   - IP Address Settings: **Automatic**
   - DHCP Host Name: **Do Not Specify**
   - DNS Settings: **Manual**
     - **Primary DNS: `<YOUR_MAC_IP>`**
     - **Secondary DNS: `8.8.8.8`**
   - MTU Settings: **Automatic**
   - Proxy Server: **Do Not Use**
8. Press **OK** to save

#### Step 2: Sign Into a Microsoft Account in Minecraft

1. Open **Minecraft** on the PS5
2. On the title screen, you should see a prompt to **Sign in with a Microsoft Account**
3. You'll get a code — go to [microsoft.com/link](https://microsoft.com/link) on your phone or computer
4. Enter the code and sign in (or create a free Xbox account)
5. Once signed in, you'll see your Gamertag on the Minecraft title screen

#### Step 3: Join the Family Server

1. From the Minecraft main menu, press **Play**
2. Go to the **Servers** tab (at the top)
3. Scroll down and select **any Featured Server** (The Hive, CubeCraft, Mineplex — doesn't matter which)
4. Instead of the Featured Server, the **BedrockConnect server list** will appear
5. You'll see **"Family Server"** in the list — select it
6. You're in! You should load into the family world

---

### PlayStation 4

#### Step 1: Change DNS Settings

1. From the PS4 home screen, go to **Settings**
2. Select **Network**
3. Select **Set Up Internet Connection**
4. Choose **Use Wi-Fi** (or LAN Cable if wired)
5. Select **Custom**
6. Set the following:
   - IP Address Settings: **Automatic**
   - DHCP Host Name: **Do Not Specify**
   - DNS Settings: **Manual**
     - **Primary DNS: `<YOUR_MAC_IP>`**
     - **Secondary DNS: `8.8.8.8`**
   - MTU Settings: **Automatic**
   - Proxy Server: **Do Not Use**
7. Select **Test Internet Connection** to confirm it works

#### Step 2: Sign Into a Microsoft Account in Minecraft

1. Open **Minecraft** on the PS4
2. On the title screen, press **Sign in with a Microsoft Account**
3. A code will appear on screen — go to [microsoft.com/link](https://microsoft.com/link) on your phone or computer
4. Enter the code and sign in with your Microsoft / Xbox account
5. Your Gamertag will show on the title screen when linked

#### Step 3: Join the Family Server

1. Press **Play** from the main menu
2. Navigate to the **Servers** tab
3. Select **any Featured Server** (The Hive, Mineplex, etc.)
4. The **BedrockConnect server list** appears instead
5. Select **"Family Server"** from the list
6. Done — you'll spawn into the family world

---

### Nintendo Switch (Switch 2)

> These instructions work for both the original Nintendo Switch and the Nintendo Switch 2. The menus are the same.

#### Step 1: Change DNS Settings

1. From the Switch home screen, go to **System Settings** (gear icon)
2. Scroll down in the left sidebar and select **Internet**
3. Select **Internet Settings**
4. Your connected Wi-Fi network will show at the top — select it
5. Select **Change Settings**
6. Scroll down to **DNS Settings** and change it from Automatic to **Manual**
   - **Primary DNS: `<YOUR_MAC_IP>`**
   - **Secondary DNS: `8.8.8.8`**
7. Press **Save**
8. Select **Connect to This Network** to test the connection

#### Step 2: Sign Into a Microsoft Account in Minecraft

1. Open **Minecraft** on the Switch
2. On the title screen, you'll see a **Sign in with a Microsoft Account** button on the left
3. Press it — a code will display on screen
4. On your phone or computer, go to [microsoft.com/link](https://microsoft.com/link)
5. Enter the code and sign in (or create a free Xbox account)
6. Back on the Switch, Minecraft will show your Gamertag once linked

#### Step 3: Join the Family Server

1. Press **Play** from the main menu
2. Go to the **Servers** tab at the top
3. Select **any Featured Server** from the list (The Hive, CubeCraft, etc.)
4. The **BedrockConnect menu** will appear instead of the Featured Server
5. Select **"Family Server"**
6. You'll connect and spawn into the family world

---

### Joining Each Other (Cross-Play)

Once everyone is connected to the Family Server:
- All players share the same world regardless of which console they're on
- PS4, PS5, and Switch players can all see each other, build together, mine, and explore
- Player progress, builds, and inventory are saved on the server and persist between sessions
- If someone disconnects, they'll respawn where they left off next time they join

---

## Tips for Parents

### Xbox / Microsoft Account Privacy Settings

If any player is a **child account** (under 13), you may need to adjust privacy settings for multiplayer to work:

1. Go to [family.microsoft.com](https://family.microsoft.com)
2. Sign in with the **parent's** Microsoft account
3. Select the child's account
4. Under **Xbox Series X|S, Xbox One, and Windows 10 devices → Privacy & online safety**
5. Make sure these are set to **Allow**:
   - "You can join multiplayer games"
   - "You can communicate outside of Xbox with voice & text"
   - "Others can communicate with voice, text, or invites"

### Keeping the Server Running

The Minecraft server runs in Docker with `restart: unless-stopped`, so it will:
- Survive Mac restarts (as long as Docker Desktop is set to start on login)
- Auto-recover from crashes
- Keep all world data safe in `server-data/`

You only need to re-run `./start-server.sh` if you manually stopped it with `./stop-server.sh`.

---

## Project Structure

```
Minecraft/
├── docker-compose.yml          # Bedrock server Docker config (port 19133)
├── start-server.sh             # Starts Bedrock server + BedrockConnect
├── stop-server.sh              # Stops the Bedrock server
├── start-dashboard.sh          # Starts the web dashboard
├── server-data/                # Minecraft world data (auto-created)
├── bedrockconnect/             # BedrockConnect JAR + config (auto-created)
│   ├── BedrockConnect-1.0-SNAPSHOT.jar
│   └── custom_servers.json
├── dashboard/
│   ├── app.py                  # Flask backend (API + server)
│   ├── requirements.txt        # Python dependencies
│   ├── history.json            # Player analytics data (auto-created)
│   ├── templates/
│   │   └── index.html          # Dashboard HTML
│   └── static/
│       ├── style.css           # Minecraft-themed styles
│       └── app.js              # Real-time dashboard logic
└── README.md                   # You're reading it
```

---

## Dashboard API

The dashboard exposes a REST API on port 8080:

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Server status (online, players, version, latency) |
| `/api/players` | GET | Connected players + recent join/leave events |
| `/api/stats` | GET | Docker container stats (CPU, RAM, network) |
| `/api/history` | GET | Player count history (24h) |
| `/api/logs?lines=50` | GET | Recent server console output |
| `/api/server/start` | POST | Start the Bedrock server |
| `/api/server/stop` | POST | Stop the Bedrock server |
| `/api/server/restart` | POST | Restart the Bedrock server |
| `/api/command` | POST | Send a command to the server console |

---

## Configuration

### Server Settings

Edit `docker-compose.yml` to customize:

```yaml
environment:
  SERVER_NAME: "Family Server"     # Server name
  GAMEMODE: survival               # survival, creative, adventure
  DIFFICULTY: normal               # peaceful, easy, normal, hard
  MAX_PLAYERS: 10                  # Max concurrent players
  ALLOW_CHEATS: "false"            # Enable /give, /tp, etc.
  VIEW_DISTANCE: 16                # Render distance (chunks)
  LEVEL_NAME: "FamilyWorld"        # World folder name
```

After changing settings, restart the server:

```bash
./stop-server.sh && ./start-server.sh
```

### Port Reference

| Port | Protocol | Used By | Purpose |
|---|---|---|---|
| 19132 | UDP | BedrockConnect | Console proxy + server list UI |
| 19133 | UDP | Bedrock Server | The actual Minecraft server |
| 53 | UDP/TCP | BedrockConnect | DNS server (intercepts console lookups) |
| 8080 | TCP | Dashboard | Web dashboard UI and API |

### Dashboard Settings

Edit `dashboard/app.py` constants:

```python
SERVER_HOST = "localhost"   # Bedrock server host
SERVER_PORT = 19133         # Bedrock server port
```

The dashboard polls every 30 seconds for analytics and every 5 seconds for the UI.

---

## Troubleshooting

### Console says "Unable to connect to world"
- Verify DNS is set correctly on the console (Primary: `<YOUR_MAC_IP>`)
- Make sure `start-server.sh` is running in a terminal (both Bedrock server AND BedrockConnect)
- Check that the Mac's firewall allows ports 53, 19132, and 19133
- On Mac: **System Settings → Network → Firewall** — either turn it off or add exceptions

### BedrockConnect menu doesn't appear (goes to actual Featured Server)
- The DNS redirect isn't working — double-check the console's Primary DNS is `<YOUR_MAC_IP>`
- Port 53 might be in use — check with: `sudo lsof -i :53`
- On macOS, the built-in mDNSResponder may conflict — try: `sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist` (re-enable later by changing `unload` to `load`)
- Restart the console's internet connection after changing DNS

### "Sign in with Microsoft Account" doesn't appear
- Make sure Minecraft is updated to the latest version
- On PS4/PS5: you may need to sign out and back into PSN first
- On Switch: try closing and reopening Minecraft completely (press X on the home screen to close)

### Players can't see each other in the world
- All players must be signed into **different** Microsoft / Xbox accounts
- Make sure **Multiplayer** is enabled in the world settings on the server
- For child accounts, check Xbox privacy settings (see Tips for Parents above)

### Dashboard shows "OFFLINE"
- The Bedrock server takes ~30 seconds to fully start up after `./start-server.sh`
- Check Docker is running: `docker ps` (look for `minecraft-bedrock`)
- Check server logs: `docker logs minecraft-bedrock`

### Mac IP address changed
- Find the new IP: `ipconfig getifaddr en0`
- Update DNS settings on each console to the new IP
- Restart `./start-server.sh` so BedrockConnect uses the new IP
- **Tip:** Set a static IP or DHCP reservation on your router to prevent this

### Server console shows "error binding to port"
- This means two services are fighting over the same port
- The Bedrock server runs on **19133** and BedrockConnect runs on **19132** — they must be different
- If you changed ports, make sure `docker-compose.yml`, `start-server.sh`, and `dashboard/app.py` all match

---

## Stopping Everything

```bash
# Stop the Bedrock server
./stop-server.sh

# Stop the dashboard — press Ctrl+C in its terminal

# Stop BedrockConnect — press Ctrl+C in the start-server.sh terminal
```

---

## Tech Stack

- **Minecraft Bedrock Dedicated Server** via [itzg/minecraft-bedrock-server](https://github.com/itzg/docker-minecraft-bedrock-server) Docker image
- **BedrockConnect** by [Pugmatt](https://github.com/Pugmatt/BedrockConnect) — console DNS bridge
- **Flask** — Python web framework for the dashboard backend
- **mcstatus** — Bedrock server status queries
- **Docker SDK for Python** — container stats and management
- **Chart.js** — player history graphs
- **Press Start 2P / VT323** — pixel and terminal fonts for the Minecraft theme

---

## License

Personal/family use. Built with love for family game nights.
