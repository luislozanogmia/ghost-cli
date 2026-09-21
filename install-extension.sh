#!/bin/bash
# Ghost Browser Extension Installer
# Opens a visual guide in Chrome and starts the bridge server.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$SCRIPT_DIR/extension"
BRIDGE="$SCRIPT_DIR/bridge_server.py"
GUIDE="$EXT_DIR/install-guide.html"
PID_FILE="$SCRIPT_DIR/logs/ghost_extension_bridge.pid"
LOG_FILE="$SCRIPT_DIR/logs/ghost_extension_bridge.log"
PYTHON_BIN="${GHOST_PYTHON:-python3}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}🔌 Ghost Browser Extension Installer${NC}"
echo ""

# Step 0: Install dependencies for the selected Python interpreter
echo -e "${CYAN}Checking dependencies...${NC}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python interpreter not found: $PYTHON_BIN" >&2
    exit 1
}
PIP_SCOPE=()
if "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.prefix != sys.base_prefix)' 2>/dev/null; then
    PIP_SCOPE=(--user)
fi
"$PYTHON_BIN" -m pip install "${PIP_SCOPE[@]}" --quiet -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Dependencies ready${NC}"

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
PAIRING_TOKEN=$("$PYTHON_BIN" "$SCRIPT_DIR/ghost_cli.py" bridge-token)

# Step 2: Open the visual install guide
echo -e "${CYAN}Opening install guide in Chrome...${NC}"
GUIDE_URL="file://${GUIDE}?path=$("$PYTHON_BIN" -c "import urllib.parse; print(urllib.parse.quote('${EXT_DIR}'))")"
open "$GUIDE_URL" 2>/dev/null || xdg-open "$GUIDE_URL" 2>/dev/null || echo -e "Open this in Chrome: ${GUIDE_URL}"

echo ""
echo -e "${BOLD}Follow the steps in the browser tab that just opened.${NC}"
echo -e "Paste this pairing token into the extension popup:"
echo -e "${CYAN}${PAIRING_TOKEN}${NC}"
echo ""
echo -e "${CYAN}Waiting for connection...${NC}"

# Step 3: Poll until connected
for i in $(seq 1 60); do
    STATUS=$("$PYTHON_BIN" "$SCRIPT_DIR/ghost_cli.py" status --backend chrome 2>/dev/null || echo '{}')
    if echo "$STATUS" | "$PYTHON_BIN" -c "import sys,json; data=json.load(sys.stdin); sys.exit(0 if data.get('result', {}).get('connected') else 1)" 2>/dev/null; then
        echo ""
        echo -e "${GREEN}${BOLD}✅ Ghost Browser Extension is live!${NC}"
        echo ""
        echo -e "  Endpoint: ${CYAN}http://127.0.0.1:9378${NC}"
        echo -e "  Try it:   ${CYAN}./ghost-cli status --backend chrome${NC}"
        echo ""
        exit 0
    fi
    sleep 2
done

echo ""
echo -e "${YELLOW}Timed out waiting for connection.${NC}"
echo -e "Follow the steps in the guide tab, then verify with:"
echo -e "  ${CYAN}./ghost-cli status --backend chrome${NC}"
echo ""
