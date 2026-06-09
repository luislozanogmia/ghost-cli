---
name: ghost-cli
description: Ghost Browser v3 browser automation via the `ghost-cli` direct runtime. The old server path remains only as an unsupported legacy shim.
---

# Ghost CLI

Use this skill when browser automation should run through Ghost Browser v3 using the direct CLI runtime.

## What this skill provides
- A deterministic direct CLI runtime with named browser instances
- A persistent local daemon for `ghost-cli call`, so long workflows survive across shell invocations
- A long-lived JSON-line REPL for agentic browser sessions
- A bridge for vacuum/action workflows over live browser pages
- Chrome session attachment through the Ghost runtime, including external browser support
- LinkedIn auth through `browser_context/linkedin_auth.json`
- A legacy server shim kept only for older integrations and not supported for production use

## Architecture
```text
You (Coding Agent)
  ↓ CLI / JSON lines
ghost_cli.py               <- the supported entrypoint
  ↓
runtime host               <- in-process Ghost runtime
  ↓
transport layer            <- live Chrome, direct CDP, or Playwright session
  ↓
browser/session target
```

Primary path: `./ghost-cli`

Archived legacy server path: `deprecated/mcp/`

The legacy server path is not supported for real browsing runs. It was moved to
`deprecated/mcp/` so the repo root only carries the supported CLI runtime.

## One-Time Wiring

From the skill folder:

```bash
pip install -r requirements.txt
playwright install chromium
```

## Runner
- `./ghost-cli list-tools`
- `./ghost-cli call ghost_status`
- `./ghost-cli call ghost_instance_create --arguments '{"instance_id":"live","cdp_url":"live-chrome"}'`
- `./browser_context/linkedin/open_linkedin_ghost.sh open`
- `./browser_context/linkedin/open_linkedin_ghost.sh vacuum`
- `./ghost-cli daemon-status`
- `./ghost-cli daemon-stop`
- `./ghost-cli repl`
- `python3 helpers/ghost_cache_bridge.py --help`
- `python3 helpers/ghost_cache_bridge.py --self-test`
- `python3 helpers/ghost_cache_bridge.py vacuum <temp_file> --url <url> --title <title>`
- `python3 helpers/ghost_cache_bridge.py action <choice> --value <text>`
- `python3 deprecated/mcp/ghost_stdio_proxy.py` (archived unsupported shim)

See [FUNCTIONALITY.md](FUNCTIONALITY.md) for the old-tool to CLI mapping.

## Commands You Have

| Tool | What it does |
|---|---|
| `ghost_status` | Check if browser is connected; call this first if unsure |
| `ghost_vacuum` | Read current page and return a numbered list of interactive elements |
| `ghost_click` | Click element by number from vacuum output |
| `ghost_more` | Scroll / load more elements (`offset=N` to skip ahead) |
| `ghost_screenshot` | Take a screenshot for visual verification |
| `ghost_save_auth` | Save current browser cookies to disk; call immediately after manual login |
| `ghost_extract` | Extract structured data using a named recipe or custom JS. Returns clean JSON. |
| `ghost_instance_create` | Create or reuse a named Chrome session, optionally navigating to a URL |
| `ghost_instance_list` | List all active named sessions |
| `ghost_instance_close` | Close a named session without deleting its profile |

All commands accept optional `instance_id`. Omit it to use the `default` session.

## Critical Rules
1. Always call `ghost_status` before assuming the browser is connected.
2. Always re-vacuum after navigation; element numbers are only valid for the current page state.
3. Always call `ghost_save_auth` immediately after login so auth persists.
4. Use different `instance_id` values for independent browser sessions.
5. `./ghost-cli call` is persistent by default; keep the same `instance_id` across calls for long LinkedIn runs.
6. Do not treat anything under `deprecated/mcp/` as a supported production transport.
7. For LinkedIn agent work, use the stable Ghost instance `linkedin` via `./browser_context/linkedin/open_linkedin_ghost.sh`.
8. Do not use `playwright_session` / `linkedin-json` for LinkedIn Ghost workflows. That path can cause `ghost_vacuum` to reopen managed Playwright browsers.
9. For LinkedIn auth backup/refresh, use `browser_context/linkedin_auth.json`; the durable browser profile is `browser_context/linkedin/chrome_profile`.

## LinkedIn Stable Browser

LinkedIn has a dedicated persistent Ghost profile and launcher:

```bash
./browser_context/linkedin/open_linkedin_ghost.sh open
./browser_context/linkedin/open_linkedin_ghost.sh vacuum
```

This creates/reuses:

- Ghost instance: `linkedin`
- Browser profile: `browser_context/linkedin/chrome_profile`
- Auth seed/backup: `browser_context/linkedin_auth.json`

Agent contract:

- Always pass `instance_id:"linkedin"` for LinkedIn `ghost_vacuum`, `ghost_click`, `ghost_more`, `ghost_screenshot`, and `ghost_extract`.
- Keep `GHOST_HEADLESS=1` for normal agent work. In Ghost CLI, non-headless creation can try to attach to live Chrome and may open or attach the wrong browser.
- Never create a LinkedIn Ghost instance with `playwright_session:"linkedin-json"`. The Playwright session manager may call `open about:blank --headed` during `ghost_vacuum`, which causes repeated browser windows.
- Do not create new LinkedIn instance names unless Luis explicitly asks for an isolated session.

Manual re-login flow:

```bash
./browser_context/linkedin/open_linkedin_ghost.sh login
# Luis logs in visibly and selects any "keep me logged in" / trusted-device prompt.
./browser_context/linkedin/open_linkedin_ghost.sh save
```

After `save`, the launcher updates `linkedin_auth.json`, closes the visible login session, and reopens the native Ghost `linkedin` instance.

## Standard Flow
1. Check connection
```text
./ghost-cli call ghost_status
```

2. Read the page
```text
./ghost-cli call ghost_vacuum
```
Returns a numbered list of every interactive element. Elements are indexed starting at 1.

LinkedIn stable session:

```text
./browser_context/linkedin/open_linkedin_ghost.sh open
GHOST_HEADLESS=1 ./ghost-cli call ghost_vacuum --arguments '{"instance_id":"linkedin","url":"https://www.linkedin.com/feed/","limit":20}'
```

3. Interact
```text
./ghost-cli call ghost_click --arguments '{"choice":7}'
./ghost-cli call ghost_more
./ghost-cli call ghost_screenshot
```

4. Re-vacuum after any navigation. Element numbers reset on every new page state, but persistent `call` keeps the same cache across shell invocations for the same `instance_id`.

## Extraction Recipes

Ghost includes pre-built extraction recipes for common page patterns. These run
JS in the browser and return clean JSON -- no DOM noise reaches your context.

### LinkedIn Search Results
```text
./ghost-cli call ghost_extract --arguments '{"instance_id":"li","recipe":"linkedin_search","max_items":10}'
```
Returns: `[{url, name, title, location, snippet}, ...]`

### LinkedIn Profile
```text
./ghost-cli call ghost_extract --arguments '{"instance_id":"li","recipe":"linkedin_profile"}'
```
Returns: `{name, headline, location, about, experiences, education}`

### All Page Links
```text
./ghost-cli call ghost_extract --arguments '{"instance_id":"demo","recipe":"page_links","max_items":20}'
```
Returns: `[{text, href}, ...]`

### Page Metadata
```text
./ghost-cli call ghost_extract --arguments '{"instance_id":"demo","recipe":"page_meta"}'
```
Returns: `{title, url, description, og_title, og_image, canonical, h1}`

### Custom Extraction
```text
./ghost-cli call ghost_extract --arguments '{"instance_id":"demo","script":"() => [...document.querySelectorAll(\"h2\")].map(e => e.textContent)"}'
```

## Batch Extraction

Extract data from multiple URLs in one command:

```text
./ghost-cli batch --queries '[{"url":"https://linkedin.com/search/results/people/?keywords=fintech+austin","label":"fintech_austin","recipe":"linkedin_search"}]' --delay 4 --output results.json
```

Or from a file:
```text
./ghost-cli batch --queries queries.json --recipe linkedin_search --output results.json
```

## Multi-Session Pattern
Use when you need two independent browser sessions simultaneously:

```text
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"session-a","url":"https://example.com"}'
./ghost-cli call ghost_instance_create --arguments '{"instance_id":"session-b","url":"https://other.com"}'
./ghost-cli call ghost_vacuum --arguments '{"instance_id":"session-a"}'
./ghost-cli call ghost_click --arguments '{"instance_id":"session-b","choice":5}'
./ghost-cli call ghost_instance_close --arguments '{"instance_id":"session-b"}'
```

Always pass the same `instance_id` on every call for that session.

## Auth Persistence
LinkedIn and other sites expire sessions. For LinkedIn, use the launcher:
1. Run `./browser_context/linkedin/open_linkedin_ghost.sh login`
2. Luis logs in manually in the visible browser.
3. Run `./browser_context/linkedin/open_linkedin_ghost.sh save`
4. Continue automation with Ghost `instance_id:"linkedin"`.

Never attempt to type passwords.
