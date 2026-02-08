#!/bin/bash
# ===========================================
#  Minecraft Dashboard - Startup
# ===========================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/dashboard"

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv venv
    venv/bin/python -m ensurepip --upgrade 2>/dev/null || true
    venv/bin/python -m pip install -r requirements.txt
fi

echo ""
echo "============================================"
echo "  Minecraft Dashboard"
echo "============================================"
echo ""
echo "  Open in your browser:"
echo "    http://localhost:8080"
echo "    http://$LOCAL_IP:8080"
echo ""
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

venv/bin/python app.py
