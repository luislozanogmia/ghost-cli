from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import AsyncExitStack, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

_ghost_dir = str(Path(__file__).resolve().parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

from ghost_tool_defs import get_ghost_tools
from shared_runtime import (
    DAEMON_PID_FILE,
    DAEMON_STDERR_LOG_FILE,
    DAEMON_STDOUT_LOG_FILE,
    GHOST_SHARED_HOST,
    GHOST_SHARED_HTTP_PATH,
    GHOST_SHARED_PORT,
    GHOST_SHARED_URL,
    PROXY_LOG_FILE,
    ensure_runtime_dirs,
    pid_exists,
    read_json,
    setup_logging,
)


LOGGER = setup_logging("ghost.stdio_proxy", PROXY_LOG_FILE)

_backend_lock = asyncio.Lock()
_backend_stack: Optional[AsyncExitStack] = None
_backend_session: Optional[ClientSession] = None
_backend_session_id: Optional[str] = None
_initialized = False
_parent_pid = os.getppid()


def _start_parent_watchdog() -> None:
    def _watch_parent() -> None:
        while True:
            current_parent = os.getppid()
            if current_parent in (0, 1) or current_parent != _parent_pid:
                LOGGER.info("Parent process changed or exited, shutting down Ghost stdio proxy")
                os._exit(0)
            time.sleep(2)

    threading.Thread(target=_watch_parent, name="ghost-parent-watchdog", daemon=True).start()


def _install_exception_logging() -> None:
    def _log_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        LOGGER.exception("Ghost stdio proxy crashed", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = _log_exception


def _server_version() -> str:
    try:
        from importlib.metadata import version

        return version("mcp")
    except Exception:
        return "unknown"


def _write_daemon_pid_file(pid: int) -> None:
    ensure_runtime_dirs()
    payload = {
        "pid": pid,
        "url": GHOST_SHARED_URL,
        "host": GHOST_SHARED_HOST,
        "port": GHOST_SHARED_PORT,
        "http_path": GHOST_SHARED_HTTP_PATH,
        "started_at": datetime.now().isoformat(),
    }
    DAEMON_PID_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _get_live_daemon_pid() -> int:
    daemon_info = read_json(DAEMON_PID_FILE) or {}
    daemon_pid = int(daemon_info.get("pid", 0) or 0)
    if daemon_pid > 0 and pid_exists(daemon_pid):
        return daemon_pid

    if daemon_pid > 0:
        with suppress(FileNotFoundError):
            DAEMON_PID_FILE.unlink()
        LOGGER.info("Removed stale Ghost daemon pid file for pid=%s", daemon_pid)

    return 0


def _spawn_shared_daemon() -> int:
    ensure_runtime_dirs()

    command = [
        sys.executable,
        str(Path(__file__).with_name("mcp_server.py")),
        "--transport",
        "streamable-http",
        "--host",
        GHOST_SHARED_HOST,
        "--port",
        str(GHOST_SHARED_PORT),
        "--http-path",
        GHOST_SHARED_HTTP_PATH,
    ]

    if sys.platform == "win32":
        command_line = subprocess.list2cmdline(command).replace("'", "''")
        current_directory = str(Path(__file__).resolve().parent).replace("'", "''")
        powershell_script = (
            f"$cmd = '{command_line}'; "
            f"$cwd = '{current_directory}'; "
            "$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            "-Arguments @{CommandLine=$cmd; CurrentDirectory=$cwd}; "
            "$result | Select-Object ProcessId, ReturnValue | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                powershell_script,
            ],
            capture_output=True,
            text=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = json.loads(completed.stdout.strip())
        if int(payload.get("ReturnValue", 1)) != 0:
            raise RuntimeError(f"Win32_Process.Create failed: {completed.stdout.strip()}")
        daemon_pid = int(payload["ProcessId"])
        _write_daemon_pid_file(daemon_pid)
        LOGGER.info("Started shared Ghost daemon via Win32_Process.Create pid=%s url=%s", daemon_pid, GHOST_SHARED_URL)
        return daemon_pid

    breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    creationflags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | breakaway_flag
    )

    with open(DAEMON_STDOUT_LOG_FILE, "a", encoding="utf-8") as stdout_file, open(
        DAEMON_STDERR_LOG_FILE,
        "a",
        encoding="utf-8",
    ) as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creationflags,
            )
        except OSError:
            if not breakaway_flag:
                raise
            LOGGER.warning("Ghost daemon breakaway spawn failed; retrying without CREATE_BREAKAWAY_FROM_JOB")
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creationflags & ~breakaway_flag,
            )

    _write_daemon_pid_file(process.pid)
    LOGGER.info("Started shared Ghost daemon pid=%s url=%s", process.pid, GHOST_SHARED_URL)
    return process.pid


async def _wait_for_daemon_listener(timeout_seconds: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error: OSError | None = None

    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection(GHOST_SHARED_HOST, GHOST_SHARED_PORT)
            writer.close()
            await writer.wait_closed()
            return
        except OSError as exc:
            last_error = exc
            await asyncio.sleep(0.25)

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(
        f"Ghost shared backend did not start listening on {GHOST_SHARED_HOST}:{GHOST_SHARED_PORT}{detail}"
    )


async def _daemon_listener_is_ready() -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(GHOST_SHARED_HOST, GHOST_SHARED_PORT),
            timeout=0.5,
        )
    except (OSError, TimeoutError):
        return False

    writer.close()
    await writer.wait_closed()
    return True


async def _open_backend_session() -> tuple[AsyncExitStack, ClientSession, str]:
    stack = AsyncExitStack()
    try:
        read_stream, write_stream, get_session_id = await stack.enter_async_context(
            streamable_http_client(GHOST_SHARED_URL, terminate_on_close=False)
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        session_id = get_session_id()
        if not session_id:
            raise RuntimeError("Ghost backend did not return an MCP session ID")
        LOGGER.info("Opened Ghost backend session %s", session_id)
        return stack, session, session_id
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        with suppress(BaseException):
            await stack.aclose()
        raise RuntimeError(f"Failed to open Ghost backend session: {exc}") from exc


async def _close_backend_session() -> None:
    global _backend_stack, _backend_session, _backend_session_id

    stack = _backend_stack
    session_id = _backend_session_id
    _backend_stack = None
    _backend_session = None
    _backend_session_id = None

    if session_id is not None:
        try:
            LOGGER.info("Terminating Ghost backend session %s", session_id)
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.delete(
                    GHOST_SHARED_URL,
                    headers={"mcp-session-id": session_id},
                )
            LOGGER.info("Terminated Ghost backend session %s", session_id)
        except Exception:
            LOGGER.exception("Failed to terminate backend session %s cleanly", session_id)

    if stack is not None:
        try:
            await stack.aclose()
        except Exception:
            LOGGER.exception("Failed to close backend session resources")


async def _ensure_backend_session() -> ClientSession:
    global _backend_stack, _backend_session, _backend_session_id

    async with _backend_lock:
        if _backend_session is not None:
            return _backend_session

        daemon_pid = _get_live_daemon_pid()
        if await _daemon_listener_is_ready():
            if daemon_pid > 0:
                LOGGER.info("Reusing shared Ghost daemon pid=%s", daemon_pid)
            else:
                LOGGER.info("Reusing existing Ghost listener at %s", GHOST_SHARED_URL)
        else:
            if daemon_pid > 0:
                LOGGER.info("Waiting for existing shared Ghost daemon pid=%s", daemon_pid)
            else:
                daemon_pid = _spawn_shared_daemon()
            await _wait_for_daemon_listener(20.0)

        deadline = asyncio.get_running_loop().time() + 20.0
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                stack, session, session_id = await _open_backend_session()
                _backend_stack = stack
                _backend_session = session
                _backend_session_id = session_id
                return session
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.5)

        detail = str(last_error) if last_error is not None else "unknown error"
        raise RuntimeError(
            f"Ghost shared backend did not become ready for pid={daemon_pid}: {detail}"
        ) from last_error


def _write_response(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": str(types.LATEST_PROTOCOL_VERSION),
        "capabilities": {
            "experimental": {},
            "tools": {"listChanged": False},
        },
        "serverInfo": {
            "name": "ghost",
            "version": _server_version(),
        },
    }


def _tools_list_result() -> dict[str, Any]:
    return {
        "tools": [
            tool.model_dump(by_alias=True, exclude_none=True)
            for tool in get_ghost_tools()
        ]
    }


async def _handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    global _initialized

    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        _initialized = True
        return _jsonrpc_result(request_id, _initialize_result())

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if not _initialized:
        return _jsonrpc_error(request_id, types.INVALID_REQUEST, "Server not initialized")

    if method == "tools/list":
        return _jsonrpc_result(request_id, _tools_list_result())

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _jsonrpc_error(request_id, types.INVALID_PARAMS, "Tool name is required")

        LOGGER.info("Forwarding Ghost tool call %s", name)
        try:
            session = await _ensure_backend_session()
            result = await session.call_tool(name, arguments)
            LOGGER.info("Completed Ghost tool call %s", name)
            return _jsonrpc_result(
                request_id,
                result.model_dump(by_alias=True, exclude_none=True),
            )
        except Exception as exc:
            LOGGER.exception("Ghost backend tool call failed for %s", name)
            await _close_backend_session()
            error_result = types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Ghost backend connection failed during '{name}': {exc}. Retry the tool call.",
                    )
                ],
                isError=True,
            )
            return _jsonrpc_result(
                request_id,
                error_result.model_dump(by_alias=True, exclude_none=True),
            )

    return _jsonrpc_error(request_id, types.METHOD_NOT_FOUND, f"Method not found: {method}")


async def main() -> None:
    _install_exception_logging()
    _start_parent_watchdog()
    LOGGER.info("Starting Ghost stdio proxy for %s", GHOST_SHARED_URL)
    try:
        while True:
            raw_line = await asyncio.to_thread(sys.stdin.readline)
            if raw_line == "":
                break

            line = raw_line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                _write_response(_jsonrpc_error(None, types.PARSE_ERROR, f"Parse error: {exc}"))
                continue

            response = await _handle_request(message)
            if response is not None:
                _write_response(response)
    finally:
        await _close_backend_session()
        LOGGER.info("Ghost stdio proxy exiting")


if __name__ == "__main__":
    asyncio.run(main())
