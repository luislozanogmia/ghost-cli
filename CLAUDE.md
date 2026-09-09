# Ghost CLI

## Setup

Install the Chrome extension:

1. Open `chrome://extensions/`
2. Enable Developer Mode
3. Click "Load unpacked" → select the `extension/` folder
4. Click the Ghost Bridge icon in the toolbar → "Connect"

Install dependencies and start the bridge server:
```bash
./install-extension.sh
```

## Using the Browser

All browser commands go through the extension bridge at `localhost:9378`.

### Check connection
```bash
curl -s http://127.0.0.1:9378/status
```

### Commands
```bash
# List tabs
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_list"}'

# Navigate
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_navigate","args":{"url":"https://example.com"}}'

# Read page content
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"max_chars":4000}}'

# Read with CSS selector
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"selector":"article","max_chars":4000}}'

# Read the PDF open in the active Chrome tab
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_pdf_read","args":{"page_start":1,"page_end":3,"mode":"auto"}}'

# Vacuum (numbered interactive elements)
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_vacuum","args":{"url":"https://example.com","limit":30}}'

# Click by choice number
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_click","args":{"choice":5}}'

# Screenshot
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_screenshot"}'

# Scroll
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_scroll","args":{"direction":"down","amount":500}}'

# Keyboard input
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"key":"Enter"}}'

curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"text":"search query"}}'

# Tab management
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_open","args":{"url":"https://example.com"}}'

curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_switch","args":{"tab_index":3}}'
```

## Workflow

1. Check connection: `curl -s http://127.0.0.1:9378/status`
2. Vacuum the page to get numbered elements
3. Click, read, or interact
4. Re-vacuum after any navigation (element numbers reset)

## Error Codes

`ELEMENT_NOT_FOUND`, `NAVIGATION_TIMEOUT`, `NO_BROWSER`, `NO_VACUUM`, `INVALID_INPUT`, `BROWSER_DISCONNECTED`, `TAB_NOT_FOUND`, `CLICK_FAILED`, `FILL_REQUIRED`
