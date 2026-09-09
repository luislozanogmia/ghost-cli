# Ghost ↔ In-App Browser Protocol

## Overview

A local JSON-RPC-style protocol between Ghost CLI and In-App Browser's Electron
`WebContentsView` browser. No CDP. No Chrome debugging APIs. No second browser.

Ghost CLI sends commands. In-App Browser executes them against its existing
`browser.cjs` `WebContentsView` tabs and returns results.

## Transport

**Primary: Unix domain socket** (macOS/Linux)

- Path: `~/.in-app-browser/ghost-bridge.sock`
- Override: `GHOST_IN_APP_BROWSER_SOCKET` env var
- Security: filesystem permissions restrict access to the owning user

**Fallback: Authenticated loopback TCP** (Windows or explicit config)

- Address: `127.0.0.1:9400`
- Override: `GHOST_IN_APP_BROWSER_PORT` env var
- Security: loopback-only + auth token

### Why Unix socket over HTTP/WebSocket

| Property | Unix socket | HTTP loopback | WebSocket |
|---|---|---|---|
| Auth by filesystem perms | ✅ | ❌ | ❌ |
| No port conflicts | ✅ | ❌ | ❌ |
| No HTTP parsing overhead | ✅ | ❌ | ❌ |
| Works on Windows | ❌ | ✅ | ✅ |
| Persistent connection needed | No | No | Yes |

The protocol is transport-neutral — the same JSON messages work over either
channel. In-App Browser can implement whichever fits its runtime.

## Wire Format

Each message is a **4-byte big-endian length prefix** followed by a UTF-8
JSON payload. This avoids delimiter issues when page content contains
newlines.

```
[4 bytes: payload length (big-endian uint32)] [N bytes: UTF-8 JSON]
```

## Authentication

Every request includes a `token` field. In-App Browser validates it against a shared
secret stored at `~/.in-app-browser/ghost-bridge.token`. Ghost CLI reads the same
file at startup.

```json
{
  "jsonrpc": "2.0",
  "id": "a1b2c3d4e5f6",
  "method": "navigate",
  "params": {"url": "https://example.com"},
  "token": "shared-secret-from-token-file"
}
```

If the token is missing or wrong, In-App Browser returns:

```json
{
  "jsonrpc": "2.0",
  "id": "a1b2c3d4e5f6",
  "error": {"code": "AUTH_FAILED", "message": "Invalid or missing token"}
}
```

## Request Format

```json
{
  "jsonrpc": "2.0",
  "id": "<unique-request-id>",
  "method": "<command>",
  "params": { ... },
  "token": "<auth-token>"
}
```

- `id`: unique string per request (UUID hex prefix). **Required.**
- `method`: command name from the table below. **Required.**
- `params`: command-specific arguments. Optional (defaults to `{}`).
- `token`: auth token. **Required** when auth is enabled.

## Response Format

### Success

```json
{
  "jsonrpc": "2.0",
  "id": "<matching-request-id>",
  "result": { ... }
}
```

### Error

```json
{
  "jsonrpc": "2.0",
  "id": "<matching-request-id>",
  "error": {
    "code": "<ERROR_CODE>",
    "message": "Human-readable description"
  }
}
```

### Error Codes

| Code | Meaning |
|---|---|
| `AUTH_FAILED` | Token missing or invalid |
| `UNKNOWN_METHOD` | Command not recognized |
| `INVALID_PARAMS` | Missing or malformed parameters |
| `TAB_NOT_FOUND` | Tab ID does not exist |
| `ELEMENT_NOT_FOUND` | Selector or choice index not found |
| `NAVIGATION_FAILED` | URL failed to load |
| `TIMEOUT` | Command exceeded time limit |
| `BROWSER_ERROR` | WebContentsView internal error |
| `RESPONSE_TOO_LARGE` | Result exceeds 16 MB |

## Commands

### `status`

Check browser state.

**Params:** none

**Result:**
```json
{
  "connected": true,
  "tabs": 3,
  "active_tab_id": 42,
  "active_url": "https://example.com",
  "active_title": "Example Domain"
}
```

---

### `navigate`

Navigate the active tab (or a specific tab) to a URL.

**Params:**
```json
{
  "url": "https://example.com",
  "tab_id": 42
}
```
`tab_id` is optional; defaults to active tab.

**Result:**
```json
{
  "tab_id": 42,
  "url": "https://example.com/",
  "title": "Example Domain",
  "loading": false
}
```

**In-App Browser mapping:** `{action: "navigate", value: url}`

---

### `read`

Read visible text content from the active tab.

**Params:**
```json
{
  "max_chars": 4000,
  "selector": "article"
}
```
Both optional. `max_chars` capped at 100,000.

**Result:**
```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "text": "Example Domain\nThis domain is...\n[0] link: More info (https://...)",
  "text_length": 142,
  "text_truncated": false
}
```

**In-App Browser mapping:** `executeJavaScript` on the active tab's `webContents`

---

### `vacuum`

Navigate to a URL and return numbered interactive elements (links, buttons,
inputs) for click-based navigation.

**Params:**
```json
{
  "url": "https://example.com",
  "limit": 30,
  "selector": "main"
}
```
`url` required. `limit` defaults to 30.

**Result:**
```json
{
  "tab_id": 42,
  "url": "https://example.com/",
  "title": "Example Domain",
  "text": "[0] link: More info (https://...)\n[1] button: Submit",
  "element_count": 2
}
```

**In-App Browser mapping:** `navigate` + `executeJavaScript` to enumerate elements

---

### `click`

Click a numbered element from a prior `vacuum`/`read` result, or a CSS
selector.

**Params:**
```json
{
  "choice": 5,
  "selector": "#submit-btn",
  "wait": "networkidle"
}
```
Provide `choice` OR `selector`. `wait` is optional.

**Result:**
```json
{
  "clicked": true,
  "tag": "a",
  "text": "More information..."
}
```

**In-App Browser mapping:** `executeJavaScript` to find element and dispatch click

---

### `fill`

Fill an input field.

**Params:**
```json
{
  "value": "hello world",
  "choice": 3,
  "selector": "input[name=q]"
}
```
`value` required. Provide `choice` OR `selector`.

**Result:**
```json
{
  "filled": true,
  "tag": "input",
  "value": "hello world"
}
```

---

### `key`

Press a key or type text.

**Params:**
```json
{
  "key": "Enter"
}
```
OR:
```json
{
  "text": "search query"
}
```

**Result:**
```json
{
  "key": "Enter",
  "pressed": true
}
```

---

### `tab_list`

List all open browser tabs.

**Params:** none

**Result:**
```json
{
  "tabs": [
    {"id": 1, "url": "https://example.com", "title": "Example", "active": true},
    {"id": 2, "url": "about:blank", "title": "New tab", "active": false}
  ]
}
```

**In-App Browser mapping:** `{action: "state"}` → map tab entries

---

### `tab_open`

Open a new tab.

**Params:**
```json
{
  "url": "https://example.com"
}
```

**Result:**
```json
{
  "tab_id": 3,
  "url": "https://example.com",
  "title": "Example Domain"
}
```

**In-App Browser mapping:** `{action: "new"}` + `{action: "navigate", value: url}`

---

### `tab_switch`

Switch to a tab by ID.

**Params:**
```json
{
  "tab_id": 2
}
```

**Result:**
```json
{
  "tab_id": 2,
  "url": "https://example.com",
  "title": "Example Domain"
}
```

**In-App Browser mapping:** `{action: "select", id: tab_id}`

---

### `tab_close`

Close a tab by ID.

**Params:**
```json
{
  "tab_id": 2
}
```

**Result:**
```json
{
  "closed": true
}
```

**In-App Browser mapping:** `{action: "close", id: tab_id}`

---

### `back`

Navigate back in the active tab's history.

**In-App Browser mapping:** `{action: "back"}`

---

### `forward`

Navigate forward in the active tab's history.

**In-App Browser mapping:** `{action: "forward"}`

---

### `reload`

Reload the active tab.

**In-App Browser mapping:** `{action: "reload"}`

---

### `stop`

Stop loading the active tab.

**In-App Browser mapping:** `{action: "stop"}`

---

### `screenshot`

Capture the visible area of the active tab.

**Params:**
```json
{
  "format": "png",
  "quality": 80
}
```

**Result:**
```json
{
  "data_url": "data:image/png;base64,...",
  "width": 1280,
  "height": 720
}
```

**Note:** `data_url` is bounded to 16 MB.

---

### `scroll`

Scroll the active tab.

**Params:**
```json
{
  "direction": "down",
  "amount": 500
}
```
`direction`: `"up"`, `"down"`, `"top"`, `"bottom"`.

---

### `wait`

Wait for an element or a fixed time.

**Params:**
```json
{
  "selector": "#loaded",
  "timeout": 10000
}
```
OR:
```json
{
  "ms": 2000
}
```

## Bounds and Limits

| Resource | Limit |
|---|---|
| Max response size | 16 MB |
| Max page text | 100,000 chars |
| Max screenshot data URL | 16 MB |
| Request timeout default | 30 s |
| Request timeout max | 120 s |

## In-App Browser Implementation Checklist

In-App Browser needs to add a server endpoint that:

1. Listens on `~/.in-app-browser/ghost-bridge.sock` (Unix socket)
2. Reads the shared token from `~/.in-app-browser/ghost-bridge.token`
3. Parses length-prefixed JSON requests
4. Validates `token` and `id` fields
5. Routes `method` to the existing `browser.cjs` IPC actions
6. Returns length-prefixed JSON responses with matching `id`
7. Adds `read` and `vacuum` commands via `executeJavaScript` on `webContents`
8. Adds `screenshot` via `webContents.capturePage()`

The protocol is deliberately aligned with In-App Browser's existing `browser.cjs`
IPC channel (`in-app-browser-command`) so the server is a thin translation
layer, not a new browser engine.

## Status

- ✅ Ghost CLI `InAppBrowserTransport` client: implemented
- ✅ Protocol specification: this document
- ✅ Mock server + tests: `tests/test_in_app_browser_transport.py`
- ⬜ In-App Browser server endpoint: not yet implemented
- ⬜ Ghost CLI runtime registration: ready when In-App Browser endpoint exists
