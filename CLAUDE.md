# Ghost CLI contributor guide

Ghost has two supported browser targets:

1. the authenticated Chrome extension bridge; and
2. the authenticated Hermes Desktop browser endpoint.

Do not add another browser transport. Keep bridge listeners local, keep tokens
out of URLs and logs, bound all request/response bodies, and add negative auth
tests for changes to either transport.

## Local use

```bash
./install-extension.sh
./ghost-cli status --backend chrome
./ghost-cli call ghost_vacuum --args '{"url":"https://example.com","limit":30}'
```

The installer creates a private token and prints it for one-time entry into the
extension popup. Direct HTTP callers must read that token and send it as a
Bearer credential; normal users should use `ghost-cli` instead.

Hermes Desktop integration follows `IN_APP_BROWSER_PROTOCOL.md`. The standalone
Hermes Agent adapter is in `hermes-plugin/` and must continue to validate with:

```bash
hermes plugins validate ./hermes-plugin
```

Run the repository checks with:

```bash
python3 -m compileall -q .
node --check extension/background.js
node --check extension/popup.js
bash -n install-extension.sh
pytest -q
```
