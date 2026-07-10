# Ghost CLI -- Full Command Reference

Primary interface: `./ghost-cli`

## CLI Subcommands

| Command | Usage | Notes |
|---------|-------|-------|
| `live-connect` | `./ghost-cli live-connect` | Canonical AI connection to the already-open Chrome through the shared Chrome MCP broker; rejects Playwright fallback |
| `list-tools` | `./ghost-cli list-tools` | Print all available Ghost tools as JSON |
| `call` | `./ghost-cli call <tool> --arguments '{...}'` | Invoke a tool via the persistent daemon |
| `repl` | `./ghost-cli repl` | Interactive JSON-line session |
| `daemon-status` | `./ghost-cli daemon-status` | Check persistent daemon health |
| `daemon-stop` | `./ghost-cli daemon-stop` | Shut down the daemon |
| `batch` | `./ghost-cli batch --queries <file> --recipe <name> --output <file>` | Multi-URL extraction |

### `call` flags

| Flag | Effect |
|------|--------|
| `--arguments '{"key":"val"}'` | JSON arguments for the tool |
| `--json-output` | Output as JSON envelope instead of raw text |
| `--ephemeral` | Run in-process (no daemon), discard state after |
| `--headless` | Inject `headless: true` into `ghost_instance_create` |

### live-connect

Use this whenever an AI needs Luis's already-open Chrome:

```bash
./ghost-cli live-connect
```

The command discovers and reuses the shared `chrome-devtools-mcp` broker, creates or reuses instance `live`, and succeeds only with `transport: "chrome-transport"`, `browser_connected: true`, and `playwright_used: false`. Use `--instance-id <name>` only when a different shared instance name is explicitly required.

## Tool Reference

### ghost_instance_create

Create or reuse a named browser instance.

```bash
./ghost-cli call ghost_instance_create --arguments '{
  "instance_id": "worker",
  "headless": true,
  "url": "https://example.com"
}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | auto-generated | Named instance identifier |
| `headless` | bool | `false` | Launch isolated headless Chromium (skips Chrome auto-attach) |
| `open_browser` | bool | `true` | Open browser on creation |
| `url` | string | -- | Navigate immediately after creation |
| `cdp_url` | string | -- | Attach to external browser (`"live-chrome"` for user's Chrome) |
| `playwright_session` | string | -- | Attach to managed Playwright session |
| `reuse_only` | bool | `false` | Fail if instance doesn't already exist |

### ghost_vacuum

Navigate and extract numbered interactive element menu.

```bash
./ghost-cli call ghost_vacuum --arguments '{"url":"https://example.com","limit":30,"wait":"networkidle"}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `url` | string | -- | Navigate before vacuuming |
| `limit` | int | 50 | Max elements per page |
| `wait` | enum | `load` | Wait strategy: `load`, `networkidle`, `none` |

### ghost_click

Execute a numbered action and auto re-vacuum.

```bash
./ghost-cli call ghost_click --arguments '{"choice":5,"value":"search query","wait":"networkidle"}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `choice` | int | **required** | Menu element number |
| `value` | string | -- | Text for input/search fields |
| `wait` | enum | `load` | Wait strategy after click |

### ghost_more

Paginate through cached vacuum results.

```bash
./ghost-cli call ghost_more --arguments '{"offset":50}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `offset` | int | auto | Start element offset |

### ghost_read

Extract clean readable text from the page (reader mode).

```bash
./ghost-cli call ghost_read --arguments '{"url":"https://example.com","max_chars":4000,"selector":"article"}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `url` | string | -- | Navigate before reading |
| `max_chars` | int | 8000 | Truncate output |
| `selector` | string | auto-detect | CSS selector to scope reading |

### ghost_scroll

Scroll page to load lazy content, then re-vacuum.

```bash
./ghost-cli call ghost_scroll --arguments '{"direction":"down","wait":2.0}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `direction` | enum | `down` | `down`, `up`, `bottom`, `top` |
| `pixels` | int | -- | Exact scroll amount (overrides direction) |
| `wait` | number | 2.0 | Seconds to wait for lazy content |

### ghost_tab_list

List all open tabs in a browser instance.

```bash
./ghost-cli call ghost_tab_list --arguments '{"instance_id":"demo"}'
```

### ghost_tab_open

Open a new tab.

```bash
./ghost-cli call ghost_tab_open --arguments '{"url":"https://example.com"}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `url` | string | -- | URL to open in the new tab |

### ghost_tab_switch

Switch active tab by index and auto-vacuum.

```bash
./ghost-cli call ghost_tab_switch --arguments '{"tab_index":0}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `tab_index` | int | **required** | Zero-based tab index |

### ghost_tab_close

Close a tab by index.

```bash
./ghost-cli call ghost_tab_close --arguments '{"tab_index":1}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `tab_index` | int | **required** | Zero-based tab index |

### ghost_screenshot

Capture page screenshot. Optionally scroll to element first.

```bash
./ghost-cli call ghost_screenshot --arguments '{"inline":true,"full_page":false}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `element` | int | -- | Scroll to menu element before capture |
| `full_page` | bool | `false` | Capture entire page vs viewport |
| `inline` | bool | `false` | Return base64 data instead of file path |

### ghost_eval

Run JavaScript on the current page.

```bash
./ghost-cli call ghost_eval --arguments '{"script":"() => document.title"}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `script` | string | **required** | JS arrow function to evaluate |

### ghost_extract

Structured extraction with built-in or custom recipes.

```bash
./ghost-cli call ghost_extract --arguments '{"recipe":"page_links","max_items":20}'
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instance_id` | string | default | Target instance |
| `recipe` | string | -- | Built-in: `linkedin_search`, `linkedin_profile`, `page_links`, `page_meta` |
| `script` | string | -- | Custom JS extraction function |
| `max_items` | int | 10 | Limit extracted items |

### ghost_status

Show instance connection and cache state.

```bash
./ghost-cli call ghost_status --arguments '{"instance_id":"demo"}'
```

### ghost_save_auth

Export browser cookies to persist sessions across restarts.

```bash
./ghost-cli call ghost_save_auth --arguments '{"instance_id":"demo"}'
```

### ghost_instance_list

List all known instances and their state.

```bash
./ghost-cli call ghost_instance_list
```

### ghost_instance_close

Close and unregister a named instance.

```bash
./ghost-cli call ghost_instance_close --arguments '{"instance_id":"demo"}'
```

## REPL Mode

```bash
./ghost-cli repl
```

Send one JSON command per line:

```json
{"tool":"ghost_instance_create","arguments":{"instance_id":"live"}}
{"tool":"ghost_vacuum","arguments":{"url":"https://news.ycombinator.com","limit":30}}
{"tool":"ghost_click","arguments":{"choice":5,"wait":"networkidle"}}
{"tool":"ghost_read","arguments":{"max_chars":2000}}
{"tool":"ghost_tab_open","arguments":{"url":"https://example.com"}}
{"tool":"ghost_tab_list","arguments":{}}
{"tool":"ghost_tab_switch","arguments":{"tab_index":0}}
{"tool":"ghost_scroll","arguments":{"direction":"down"}}
```

Each line returns a JSON envelope:

```json
{"ok":true,"tool":"ghost_vacuum","output":"=== Hacker News ===\n...","parsed":null}
```

## Error Handling

All errors follow the structured format: `Error [CODE]: message`

Codes: `ELEMENT_NOT_FOUND`, `NAVIGATION_TIMEOUT`, `NO_BROWSER`, `NO_VACUUM`,
`INVALID_INPUT`, `BROWSER_DISCONNECTED`, `TAB_NOT_FOUND`, `CLICK_FAILED`,
`FILL_REQUIRED`, `INSTANCE_NOT_FOUND`, `BLOCKED_URL`, `EVAL_EXCEPTION`

## Transport Support

| Transport | Attachment | Tab Management | Notes |
|-----------|-----------|----------------|-------|
| Playwright (own browser) | `headless: true/false` | Full | Default for new instances |
| Live Chrome (CDP) | auto-detect or `cdp_url: "live-chrome"` | Full | Attaches to user's Chrome |
| Chrome Transport | via `chrome_transport.py` | Via instances | Consumes chrome-devtools-mcp to reach Chrome |
| Playwright Session | `playwright_session` param | Via instances | Managed auth sessions |
| Liquid CDP | auto-detect on `localhost:9222` | N/A | Workspace browser |
