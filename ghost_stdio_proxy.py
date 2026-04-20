from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_ghost_dir = str(Path(__file__).resolve().parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

import mcp_server as runtime

INVALID_REQUEST = -32600
INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _jsonrpc_result(request_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False)


def _jsonrpc_error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


def _text_content(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _extract_text(contents: list[Any]) -> str:
    parts: list[str] = []
    for item in contents:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(part for part in parts if part).strip()


def _tool_payload(tool: Any) -> dict[str, Any]:
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", "") or "",
        "inputSchema": getattr(tool, "inputSchema", {}) or {},
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "ghost-cli-shim", "version": "0.2.0"},
    }


async def _handle_tools_list(request_id: Any) -> str:
    tools = await runtime.list_tools()
    payload = {"tools": [_tool_payload(tool) for tool in tools]}
    return _jsonrpc_result(request_id, payload)


async def _handle_tools_call(request_id: Any, params: dict[str, Any]) -> str:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return _jsonrpc_error(request_id, INVALID_PARAMS, "Tool name is required")
    if not isinstance(arguments, dict):
        return _jsonrpc_error(request_id, INVALID_PARAMS, "Tool arguments must be an object")

    try:
        text = _extract_text(await runtime.call_tool(name, arguments))
        return _jsonrpc_result(request_id, {"content": [_text_content(text)], "isError": False})
    except Exception as exc:
        return _jsonrpc_result(
            request_id,
            {"content": [_text_content(f"Ghost error: {exc}")], "isError": True},
        )


async def _shutdown_runtime() -> None:
    await runtime._close_all_instance_browsers("ghost stdio proxy exited")
    await runtime._stop_playwright()


async def _run() -> int:
    initialized = False
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                break

            raw = line.strip()
            if not raw:
                continue

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                print(_jsonrpc_error(None, INVALID_REQUEST, "Invalid JSON"), flush=True)
                continue

            request_id = message.get("id")
            method = message.get("method")
            params = message.get("params") or {}

            if method == "initialize":
                initialized = True
                print(_jsonrpc_result(request_id, _initialize_result()), flush=True)
                continue

            if method == "notifications/initialized":
                continue

            if method == "ping":
                print(_jsonrpc_result(request_id, {}), flush=True)
                continue

            if not initialized:
                print(_jsonrpc_error(request_id, INVALID_REQUEST, "Server not initialized"), flush=True)
                continue

            if method == "tools/list":
                print(await _handle_tools_list(request_id), flush=True)
                continue

            if method == "tools/call":
                print(await _handle_tools_call(request_id, params), flush=True)
                continue

            print(_jsonrpc_error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}"), flush=True)
    finally:
        await _shutdown_runtime()

    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
