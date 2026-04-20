#!/usr/bin/env python3
"""Ghost Chrome Proxy — shared HTTP proxy wrapping chrome-devtools-mcp.

Chrome only allows ONE CDP debugger connection. This proxy holds that single
connection and exposes it to any number of consumers via HTTP on port 8766.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from aiohttp import web
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

LOG = logging.getLogger("ghost.chrome_proxy")
PORT = 8766
PID_FILE = Path(__file__).parent / "ghost_chrome_proxy.pid"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _tool_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


class GhostChromeProxy:
    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._tools: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/tools", self._handle_tools)
        self._app.router.add_post("/call", self._handle_call)

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "connected": self._session is not None,
            "pid": os.getpid(),
        })

    async def _handle_tools(self, _request: web.Request) -> web.Response:
        return web.json_response({"tools": self._tools})

    async def _handle_call(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(
                {"result": None, "error": "invalid JSON body"}, status=400
            )

        name = body.get("name", "")
        arguments = body.get("arguments", {})
        timeout = body.get("timeout", 60)
        page_id = body.get("page_id")  # optional int -- switch to this tab first

        if not name:
            return web.json_response(
                {"result": None, "error": "missing 'name' field"}, status=400
            )

        if self._session is None:
            return web.json_response(
                {"result": None, "error": "MCP session not connected"}, status=503
            )

        # Tools that manage pages themselves don't need a prior tab switch
        _NO_PRESELECT = {"select_page", "list_pages", "new_page"}

        async with self._lock:
            try:
                if page_id is not None and name not in _NO_PRESELECT:
                    await self._session.call_tool(
                        "select_page",
                        {"pageId": page_id, "bringToFront": False},
                        read_timeout_seconds=timedelta(seconds=10),
                    )
                result = await asyncio.wait_for(
                    self._session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(seconds=timeout),
                    ),
                    timeout=timeout + 5,
                )
                return web.json_response({"result": _tool_text(result), "error": None})
            except asyncio.TimeoutError:
                return web.json_response(
                    {"result": None, "error": f"timeout after {timeout}s"}
                )
            except Exception as exc:
                LOG.exception("Tool call %s failed", name)
                return web.json_response(
                    {"result": None, "error": str(exc)}
                )

    async def run(self) -> None:
        PID_FILE.write_text(str(os.getpid()))
        LOG.info("PID %d written to %s", os.getpid(), PID_FILE)

        if os.name == "nt":
            server_params = StdioServerParameters(
                command="cmd",
                args=[
                    "/c", "npx", "-y", "chrome-devtools-mcp@latest",
                    "--no-usage-statistics", "--autoConnect", "--channel=stable",
                ],
            )
        else:
            server_params = StdioServerParameters(
                command="npx",
                args=[
                    "-y", "chrome-devtools-mcp@latest",
                    "--no-usage-statistics", "--autoConnect", "--channel=stable",
                ],
            )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._session = session

                tools_result = await session.list_tools()
                self._tools = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
                    }
                    for t in tools_result.tools
                ]
                LOG.info("Cached %d tools from chrome-devtools-mcp", len(self._tools))

                runner = web.AppRunner(self._app)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", PORT)
                await site.start()
                LOG.info("Ghost Chrome Proxy ready on http://127.0.0.1:%d", PORT)

                stop_event = asyncio.Event()

                def _signal_handler() -> None:
                    LOG.info("Received shutdown signal")
                    stop_event.set()

                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    try:
                        loop.add_signal_handler(sig, _signal_handler)
                    except NotImplementedError:
                        # Windows doesn't support add_signal_handler for all signals
                        pass

                # On Windows, also handle Ctrl+C via default KeyboardInterrupt
                try:
                    await stop_event.wait()
                except (KeyboardInterrupt, SystemExit):
                    pass

                LOG.info("Shutting down...")
                self._session = None
                await runner.cleanup()

        if PID_FILE.exists():
            PID_FILE.unlink()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if _port_in_use(PORT):
        LOG.info("Port %d already in use — proxy already running", PORT)
        sys.exit(0)

    proxy = GhostChromeProxy()

    try:
        asyncio.run(proxy.run())
    except KeyboardInterrupt:
        LOG.info("Interrupted")
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


if __name__ == "__main__":
    main()
