# Ghost Functionality

Primary interface: `python3 ghost_cli.py`

The Ghost MCP daemon/proxy path is no longer the primary operational path. The
direct CLI runtime exposes the same browser actions without the shared HTTP
daemon and backend-session reconnect layer.

## Tool Parity

| Former tool | CLI form | Notes |
|---|---|---|
| `ghost_instance_create` | `python3 ghost_cli.py call ghost_instance_create --arguments '{"instance_id":"demo","cdp_url":"live-chrome"}'` | Creates or reuses a named instance. |
| `ghost_instance_list` | `python3 ghost_cli.py call ghost_instance_list` | Lists known instances and current state. |
| `ghost_instance_close` | `python3 ghost_cli.py call ghost_instance_close --arguments '{"instance_id":"demo"}'` | Closes one named instance. |
| `ghost_status` | `python3 ghost_cli.py call ghost_status --arguments '{"instance_id":"demo"}'` | Returns connection and cache status. |
| `ghost_vacuum` | `python3 ghost_cli.py call ghost_vacuum --arguments '{"instance_id":"demo","limit":50}'` | Produces numbered menu output. |
| `ghost_more` | `python3 ghost_cli.py call ghost_more --arguments '{"instance_id":"demo","offset":50}'` | Pages through cached vacuum output. |
| `ghost_click` | `python3 ghost_cli.py call ghost_click --arguments '{"instance_id":"demo","choice":17}'` | Executes a numbered action and re-vacuums. |
| `ghost_eval` | `python3 ghost_cli.py call ghost_eval --arguments '{"instance_id":"demo","script":"() => document.title"}'` | Runs page JS. |
| `ghost_screenshot` | `python3 ghost_cli.py call ghost_screenshot --arguments '{"instance_id":"demo","full_page":true}'` | Saves a screenshot to disk. |
| `ghost_save_auth` | `python3 ghost_cli.py call ghost_save_auth --arguments '{"instance_id":"demo"}'` | Persists browser auth. |

## Long-Lived Agent Mode

For agentic browsing, use a single long-lived CLI session:

```bash
python ghost_cli.py repl
```

Send one JSON command per line:

```json
{"tool":"ghost_instance_create","arguments":{"instance_id":"live","cdp_url":"live-chrome"}}
{"tool":"ghost_vacuum","arguments":{"instance_id":"live","limit":50}}
{"tool":"ghost_click","arguments":{"instance_id":"live","choice":16}}
```

Each line returns a JSON envelope:

```json
{"ok":true,"tool":"ghost_status","output":"{...}","parsed":{...}}
```

This keeps Ghost state in one process without the MCP daemon/proxy stack.
