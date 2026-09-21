# Ghost Chrome extension

The extension uses Chrome's native tab and scripting APIs. It connects only to
the Ghost loopback bridge and must authenticate before it can receive commands.

1. Start the bridge with `../ghost-cli serve`.
2. Obtain the token with `../ghost-cli bridge-token`.
3. Load this directory as an unpacked extension.
4. Paste the token into the popup and click **Connect**.

The popup stores the token in extension-local storage. The extension and bridge
exchange nonce-bound HMAC proofs, so the token is never transmitted or placed
in the connection URL. Disconnect removes the stored pairing token and does not
reconnect until the user pairs again.
