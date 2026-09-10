---
name: ghost
description: Ghost Browser — browser automation via the Chrome extension bridge.
---

# Ghost

Browser automation through a Chrome extension that uses native Chrome APIs.

## Setup

1. Install the extension: `chrome://extensions/` → Developer Mode → Load unpacked → select `extension/`
2. Click the Ghost Bridge icon → "Connect"
3. Run `./install-extension.sh` from the Ghost repository (or start `python3 bridge_server.py`)
4. Verify: `curl -s http://127.0.0.1:9378/status`

## Architecture
```text
Agent
  ↓ HTTP POST to localhost:9378
Bridge Server (bridge_server.py)
  ↓ WebSocket
Chrome Extension (extension/)    ← native chrome.tabs / chrome.scripting APIs
  ↓
Browser tabs / pages
```

## Commands

### Connection
```bash
curl -s http://127.0.0.1:9378/status
```

### Navigation
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_navigate","args":{"url":"https://example.com"}}'
```

### Read page content
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"max_chars":4000}}'

# With CSS selector
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"selector":"article","max_chars":4000}}'
```

### Vacuum (numbered interactive elements)
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_vacuum","args":{"url":"https://example.com","limit":30}}'
```

### Read a PDF
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_pdf_read","args":{"page_start":1,"page_end":3,"mode":"auto"}}'
```

`auto` uses embedded text and applies OCR only to pages without text. PDF fetching
stays in the signed-in Chrome session; bytes are transferred through a bounded,
one-time loopback upload. HTTP(S) PDF tabs are supported.

### Click
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_click","args":{"choice":5}}'
```

### Screenshot
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_screenshot"}'
```

### Scroll
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_scroll","args":{"direction":"down","amount":500}}'
```

### Keyboard
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"key":"Enter"}}'

curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"text":"search query"}}'
```

### Tabs
```bash
# List
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_list"}'

# Open
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_open","args":{"url":"https://example.com"}}'

# Switch
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_switch","args":{"tab_index":3}}'
```

### Eval (pages without strict CSP only)
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_eval","args":{"script":"() => document.title"}}'
```

Sites with strict CSP may block eval. Use `ghost_read` with a `selector` instead.

## All available commands

| Command | What it does |
|---|---|
| `ghost_tab_list` | List open tabs |
| `ghost_tab_open` | Open a new tab |
| `ghost_tab_switch` | Switch to a tab by index |
| `ghost_navigate` | Navigate the active tab to a URL |
| `ghost_vacuum` | Read page and return numbered interactive elements |
| `ghost_click` | Click element by number from vacuum output |
| `ghost_read` | Read page text content, optionally filtered by CSS selector |
| `ghost_pdf_read` | Read page-indexed PDF text with OCR fallback |
| `ghost_screenshot` | Capture the visible page |
| `ghost_scroll` | Scroll the page (up/down/top/bottom) |
| `ghost_key` | Send keyboard input (key press or typed text) |
| `ghost_eval` | Run JS in the page context (CSP-permitting) |
| `ghost_save_auth` | Save current browser cookies to disk after manual login |

## Workflow

1. `curl -s http://127.0.0.1:9378/status` — verify bridge is connected
2. Vacuum the page to get numbered elements
3. Click, read, scroll, or type
4. Re-vacuum after any navigation (element numbers reset on every page state change)

## Rules
1. Always check `localhost:9378/status` before the first browser command.
2. Re-vacuum after navigation — element numbers are only valid for the current page.
3. Call `ghost_save_auth` immediately after manual login so auth persists.
4. Never attempt to type passwords.

## Error Codes

`ELEMENT_NOT_FOUND`, `NAVIGATION_TIMEOUT`, `NO_BROWSER`, `NO_VACUUM`, `INVALID_INPUT`, `BROWSER_DISCONNECTED`, `TAB_NOT_FOUND`, `CLICK_FAILED`, `FILL_REQUIRED`
