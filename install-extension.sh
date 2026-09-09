#!/bin/bash
# Ghost Browser Extension Installer
# Opens a visual guide in Chrome and starts the bridge server.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$SCRIPT_DIR/extension"
BRIDGE="$EXT_DIR/bridge_server.py"
GUIDE="$EXT_DIR/install-guide.html"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}🔌 Ghost Browser Extension Installer${NC}"
echo ""

# Step 0: Check dependencies
echo -e "${CYAN}Checking dependencies...${NC}"
missing=""
python3 -c "import websockets" 2>/dev/null || missing="websockets"
python3 -c "import aiohttp" 2>/dev/null || { [ -n "$missing" ] && missing="$missing "; missing="${missing}aiohttp"; }

if [ -n "$missing" ]; then
    echo -e "${YELLOW}Installing: ${missing}${NC}"
    pip install $missing --quiet
    echo -e "${GREEN}✓ Dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Dependencies ready${NC}"
fi

# Copy extension path to clipboard
echo "$EXT_DIR" | pbcopy 2>/dev/null && echo -e "${GREEN}✓ Extension path copied to clipboard${NC}" || true

# Step 1: Start bridge server
echo -e "${CYAN}Starting bridge server...${NC}"
pkill -f "bridge_server.py" 2>/dev/null || true
sleep 0.5
cd "$SCRIPT_DIR"
python3 "$BRIDGE" &
BRIDGE_PID=$!
sleep 1
echo -e "${GREEN}✓ Bridge server running (PID ${BRIDGE_PID})${NC}"

# Step 2: Open the visual install guide
echo -e "${CYAN}Opening install guide in Chrome...${NC}"
GUIDE_URL="file://${GUIDE}?path=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${EXT_DIR}'))")"
open "$GUIDE_URL" 2>/dev/null || xdg-open "$GUIDE_URL" 2>/dev/null || echo -e "Open this in Chrome: ${GUIDE_URL}"

echo ""
echo -e "${BOLD}Follow the steps in the browser tab that just opened.${NC}"
echo -e "The page will show ${GREEN}✅ Ghost Bridge is live!${NC} when everything is connected."
echo ""
echo -e "${CYAN}Waiting for connection...${NC}"

# Step 3: Poll until connected
for i in $(seq 1 60); do
    STATUS=$(curl -s http://127.0.0.1:9378/status 2>/dev/null || echo '{}')
    if echo "$STATUS" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('connected') else 1)" 2>/dev/null; then
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
