# Ghost Chrome extension

The extension uses Chrome's native tab and scripting APIs. It connects only to
the Ghost loopback bridge and must authenticate before it can receive commands.

1. Start the bridge with `../ghost-cli serve`.
2. Obtain the token with `../ghost-cli bridge-token`.
3. Load this directory as an unpacked extension.
4. Paste the token into the popup and click **Connect**.

The popup stores the token in extension-local storage. The token is sent as the
first WebSocket message and is never placed in the connection URL.
