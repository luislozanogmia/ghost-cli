# Ghost ↔ Hermes Desktop browser protocol

Ghost controls the browser pane already owned by Hermes Desktop through a
local, authenticated request/response channel.

## Transport and framing

- Unix socket at `$GHOST_IN_APP_BROWSER_SOCKET`, otherwise
  `$XDG_RUNTIME_DIR/ghost/in-app-browser.sock`.
- Every frame is a four-byte big-endian length followed by UTF-8 JSON.
- Requests and responses are capped at 16 MiB.

The Unix socket and its parent directory must be private to the current user.
Ghost does not fall back to a network listener when the socket is absent.

## Authentication

Every request contains the token from `GHOST_IN_APP_BROWSER_TOKEN` or the
private file selected by `GHOST_IN_APP_BROWSER_TOKEN_FILE`. The default token
file is next to the socket. Tokens must contain at least 32 bytes. The host
compares tokens in constant time and
returns `AUTH_FAILED` without running the requested action when authentication
fails.

## Request

```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "method": "navigate",
  "params": {"url": "https://example.com"},
  "token": "private-local-token"
}
```

## Response

```json
{"jsonrpc":"2.0","id":"unique-request-id","result":{"url":"https://example.com"}}
```

Errors use an `error` object with `code` and `message`. The response `id` must
match the request `id`.

## Methods

| Method | Purpose | Important parameters |
|---|---|---|
| `status` | Browser and active-tab status | none |
| `tab_list` | List tabs | none |
| `tab_open` | Open a tab | `url` |
| `tab_switch` | Activate a tab | `tab_id` or `tab_index` |
| `tab_close` | Close a tab | `tab_id` or `tab_index` |
| `navigate` | Navigate a tab | `url`, optional `tab_id` |
| `vacuum` | Navigate and enumerate interactive elements | `url`, optional `limit`, `selector` |
| `read` | Read bounded page text | optional `max_chars`, `selector` |
| `click` | Click an enumerated element or selector | `choice` or `selector` |
| `fill` | Fill an input | `value`, plus `choice` or `selector` |
| `key` | Press a key or type text | `key` or `text` |
| `eval` | Run a supplied JavaScript function in the page | `script` |
| `screenshot` | Capture the visible page | optional `format`, `quality` |
| `scroll` | Scroll the page | `direction`, optional `amount` |
| `wait` | Wait for a selector or delay | `selector` or `ms`, optional `timeout` |

The host must not include current input or textarea values in `read`/`vacuum`
results, and `fill`/`key` results must acknowledge the action without echoing
the supplied value or text. Ghost clients additionally strip common echo fields
for compatibility with older hosts.

For `eval`, the host executes only after authenticating the request and returns
a JSON-serializable value. Page content and script results are untrusted and
must remain within the response cap.
