# Ghost functionality

Ghost exposes one shared command set over Chrome and Hermes Desktop.

| Command | Function |
|---|---|
| `ghost_status` | Check the browser connection and active page |
| `ghost_tab_list` | List tabs |
| `ghost_tab_open` | Open a tab |
| `ghost_tab_switch` | Activate a tab |
| `ghost_tab_close` | Close a tab |
| `ghost_navigate` | Navigate the active or selected tab |
| `ghost_vacuum` | Navigate and enumerate interactive elements |
| `ghost_read` | Read bounded page text |
| `ghost_pdf_read` | Read bounded PDF pages through Chrome |
| `ghost_click` | Click an enumerated element or selector |
| `ghost_fill` | Fill an input |
| `ghost_key` | Press a key or type text |
| `ghost_eval` | Run a JavaScript function in the page |
| `ghost_screenshot` | Capture the visible page |
| `ghost_scroll` | Scroll the page |
| `ghost_wait` | Wait for a selector or bounded delay |

Chrome uses the authenticated extension bridge on loopback. Hermes Desktop uses
the authenticated local protocol described in `IN_APP_BROWSER_PROTOCOL.md`.
The Hermes Agent adapter in `hermes-plugin/` registers the same tools without
adding dependencies to Hermes core.
