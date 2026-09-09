#!/bin/bash
# Ghost Browser Extension Installer
# Opens a visual guide in Chrome and starts the bridge server.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$SCRIPT_DIR/extension"
BRIDGE="$SCRIPT_DIR/bridge_server.py"
GUIDE="$EXT_DIR/install-guide.html"
VENV_DIR="$SCRIPT_DIR/.venv"
PID_FILE="$SCRIPT_DIR/logs/ghost_extension_bridge.pid"
LOG_FILE="$SCRIPT_DIR/logs/ghost_extension_bridge.log"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}🔌 Ghost Browser Extension Installer${NC}"
echo ""

# Step 0: Create/use Ghost's isolated Python environment and install dependencies
echo -e "${CYAN}Checking dependencies...${NC}"
if [ ! -x "$VENV_DIR/bin/python" ] && [ ! -x "$VENV_DIR/Scripts/python.exe" ]; then
    python3 -m venv "$VENV_DIR"
fi
if [ -x "$VENV_DIR/bin/python" ]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    PYTHON_BIN="$VENV_DIR/Scripts/python.exe"
fi
"$PYTHON_BIN" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Dependencies ready in $VENV_DIR${NC}"

# Copy extension path to clipboard
echo "$EXT_DIR" | pbcopy 2>/dev/null && echo -e "${GREEN}✓ Extension path copied to clipboard${NC}" || true

# Step 1: Start bridge server
echo -e "${CYAN}Starting bridge server...${NC}"
mkdir -p "$SCRIPT_DIR/logs"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(tr -cd '0-9' < "$PID_FILE")
    if [ -n "$OLD_PID" ] && ps -p "$OLD_PID" -o command= 2>/dev/null | grep -Fq "$BRIDGE"; then
        kill "$OLD_PID"
        sleep 0.5
    fi
fi
cd "$SCRIPT_DIR"
nohup "$PYTHON_BIN" "$BRIDGE" >> "$LOG_FILE" 2>&1 &
BRIDGE_PID=$!
echo "$BRIDGE_PID" > "$PID_FILE"
sleep 1
echo -e "${GREEN}✓ Bridge server running (PID ${BRIDGE_PID})${NC}"

# Step 2: Open the visual install guide
echo -e "${CYAN}Opening install guide in Chrome...${NC}"
GUIDE_URL="file://${GUIDE}?path=$("$PYTHON_BIN" -c "import urllib.parse; print(urllib.parse.quote('${EXT_DIR}'))")"
open "$GUIDE_URL" 2>/dev/null || xdg-open "$GUIDE_URL" 2>/dev/null || echo -e "Open this in Chrome: ${GUIDE_URL}"

echo ""
echo -e "${BOLD}Follow the steps in the browser tab that just opened.${NC}"
echo -e "The page will show ${GREEN}✅ Ghost Bridge is live!${NC} when everything is connected."
echo ""
echo -e "${CYAN}Waiting for connection...${NC}"

# Step 3: Poll until connected
for i in $(seq 1 60); do
    STATUS=$(curl -s http://127.0.0.1:9378/status 2>/dev/null || echo '{}')
    if echo "$STATUS" | "$PYTHON_BIN" -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('connected') else 1)" 2>/dev/null; then
        echo ""
        echo -e "${GREEN}${BOLD}✅ Ghost Browser Extension is live!${NC}"
        echo ""
        echo -e "  Endpoint: ${CYAN}http://127.0.0.1:9378${NC}"
        echo -e "  Try it:   ${CYAN}curl -s http://127.0.0.1:9378/status${NC}"
        echo ""
        exit 0
    fi
    sleep 2
done

echo ""
echo -e "${YELLOW}Timed out waiting for connection.${NC}"
echo -e "Follow the steps in the guide tab, then verify with:"
echo -e "  ${CYAN}curl -s http://127.0.0.1:9378/status${NC}"
echo ""
