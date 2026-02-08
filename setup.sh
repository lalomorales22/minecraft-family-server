#!/bin/bash
# ===========================================
#  Minecraft Family Server - One-Time Setup
#  Run this on any Mac to get everything ready
# ===========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Minecraft Family Server - Setup${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

ERRORS=0

# ------------------------------------------
# 1. Check / Install Homebrew
# ------------------------------------------
echo -e "${CYAN}[1/6]${NC} Checking Homebrew..."
if command -v brew &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Homebrew is installed"
else
    echo -e "  ${YELLOW}→${NC} Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to path for Apple Silicon Macs
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    echo -e "  ${GREEN}✓${NC} Homebrew installed"
fi

# ------------------------------------------
# 2. Check / Install Docker
# ------------------------------------------
echo -e "${CYAN}[2/6]${NC} Checking Docker..."
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    echo -e "  ${GREEN}✓${NC} Docker is installed (${DOCKER_VER}) and running"
else
    if command -v docker &>/dev/null; then
        echo -e "  ${RED}✗${NC} Docker is installed but not running"
        echo -e "  ${YELLOW}→${NC} Opening Docker Desktop... (wait for it to start, then re-run this script)"
        open -a "Docker Desktop" 2>/dev/null || open -a Docker 2>/dev/null || true
        echo ""
        echo -e "  ${YELLOW}Docker Desktop needs to be running before setup can continue.${NC}"
        echo -e "  ${YELLOW}Once you see the Docker whale icon in your menu bar, run this script again:${NC}"
        echo ""
        echo -e "    ${BOLD}./setup.sh${NC}"
        echo ""
        exit 1
    else
        echo -e "  ${YELLOW}→${NC} Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        echo -e "  ${YELLOW}→${NC} Opening Docker Desktop..."
        open -a "Docker Desktop" 2>/dev/null || open -a Docker 2>/dev/null || true
        echo ""
        echo -e "  ${YELLOW}Docker Desktop is installing and starting for the first time.${NC}"
        echo -e "  ${YELLOW}Wait for the whale icon in your menu bar, then run this script again:${NC}"
        echo ""
        echo -e "    ${BOLD}./setup.sh${NC}"
        echo ""
        exit 1
    fi
fi

# ------------------------------------------
# 3. Check / Install Java
# ------------------------------------------
echo -e "${CYAN}[3/6]${NC} Checking Java..."
if command -v java &>/dev/null; then
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo -e "  ${GREEN}✓${NC} Java is installed (${JAVA_VER})"
else
    echo -e "  ${YELLOW}→${NC} Installing Java via Homebrew..."
    brew install openjdk
    # Symlink so system can find it
    sudo ln -sfn "$(brew --prefix openjdk)/libexec/openjdk.jdk" /Library/Java/JavaVirtualMachines/openjdk.jdk 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Java installed"
fi

# ------------------------------------------
# 4. Check / Install Python 3 + venv
# ------------------------------------------
echo -e "${CYAN}[4/6]${NC} Checking Python..."
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version)
    echo -e "  ${GREEN}✓${NC} ${PY_VER}"
else
    echo -e "  ${YELLOW}→${NC} Installing Python via Homebrew..."
    brew install python
    echo -e "  ${GREEN}✓${NC} Python installed"
fi

echo -e "${CYAN}[5/6]${NC} Setting up dashboard Python environment..."
cd "$SCRIPT_DIR/dashboard"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "  ${GREEN}✓${NC} Virtual environment created"
else
    echo -e "  ${GREEN}✓${NC} Virtual environment already exists"
fi
venv/bin/python -m ensurepip --upgrade 2>/dev/null || true
venv/bin/python -m pip install -q -r requirements.txt
echo -e "  ${GREEN}✓${NC} Python dependencies installed"
cd "$SCRIPT_DIR"

# ------------------------------------------
# 5. Download BedrockConnect
# ------------------------------------------
echo -e "${CYAN}[6/6]${NC} Checking BedrockConnect..."
BCJAR="$SCRIPT_DIR/bedrockconnect/BedrockConnect-1.0-SNAPSHOT.jar"
if [ -f "$BCJAR" ]; then
    echo -e "  ${GREEN}✓${NC} BedrockConnect already downloaded"
else
    echo -e "  ${YELLOW}→${NC} Downloading BedrockConnect..."
    mkdir -p "$SCRIPT_DIR/bedrockconnect"
    curl -L -o "$BCJAR" \
        "https://github.com/Pugmatt/BedrockConnect/releases/latest/download/BedrockConnect-1.0-SNAPSHOT.jar"
    echo -e "  ${GREEN}✓${NC} BedrockConnect downloaded"
fi

# ------------------------------------------
# 6. Pull the Docker image
# ------------------------------------------
echo ""
echo -e "${CYAN}Pulling Minecraft Bedrock server image...${NC}"
docker pull itzg/minecraft-bedrock-server
echo -e "  ${GREEN}✓${NC} Docker image ready"

# ------------------------------------------
# Done — print summary
# ------------------------------------------
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "UNKNOWN")

echo ""
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  This Mac's IP: ${BOLD}${LOCAL_IP}${NC}"
echo ""
echo -e "  ${BOLD}To start the server:${NC}"
echo -e "    Terminal 1:  ${CYAN}./start-server.sh${NC}"
echo -e "    Terminal 2:  ${CYAN}./start-dashboard.sh${NC}"
echo ""
echo -e "  ${BOLD}Dashboard URL:${NC}"
echo -e "    ${CYAN}http://localhost:8080${NC}"
echo -e "    ${CYAN}http://${LOCAL_IP}:8080${NC}"
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Console DNS Settings${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  On each PS4 / PS5 / Switch, set DNS to:"
echo ""
echo -e "    Primary DNS:   ${BOLD}${LOCAL_IP}${NC}"
echo -e "    Secondary DNS: ${BOLD}8.8.8.8${NC}"
echo ""
echo -e "  Then open Minecraft → Servers tab → pick"
echo -e "  any Featured Server → select 'Family Server'"
echo ""
echo -e "${GREEN}============================================${NC}"
echo ""
