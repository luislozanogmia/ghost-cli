# ghost-cli

Ghost Browser -- AI browser automation via numbered accessibility menus.

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Browser Modes

Ghost supports three browser attachment modes:

| Mode | Flag | Behavior |
|------|------|----------|
| **Live Chrome** | (default) | Attaches to the user's open Chrome via DevToolsActivePort websocket |
| **Playwright headed** | `"headless": false` | Launches own isolated Chromium with a visible window |
| **Playwright headless** | `"headless": true` | Launches own isolated Chromium with no window (for CI/agents) |

When `headless` is not set (default `false`), Ghost auto-detects and attaches to your
running Chrome. Set `headless: true` to guarantee an isolated Playwright browser that
never touches your Chrome session -- ideal for delegating work to sub-agents.

```bash
# Attach to your live Chrome (default)
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"live"}'

# Launch isolated headless Chromium (agents/CI)
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"worker","headless":true}'

# Launch isolated headed Chromium (visible but separate from your Chrome)
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"demo","headless":false}' --headless=false
```

You can also set the `GHOST_HEADLESS=1` environment variable to default all
`ghost_instance_create` calls to headless mode.

## Quick Start

```bash
# List available tools
./ghost-cli list-tools

# One-shot commands (persistent daemon auto-starts)
./ghost-cli call ghost_vacuum --arguments '{"url":"https://news.ycombinator.com","limit":30}'
./ghost-cli call ghost_click --arguments '{"choice":5,"wait":"networkidle"}'
./ghost-cli call ghost_read --arguments '{"url":"https://example.com","max_chars":4000}'

# Interactive REPL
./ghost-cli repl
```

`ghost-cli call` is **persistent by default** -- it auto-starts a local daemon and
reuses the same runtime across separate shell calls. The same `instance_id` keeps
its browser attach, vacuum state, and tab context. Use `--ephemeral` only for
throwaway one-shot commands.

## Tools

### Core Navigation

| Tool | Purpose |
|------|---------|
| `ghost_vacuum` | Navigate + extract numbered interactive element menu |
| `ghost_click` | Execute action by menu number, auto re-vacuums |
| `ghost_more` | Paginate through cached vacuum results |
| `ghost_scroll` | Scroll page (lazy-load content) and re-vacuum |

### Content Reading

| Tool | Purpose |
|------|---------|
| `ghost_read` | Extract clean readable text (like reader mode) |
| `ghost_eval` | Run arbitrary JavaScript on the page |
| `ghost_extract` | Structured extraction with built-in recipes |

### Tab Management

| Tool | Purpose |
|------|---------|
| `ghost_tab_list` | List all open tabs with index and URL |
| `ghost_tab_open` | Open a new tab (optionally with URL) |
| `ghost_tab_switch` | Switch active tab by index, auto-vacuums |
| `ghost_tab_close` | Close a tab by index |

### Screenshots

| Tool | Purpose |
|------|---------|
| `ghost_screenshot` | Capture viewport or full page. Set `inline: true` for base64 data |

### Instance Management

| Tool | Purpose |
|------|---------|
| `ghost_instance_create` | Create/reuse named browser instance |
| `ghost_instance_list` | List all active instances |
| `ghost_instance_close` | Close and unregister an instance |
| `ghost_status` | Show connection/cache state for one instance |
| `ghost_save_auth` | Export browser cookies to persist sessions |

## Wait Strategies

`ghost_vacuum` and `ghost_click` accept a `wait` parameter:

| Strategy | Behavior | Best for |
|----------|----------|----------|
| `load` (default) | Wait for DOMContentLoaded + 2s settle | Most pages |
| `networkidle` | Wait until network is idle 500ms | SPAs, AJAX-heavy pages |
| `none` | No wait, immediate re-vacuum | Already-loaded content |

## Structured Error Codes

All errors return a machine-readable format: `Error [CODE]: message`

| Code | Meaning |
|------|---------|
| `ELEMENT_NOT_FOUND` | Menu number doesn't exist in cached vacuum |
| `NAVIGATION_TIMEOUT` | Page load or click timed out |
| `NO_BROWSER` | No browser connected yet |
| `NO_VACUUM` | Must vacuum before clicking |
| `INVALID_INPUT` | Missing or malformed argument |
| `BROWSER_DISCONNECTED` | Browser crashed or was closed externally |
| `TAB_NOT_FOUND` | Tab index out of range |
| `CLICK_FAILED` | Element could not be activated |
| `FILL_REQUIRED` | Textbox/searchbox needs a `value` argument |
| `INSTANCE_NOT_FOUND` | Named instance doesn't exist |

## AI Agent Tips

These behaviors trip up fresh agents. Know them before your first session:

- **Always re-vacuum after navigation.** Element numbers are only valid for the current page state. If you click a link or the page reloads, your old numbers are stale -- `ghost_vacuum` again before clicking.
- **Use `limit` to reduce noise.** Dense pages (LinkedIn, dashboards) return 80+ elements. Set `"limit": 20` or `"limit": 30` to get the most relevant items without drowning in nav/footer/ad elements.
- **Sleep between profile visits.** Ghost has no built-in rate limiter. If you're visiting 10+ pages in sequence on LinkedIn or similar sites, add 3-5 second pauses between calls to avoid triggering anti-bot detection.
- **`ghost_read` for content, `ghost_vacuum` for interaction.** If you just need to check whether a word appears on the page, use `ghost_read` -- it returns clean text without the numbered element overhead.
- **One instance per workflow.** Don't create a new instance for every call. Keep the same `instance_id` throughout -- it preserves browser state, cookies, and vacuum cache.
- **Save auth immediately after manual login.** The human logs in once, you call `ghost_save_auth`, and that session persists across daemon restarts.
- **Headless for delegation.** When spawning sub-agents that need browser access, use `"headless": true` so they get their own isolated Chromium without touching the user's Chrome.

## Extraction Recipes

Built-in recipes for `ghost_extract`:

- `linkedin_search` -- numbered profile list from LinkedIn search results
- `linkedin_profile` -- formatted profile card
- `page_links` -- numbered link list from any page
- `page_meta` -- title, description, OG tags

## Daemon Management

```bash
./ghost-cli daemon-status   # Check if persistent daemon is running
./ghost-cli daemon-stop     # Shut down the daemon cleanly
```

## Advanced Usage

Attach to managed Playwright LinkedIn sessions:

```bash
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"li-b","playwright_session":"linkedin_auth_b"}'
./ghost-cli call ghost_vacuum --arguments '{"instance_id":"li-b","url":"https://www.linkedin.com/feed/"}'
```

Attach to an external CDP endpoint (e.g. Liquid workspace browser):

```bash
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"ext","cdp_url":"http://localhost:9222"}'
```

Batch extraction across multiple URLs:

```bash
./ghost-cli batch --queries queries.json --recipe linkedin_search --output results.json
```

## Known Limitations & Roadmap

| # | Issue | Status |
|---|-------|--------|
| 1 | Vacuum output lacks semantic filtering (no "only show profile cards" mode) | Planned |
| 2 | No built-in rate limiting or anti-detection pacing between requests | Planned |
| 3 | Error messages don't suggest recovery actions (e.g. "re-vacuum first") | Planned |
| 4 | No text search primitive (`ghost_find_text` or `ghost_grep` for page content) | Planned |
| 5 | Screenshots return path only -- no text description for non-multimodal agents | Planned |
| 6 | No scroll-to-element by text/selector (only blind `ghost_more`) | Planned |
| 7 | Stale instances don't auto-expire -- manual cleanup required | Planned |

Contributions welcome. Open an issue to discuss before sending PRs.

## Architecture

```
ghost-cli (CLI entrypoint)
  -> ghost_daemon.py (persistent background process)
    -> runtime_host.py (tool dispatch + GhostInstance lifecycle)
      -> helpers/vacuum.py (accessibility tree -> numbered menu)
      -> helpers/execute.py (menu number -> Playwright action)
      -> helpers/extractors.py (built-in extraction recipes)
      -> chrome_transport.py (Chrome MCP bridge)
      -> playwright_session_transport.py (managed Playwright sessions)
```

## Status

The old Ghost MCP server path is archived under `deprecated/mcp/`. The supported
path is this CLI runtime only.

See [FUNCTIONALITY.md](./FUNCTIONALITY.md) for the full CLI command reference.
