---
name: ghost_mcp
description: Ghost Browser v3 browser automation via the direct CLI runtime, with MCP kept only as a legacy compatibility shim.
---

# Ghost CLI

Use this skill when browser automation should run through Ghost Browser v3 using the direct CLI runtime instead of the older Ghost MCP daemon/proxy flow.

## What this skill provides
- A deterministic direct CLI runtime with named browser instances
- A long-lived JSON-line REPL for agentic browser sessions
- A bridge for vacuum/action workflows over live browser pages
- Chrome session attachment through the Ghost runtime, including external browser support
- A legacy MCP compatibility shim that now acts only as a translation layer

## Architecture
```text
You (Coding Agent)
  ↓ CLI / JSON lines
ghost_cli.py               <- the primary entrypoint
  ↓
mcp_server.py              <- runtime host / compatibility layer
  ↓
chrome_mcp_runtime.py      <- Chrome transport when live Chrome attach is needed
  ↓
Chrome (live browser)
```

Primary path: `ghost_cli.py`

Legacy-only path: `ghost_stdio_proxy.py`

The MCP path is no longer the primary execution route. If used, it should only act as a translation layer over the same direct runtime.

## One-Time Wiring

From the skill folder:

```bash
pip install -r requirements.txt
playwright install chromium
```

To expose the server to an MCP client, point it at `ghost_stdio_proxy.py`:

```json
{
  "mcpServers": {
    "ghost": {
      "command": "python",
      "args": ["/path/to/ghost-mcp/ghost_stdio_proxy.py"]
    }
  }
}
```

If you are wiring Codex itself, add the `ghost` entry under your `mcp_servers` config and point it at the same proxy command:

```toml
[mcp_servers.ghost]
command = "/Users/luis.lozano/.codex/skills/ghost_mcp/.venv/bin/python"
args = ["/Users/luis.lozano/.codex/skills/ghost_mcp/ghost_stdio_proxy.py"]
enabled = true
```

Then reload or restart Codex so the new MCP server is registered.

## Runner
- `python3 ghost_cli.py list-tools`
- `python3 ghost_cli.py call ghost_status`
- `python3 ghost_cli.py call ghost_instance_create --arguments '{"instance_id":"live","cdp_url":"live-chrome"}'`
- `python3 ghost_cli.py repl`
- `python3 ghost_mcp.py --help`
- `python3 ghost_mcp.py --self-test`
- `python3 ghost_mcp.py vacuum <temp_file> --url <url> --title <title>`
- `python3 ghost_mcp.py action <choice> --value <text>`
- `python3 ghost_stdio_proxy.py` (legacy compatibility shim)

See [FUNCTIONALITY.md](/Users/luis.lozano/.codex/skills/ghost_mcp/FUNCTIONALITY.md:1) for the old-tool to CLI mapping.

## Commands You Have

| Tool | What it does |
|---|---|
| `ghost_status` | Check if browser is connected; call this first if unsure |
| `ghost_vacuum` | Read current page and return a numbered list of interactive elements |
| `ghost_click` | Click element by number from vacuum output |
| `ghost_more` | Scroll / load more elements (`offset=N` to skip ahead) |
| `ghost_screenshot` | Take a screenshot for visual verification |
| `ghost_save_auth` | Save current browser cookies to disk; call immediately after manual login |
| `ghost_instance_create` | Create or reuse a named Chrome session, optionally navigating to a URL |
| `ghost_instance_list` | List all active named sessions |
| `ghost_instance_close` | Close a named session without deleting its profile |

All commands accept optional `instance_id`. Omit it to use the `default` session.

## Critical Rules
1. Always call `ghost_status` before assuming the browser is connected.
2. Always re-vacuum after navigation; element numbers are only valid for the current page state.
3. Always call `ghost_save_auth` immediately after login so auth persists.
4. Use different `instance_id` values for independent browser sessions.
5. Prefer `ghost_cli.py repl` for long LinkedIn runs so state stays in one CLI process.

## Standard Flow
1. Check connection
```text
python3 ghost_cli.py call ghost_status
```

2. Read the page
```text
python3 ghost_cli.py call ghost_vacuum
```
Returns a numbered list of every interactive element. Elements are indexed starting at 1.

3. Interact
```text
python3 ghost_cli.py call ghost_click --arguments '{"choice":7}'
python3 ghost_cli.py call ghost_more
python3 ghost_cli.py call ghost_screenshot
```

4. Re-vacuum after any navigation. Element numbers reset on every new page.

## Multi-Session Pattern
Use when you need two independent browser sessions simultaneously:

```text
python3 ghost_cli.py call ghost_instance_create --arguments '{"instance_id":"session-a","url":"https://example.com"}'
python3 ghost_cli.py call ghost_instance_create --arguments '{"instance_id":"session-b","url":"https://other.com"}'
python3 ghost_cli.py call ghost_vacuum --arguments '{"instance_id":"session-a"}'
python3 ghost_cli.py call ghost_click --arguments '{"instance_id":"session-b","choice":5}'
python3 ghost_cli.py call ghost_instance_close --arguments '{"instance_id":"session-b"}'
```

Always pass the same `instance_id` on every call for that session.

## Auth Persistence
LinkedIn and other sites expire sessions. Correct flow:
1. User logs in manually in the browser
2. You call `ghost_save_auth` immediately on the same `instance_id`
3. Ghost saves cookies and loads them automatically on next startup

Never attempt to type passwords.
