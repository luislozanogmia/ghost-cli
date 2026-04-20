from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ghost_dir = str(Path(__file__).resolve().parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

import runtime_host as runtime
from shared_runtime import (
    CLI_DAEMON_HOST,
    CLI_DAEMON_LOG_FILE,
    CLI_DAEMON_PID_FILE,
    CLI_DAEMON_PORT,
    ensure_runtime_dirs,
    setup_logging,
)


LOGGER = setup_logging("ghost.daemon", CLI_DAEMON_LOG_FILE)
_STOP_EVENT: asyncio.Event | None = None


def _write_pid_file() -> None:
    ensure_runtime_dirs()
    payload = {
        "pid": os.getpid(),
        "host": CLI_DAEMON_HOST,
        "port": CLI_DAEMON_PORT,
        "started_at": datetime.now().isoformat(),
    }
    CLI_DAEMON_PID_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def _handle_request(message: dict[str, Any]) -> dict[str, Any]:
    request_type = message.get("type")
    if request_type == "health":
        return {
            "ok": True,
            "ready": True,
            "pid": os.getpid(),
            "host": CLI_DAEMON_HOST,
            "port": CLI_DAEMON_PORT,
        }

    if request_type == "list_tools":
        tools = await runtime.list_tools()
        return {
            "ok": True,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.input_schema or {},
                }
                for tool in tools
            ],
        }

    if request_type == "call_tool":
        tool_name = message.get("tool")
        arguments = message.get("arguments") or {}
        if not isinstance(tool_name, str) or not tool_name:
            return {"ok": False, "error": "tool must be a non-empty string"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "arguments must be a JSON object"}
        text = await runtime.call_tool(tool_name, arguments)
        return {"ok": True, "text": text}

    if request_type == "shutdown":
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        return {"ok": True, "stopping": True}

    return {"ok": False, "error": f"unknown request type: {request_type}"}


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        raw = await reader.readline()
        if not raw:
            return
        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            response = {"ok": False, "error": f"invalid json: {exc}"}
        else:
            response = await _handle_request(message)
    except Exception as exc:
        LOGGER.exception("Ghost CLI daemon request failed")
        response = {"ok": False, "error": str(exc)}

    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def _shutdown(server: asyncio.AbstractServer | None) -> None:
    LOGGER.info("Stopping ghost CLI daemon")
    if server is not None:
        server.close()
        await server.wait_closed()
    await runtime._close_all_instance_browsers("ghost cli daemon stopped")
    await runtime._stop_playwright()


async def main() -> int:
    global _STOP_EVENT

    ensure_runtime_dirs()
    _write_pid_file()
    _STOP_EVENT = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _STOP_EVENT.set)
        except NotImplementedError:
            pass

    server = await asyncio.start_server(_handle_client, CLI_DAEMON_HOST, CLI_DAEMON_PORT)
    LOGGER.info(
        "Ghost CLI daemon listening on %s:%s pid=%s",
        CLI_DAEMON_HOST,
        CLI_DAEMON_PORT,
        os.getpid(),
    )

    try:
        await _STOP_EVENT.wait()
    finally:
        await _shutdown(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
