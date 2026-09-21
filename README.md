# Ghost CLI

Ghost gives local agents a small browser-control surface with two supported
targets:

- a signed-in Chrome window through the Ghost extension; and
- the browser pane already running in Hermes Desktop.

Both transports are local and token-authenticated. Ghost never asks the model
for browser credentials and does not export browser session material.

## Chrome setup

```bash
./install-extension.sh
```

Load `extension/` as an unpacked Chrome extension. The installer starts the
loopback bridge and prints a pairing token. Paste that token into the extension
popup once. It is stored in Chrome extension-local storage; the matching local
file is private to your OS user.

```bash
./ghost-cli status --backend chrome
./ghost-cli call ghost_navigate --args '{"url":"https://example.com"}' --backend chrome
```

## Hermes Desktop setup

Hermes Desktop must implement the authenticated local protocol in
`IN_APP_BROWSER_PROTOCOL.md`. Then either use the CLI directly:

```bash
./ghost-cli status --backend hermes
```

or install `hermes-plugin/` as a Hermes Agent plugin. The plugin defaults to
`auto`, preferring the Hermes Desktop browser when present and otherwise using
the Chrome extension.

## Supported tools

`ghost_status`, `ghost_tab_list`, `ghost_tab_open`, `ghost_tab_switch`,
`ghost_tab_close`, `ghost_navigate`, `ghost_vacuum`, `ghost_read`,
`ghost_pdf_read`, `ghost_click`, `ghost_fill`, `ghost_key`, `ghost_eval`, `ghost_screenshot`,
`ghost_scroll`, and `ghost_wait`.

PDF reading is Chrome-only. The other listed commands are shared by Chrome and
Hermes Desktop.

`ghost_eval` intentionally remains available because some browser tasks require
page-context JavaScript. Treat its script input as privileged local code.

## Security

- All listeners bind only to loopback or a private Unix socket.
- HTTP and extension WebSocket traffic require the same high-entropy token.
- Tokens are never accepted in URLs and are not written to logs.
- Chrome accepts commands only after the extension authenticates.
- Responses are bounded; PDF uploads additionally use one-time capabilities.
