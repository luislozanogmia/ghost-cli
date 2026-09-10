# Pending cleanup

The current release remains `0.3.2`. The items below are intentionally deferred
so they can be handled as separate, reviewable changes.

## 1. Make the CLI extension-only

- Route every extension-supported CLI command through `BridgeTransport`.
- Define one shared command contract for the Python CLI and extension router.
- Preserve structured errors, timeouts, tab selection, and daemon behavior.
- Add integrated tests for every bridged command before removing compatibility code.

## 2. Remove the legacy protocol stack

After bridge parity is verified:

- Remove the legacy tool-process client, debugging transport, and proxy.
- Remove their process management, status commands, tests, and dependencies.
- Remove direct debugging and managed-browser branches from `runtime_host.py` if
  they are no longer part of the supported product.
- Correct documentation so it describes only runtime paths that actually execute.

## 3. Separate or retire the page compiler

The scout/compiler commands are independent of the extension bridge. Decide
whether to package them as a separate optional tool or remove them. Do not keep
their browser dependency in the core installer unless they remain supported.

## 4. Consolidate transport experiments

The in-app browser transport and protocol are isolated from the production
runtime. Either integrate them behind an explicit interface or archive them;
do not leave an apparently supported transport that no entrypoint calls.

## 5. Minimize extension permissions and scripts

- Remove the content script if no background command calls it.
- Review broad host permissions against the commands that require them.
- Add negative tests for one-time PDF uploads, invalid sources, and oversized files.

## 6. Portable installation

- Add a package definition and console entrypoint instead of assuming a checkout layout.
- Support an explicitly selected interpreter through `GHOST_PYTHON`.
- Replace legacy platform-specific browser-location guesses with environment
  configuration or operating-system discovery APIs.
- Add clean-machine installation checks for macOS, Windows, and Linux.

## 7. Local data retention

- Keep browser profiles by default because they may contain active sessions.
- Add explicit commands for cache cleanup, log rotation, screenshot retention,
  and profile deletion.
- Never combine profile deletion with routine dependency or build cleanup.

## 8. Repository history

Historical commit messages include retired target-specific work. Removing them
requires rewriting published history and force-pushing shared branches. Do this
only during an approved maintenance window with a backup and collaborator notice.

