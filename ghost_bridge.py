#!/usr/bin/env python3
"""ghost_bridge.py — legacy bridge for older Ghost server clients.

Connects to the running Ghost shared runtime and calls a tool.
Can be used from any environment (WSL2, native, subprocess) via run_command.

This path is retained only for compatibility and is not the supported way to
run Ghost.

Usage:
    python ghost_bridge.py vacuum [--url URL] [--limit N]
    python ghost_bridge.py click --choice N [--value TEXT]
    python ghost_bridge.py more [--offset N]
    python ghost_bridge.py screenshot [--element N] [--full-page]
    python ghost_bridge.py status
    python ghost_bridge.py save_auth
    python ghost_bridge.py instance_list
    python ghost_bridge.py instance_create --name NAME [--url URL]
    python ghost_bridge.py instance_close --id ID

Examples:
    python ghost_bridge.py vacuum --url "https://www.linkedin.com/feed/"
    python ghost_bridge.py click --choice 3 --value "search query"
    python ghost_bridge.py screenshot
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path

# Force UTF-8 stdout to avoid charmap codec errors when piped through WSL
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_ghost_dir = str(Path(__file__).resolve().parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

from shared_runtime import (
    DAEMON_STDERR_LOG_FILE,
    DAEMON_STDOUT_LOG_FILE,
    GHOST_SHARED_HOST,
    GHOST_SHARED_HTTP_PATH,
    GHOST_SHARED_PORT,
    GHOST_SHARED_URL,
    ensure_runtime_dirs,
)


async def _shared_daemon_is_ready() -> bool:
    try:
        reader, writer = await asyncio.open_connection(GHOST_SHARED_HOST, GHOST_SHARED_PORT)
    except OSError:
        return False

    writer.close()
    await writer.wait_closed()
    return True


def _spawn_shared_daemon() -> int:
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

    with open(DAEMON_STDOUT_LOG_FILE, "a", encoding="utf-8") as stdout_file, open(
        DAEMON_STDERR_LOG_FILE,
        "a",
        encoding="utf-8",
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parent),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
    return process.pid


async def _ensure_shared_daemon() -> None:
    if await _shared_daemon_is_ready():
        return

    _spawn_shared_daemon()
    deadline = asyncio.get_running_loop().time() + 20.0
    while asyncio.get_running_loop().time() < deadline:
        if await _shared_daemon_is_ready():
            return
        await asyncio.sleep(0.25)

    raise RuntimeError(f"Ghost shared backend did not start on {GHOST_SHARED_HOST}:{GHOST_SHARED_PORT}")


async def call_ghost_tool(tool_name: str, arguments: dict) -> str:
    """Connect to Ghost daemon and call a tool, return text result."""
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    ensure_runtime_dirs()
    await _ensure_shared_daemon()

    async with AsyncExitStack() as stack:
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(GHOST_SHARED_URL)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        result = await session.call_tool(tool_name, arguments)

        # Extract text from result
        texts = []
        for content in result.content:
            if hasattr(content, "text"):
                texts.append(content.text)
            elif hasattr(content, "data"):
                texts.append(f"[image: {len(content.data)} bytes]")
        return "\n".join(texts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ghost legacy server bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    # vacuum
    p = sub.add_parser("vacuum", help="Vacuum a page (extract text)")
    p.add_argument("--url", help="URL to navigate to")
    p.add_argument("--limit", type=int, help="Max items to return")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # click
    p = sub.add_parser("click", help="Click an element from vacuum output")
    p.add_argument("--choice", type=int, required=True, help="Element number to click")
    p.add_argument("--value", help="Text to type after clicking (for inputs)")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # more
    p = sub.add_parser("more", help="Get next page of vacuum results")
    p.add_argument("--offset", type=int, help="Start offset")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # screenshot
    p = sub.add_parser("screenshot", help="Take a screenshot")
    p.add_argument("--element", type=int, help="Element number to screenshot")
    p.add_argument("--full-page", action="store_true", help="Full page screenshot")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # page_text
    p = sub.add_parser("page_text", help="Extract all visible text from page")
    p.add_argument("--max-length", type=int, default=5000, help="Max characters to return")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # status
    p = sub.add_parser("status", help="Get Ghost status")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # save_auth
    p = sub.add_parser("save_auth", help="Save browser auth cookies")
    p.add_argument("--instance-id", help="Ghost instance ID")

    # instance management
    p = sub.add_parser("instance_list", help="List Ghost instances")
    p = sub.add_parser("instance_create", help="Create a named Ghost instance")
    p.add_argument("--name", required=True, help="Instance name")
    p.add_argument("--url", help="Initial URL to navigate to")
    p = sub.add_parser("instance_close", help="Close a Ghost instance")
    p.add_argument("--id", required=True, help="Instance ID to close")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Map command to Ghost tool name and arguments
    tool_map = {
        "vacuum": ("ghost_vacuum", lambda a: {
            k: v for k, v in {
                "url": a.url, "limit": a.limit, "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "click": ("ghost_click", lambda a: {
            k: v for k, v in {
                "choice": a.choice, "value": a.value, "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "more": ("ghost_more", lambda a: {
            k: v for k, v in {
                "offset": a.offset, "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "screenshot": ("ghost_screenshot", lambda a: {
            k: v for k, v in {
                "element": a.element,
                "full_page": a.full_page if a.full_page else None,
                "instance_id": getattr(a, "instance_id", None),
            }.items() if v is not None
        }),
        "page_text": ("ghost_page_text", lambda a: {
            k: v for k, v in {
                "max_length": a.max_length, "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "status": ("ghost_status", lambda a: {
            k: v for k, v in {
                "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "save_auth": ("ghost_save_auth", lambda a: {
            k: v for k, v in {
                "instance_id": getattr(a, "instance_id", None)
            }.items() if v is not None
        }),
        "instance_list": ("ghost_instance_list", lambda a: {}),
        "instance_create": ("ghost_instance_create", lambda a: {
            k: v for k, v in {
                "name": a.name, "url": a.url
            }.items() if v is not None
        }),
        "instance_close": ("ghost_instance_close", lambda a: {"instance_id": a.id}),
    }

    tool_name, args_fn = tool_map[args.command]
    arguments = args_fn(args)

    try:
        result = asyncio.run(call_ghost_tool(tool_name, arguments))
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
