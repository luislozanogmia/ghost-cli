# ghost-cli

Ghost Browser — AI browser automation via a Chrome extension and numbered accessibility menus.

<img width="607" height="453" alt="Screenshot at Jun 15 22-08-42" src="https://github.com/user-attachments/assets/f9481c3d-74a7-4049-ae13-20f83b72d59f" />

## Install

1. Install Python dependencies:
```bash
pip install -r requirements.txt
pip install websockets aiohttp
```

2. Load the Chrome extension:
   - Open `chrome://extensions/`
   - Enable **Developer Mode** (top right)
   - Click **Load unpacked** → select the `extension/` folder
   - Click the **Ghost Bridge** icon in the toolbar → **Connect**

3. Start the bridge server:
```bash
python extension/bridge_server.py &
```

4. Verify:
```bash
curl -s http://127.0.0.1:9378/status
# → {"connected": true, ...}
```

## How It Works

The Chrome extension uses native Chrome APIs (`chrome.tabs`, `chrome.scripting`) to control the browser. A local bridge server (`localhost:9378`) relays commands from agents to the extension over WebSocket.

```
Agent (curl / code)
  ↓ HTTP POST to localhost:9378
Bridge Server (extension/bridge_server.py)
  ↓ WebSocket
Chrome Extension (extension/)
  ↓ chrome.tabs / chrome.scripting
Browser tabs / pages
```

No remote debugging. No debugging dialogs. The user approves the extension once during install.

## Quick Start

```bash
# Check connection
curl -s http://127.0.0.1:9378/status

# Navigate somewhere
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_navigate","args":{"url":"https://news.ycombinator.com"}}'

# Get numbered interactive elements
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_vacuum","args":{"url":"https://news.ycombinator.com","limit":30}}'

# Click element #5
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_click","args":{"choice":5}}'

# Read page text
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"max_chars":4000}}'
```

## Commands

All commands are sent as HTTP POST to `http://127.0.0.1:9378/call` with `Content-Type: application/json`.

### Navigation

| Command | Purpose |
|---------|---------|
| `ghost_navigate` | Navigate the active tab to a URL |
| `ghost_vacuum` | Navigate + extract numbered interactive element menu |
| `ghost_click` | Click element by menu number |
| `ghost_scroll` | Scroll page (up/down/top/bottom) |

### Reading

| Command | Purpose |
|---------|---------|
| `ghost_read` | Extract clean readable text (optional CSS `selector`) |
| `ghost_eval` | Run JavaScript on the page (CSP-permitting) |
| `ghost_screenshot` | Capture the visible page |

### Tabs

| Command | Purpose |
|---------|---------|
| `ghost_tab_list` | List all open tabs |
| `ghost_tab_open` | Open a new tab |
| `ghost_tab_switch` | Switch active tab by index |

### Keyboard

| Command | Purpose |
|---------|---------|
| `ghost_key` | Send a key press (`"key":"Enter"`) or type text (`"text":"query"`) |

### Auth

| Command | Purpose |
|---------|---------|
| `ghost_save_auth` | Save browser cookies after manual login |

## Wait Strategies

`ghost_vacuum` and `ghost_click` accept a `wait` parameter:

| Strategy | Behavior | Best for |
|----------|----------|----------|
| `load` (default) | Wait for DOMContentLoaded + 2s settle | Most pages |
| `networkidle` | Wait until network is idle 500ms | SPAs, AJAX-heavy pages |
| `none` | No wait, immediate re-vacuum | Already-loaded content |

## Error Codes

All errors return: `Error [CODE]: message`

| Code | Meaning |
|------|---------|
| `ELEMENT_NOT_FOUND` | Menu number doesn't exist |
| `NAVIGATION_TIMEOUT` | Page load timed out |
| `NO_BROWSER` | Extension not connected |
| `NO_VACUUM` | Must vacuum before clicking |
| `INVALID_INPUT` | Missing or malformed argument |
| `BROWSER_DISCONNECTED` | Browser was closed |
| `TAB_NOT_FOUND` | Tab index out of range |
| `CLICK_FAILED` | Element could not be activated |
| `FILL_REQUIRED` | Input field needs a `value` argument |

## AI Agent Tips

- **Always re-vacuum after navigation.** Element numbers are only valid for the current page state.
- **Use `limit` to reduce noise.** Dense pages return 80+ elements. Set `"limit": 20` or `"limit": 30`.
- **`ghost_read` for content, `ghost_vacuum` for interaction.** If you just need text, use `ghost_read`.
- **Save auth after manual login.** Call `ghost_save_auth` right after the user logs in.
- **`ghost_eval` won't work on sites with strict CSP** (YouTube, Google). Use `ghost_read` with a `selector` instead.

## Extraction Recipes

Built-in recipes for `ghost_extract`:

- `linkedin_search` — profile list from LinkedIn search results
- `linkedin_profile` — formatted profile card
- `page_links` — link list from any page
- `page_meta` — title, description, OG tags

## LinkedIn

LinkedIn has a dedicated persistent profile and launcher:

```bash
./browser_context/linkedin/open_linkedin_ghost.sh open
./browser_context/linkedin/open_linkedin_ghost.sh vacuum
```

Manual re-login:
```bash
./browser_context/linkedin/open_linkedin_ghost.sh login
# User logs in manually
./browser_context/linkedin/open_linkedin_ghost.sh save
```

## Batch Extraction

```bash
./ghost-cli batch --queries queries.json --recipe linkedin_search --output results.json
```

## Known Limitations & Roadmap

| # | Issue | Status |
|---|-------|--------|
| 1 | Vacuum output lacks semantic filtering | Planned |
| 2 | No built-in rate limiting between requests | Planned |
| 3 | Error messages don't suggest recovery actions | Planned |
| 4 | No text search primitive | Planned |
| 5 | Screenshots return path only | Planned |
| 6 | No scroll-to-element by text/selector | Planned |

Contributions welcome. Open an issue to discuss before sending PRs.
