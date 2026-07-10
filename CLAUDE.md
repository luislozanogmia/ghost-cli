# Ghost CLI -- Skill Guide

## Golden Rule: Use the Daemon

**Never run bare `python -c` or `python << 'EOF'` to call Ghost tools against the user's Chrome.**

Each bare Python process creates a new CDP connection, which triggers Chrome's "Allow remote debugging?" dialog. The user has to click Allow every single time.

Instead, always use:
```bash
./ghost-cli call <tool_name> --arguments '{"key": "value"}'
```

The daemon (`ghost_daemon.py`) holds one persistent CDP connection. The user approves once, and all subsequent calls reuse it.

Bare Python is only acceptable for **headless mode** (`"headless": true`) where no user Chrome is involved.

## Connecting to the User's Chrome

```bash
# Canonical connection: discovers/reuses live Chrome through the shared
# chrome-devtools-mcp broker and rejects any Playwright fallback.
./ghost-cli live-connect

# All subsequent calls reuse the same connection -- no more prompts
./ghost-cli call ghost_tab_list --arguments '{"instance_id":"live"}'
./ghost-cli call ghost_vacuum --arguments '{"instance_id":"live","url":"https://example.com"}'
./ghost-cli call ghost_click --arguments '{"instance_id":"live","choice":5}'
```

The command must report `backend=chrome-devtools-mcp`, `transport=chrome-transport`, `browser_connected=true`, and `playwright_used=false`. Do not manually pass a Chrome websocket URL or start another Chrome MCP process.

## Headless Mode (for Agents/CI)

```bash
# Isolated Chromium -- never touches user's Chrome, no approval needed
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"worker","headless":true}'
```

Use headless when delegating to sub-agents or running automated workflows.

## Common Workflows

### Vacuum-Click Loop
```bash
./ghost-cli call ghost_vacuum --arguments '{"instance_id":"live","url":"https://example.com","limit":30}'
./ghost-cli call ghost_click --arguments '{"instance_id":"live","choice":5,"wait":"networkidle"}'
```

### Read Page Content
```bash
./ghost-cli call ghost_read --arguments '{"instance_id":"live","max_chars":4000}'
./ghost-cli call ghost_read --arguments '{"instance_id":"live","url":"https://example.com","selector":"article"}'
```

### SPA Extraction (WhatsApp, LinkedIn, Gmail)
```bash
./ghost-cli call ghost_eval --arguments '{"instance_id":"live","script":"() => document.title"}'
./ghost-cli call ghost_extract --arguments '{"instance_id":"live","recipe":"page_links"}'
```

### Multi-Tab
```bash
./ghost-cli call ghost_tab_list --arguments '{"instance_id":"live"}'
./ghost-cli call ghost_tab_switch --arguments '{"instance_id":"live","tab_index":3}'
./ghost-cli call ghost_tab_open --arguments '{"instance_id":"live","url":"https://example.com"}'
```

### Keyboard Input
```bash
./ghost-cli call ghost_key --arguments '{"instance_id":"live","key":"Escape"}'
./ghost-cli call ghost_key --arguments '{"instance_id":"live","text":"search query"}'
```

## Error Codes

All errors: `Error [CODE]: message`. Codes: `ELEMENT_NOT_FOUND`, `NAVIGATION_TIMEOUT`, `NO_BROWSER`, `NO_VACUUM`, `INVALID_INPUT`, `BROWSER_DISCONNECTED`, `TAB_NOT_FOUND`, `CLICK_FAILED`, `FILL_REQUIRED`.

## Daemon Management

```bash
./ghost-cli daemon-status   # Is the daemon up?
./ghost-cli daemon-stop     # Shut it down (drops all connections)
```
