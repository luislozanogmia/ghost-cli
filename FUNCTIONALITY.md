# Ghost CLI — Full Command Reference

All browser commands go through the Chrome extension bridge at `http://127.0.0.1:9378`.

## Bridge API

### Check connection
```bash
curl -s http://127.0.0.1:9378/status
```

### Send a command
```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"<command_name>","args":{...}}'
```

## Command Reference

### ghost_navigate

Navigate the active tab to a URL.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_navigate","args":{"url":"https://example.com"}}'
```

| Param | Type | Description |
|-------|------|-------------|
| `url` | string | **required** — URL to navigate to |

### ghost_vacuum

Navigate and extract numbered interactive elements.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_vacuum","args":{"url":"https://example.com","limit":30}}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | — | Navigate before vacuuming |
| `limit` | int | 50 | Max elements to return |
| `wait` | enum | `load` | `load`, `networkidle`, `none` |

### ghost_click

Click a numbered element from the last vacuum.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_click","args":{"choice":5}}'
```

| Param | Type | Description |
|-------|------|-------------|
| `choice` | int | **required** — element number |
| `value` | string | Text for input/search fields |
| `wait` | enum | Wait strategy after click |

### ghost_read

Extract clean readable text from the page.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_read","args":{"max_chars":4000,"selector":"article"}}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `max_chars` | int | 8000 | Truncate output |
| `selector` | string | — | CSS selector to scope reading |

### ghost_scroll

Scroll the page.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_scroll","args":{"direction":"down","amount":500}}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `direction` | enum | `down` | `down`, `up`, `bottom`, `top` |
| `amount` | int | 500 | Pixels to scroll |

### ghost_screenshot

Capture the visible page.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_screenshot"}'
```

### ghost_key

Send keyboard input.

```bash
# Key press
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"key":"Enter"}}'

# Type text
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_key","args":{"text":"search query"}}'
```

| Param | Type | Description |
|-------|------|-------------|
| `key` | string | Key name (`Enter`, `Escape`, `Tab`, etc.) |
| `text` | string | Text to type character by character |

### ghost_eval

Run JavaScript on the current page. Only works on sites without strict CSP.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_eval","args":{"script":"() => document.title"}}'
```

| Param | Type | Description |
|-------|------|-------------|
| `script` | string | **required** — JS arrow function |

### ghost_tab_list

List all open tabs.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_list"}'
```

### ghost_tab_open

Open a new tab.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_open","args":{"url":"https://example.com"}}'
```

### ghost_tab_switch

Switch active tab by index.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_tab_switch","args":{"tab_index":0}}'
```

### ghost_save_auth

Save browser cookies to persist sessions.

```bash
curl -s -X POST http://127.0.0.1:9378/call \
  -H 'Content-Type: application/json' \
  -d '{"command":"ghost_save_auth"}'
```

## Error Codes

All errors: `Error [CODE]: message`

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
| `FILL_REQUIRED` | Input field needs a `value` |
