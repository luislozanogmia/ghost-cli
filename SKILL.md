---
name: ghost
description: Control a signed-in Chrome window or the Hermes Desktop browser through authenticated local transports.
---

# Ghost Browser

Use Ghost when a task requires browser interaction in the user's existing
Chrome window or the Hermes Desktop browser pane.

## Workflow

1. Run `./ghost-cli status`.
2. Use `ghost_vacuum` or `ghost_read` to inspect the page.
3. Use `ghost_click`, `ghost_fill`, `ghost_key`, or `ghost_eval` to act.
4. Read the page again after navigation because numbered elements may change.

Never type passwords or request browser session secrets. Ask the user to perform
sensitive login steps themselves.

## CLI examples

```bash
./ghost-cli call ghost_vacuum --args '{"url":"https://example.com","limit":30}'
./ghost-cli call ghost_click --args '{"choice":2}'
./ghost-cli call ghost_eval --allow-eval --args '{"script":"() => document.title"}'
```

Select a target with `--backend chrome` or `--backend hermes`. The default
`auto` mode prefers Hermes Desktop when its browser endpoint is available.
The Chrome bridge must also be started with `--allow-eval` before eval calls are
accepted. Leave eval disabled when ordinary navigation tools are sufficient.
