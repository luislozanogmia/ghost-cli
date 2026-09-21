# Ghost for Hermes Agent

This standalone plugin registers Ghost's browser tools in Hermes Agent. It can
control either:

- a regular Chrome window through the authenticated Ghost extension bridge; or
- the browser pane in Hermes Desktop through its authenticated local socket.

The default `backend: auto` tries Hermes Desktop first, then Chrome. Set
`backend` to `chrome` or `hermes` in the plugin configuration to require one.

## Install from a checkout

```bash
hermes plugins install ./hermes-plugin
hermes tools enable ghost
```

For Chrome, start `./ghost-cli serve`, run `./ghost-cli bridge-token`, and paste
that value into the extension popup. For Hermes Desktop, the app must expose
the protocol documented in `IN_APP_BROWSER_PROTOCOL.md` and create its private
token file.

The plugin intentionally does not export browser session material. JavaScript
evaluation is available as `ghost_eval` on both browser targets.
`ghost_pdf_read` is available only through the Chrome extension.
