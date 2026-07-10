from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

_ghost_dir = str(Path(__file__).resolve().parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

import runtime_host as runtime
from shared_runtime import (
    CLI_DAEMON_HOST,
    CLI_DAEMON_PID_FILE,
    CLI_DAEMON_PORT,
    CLI_DAEMON_STDERR_LOG_FILE,
    CLI_DAEMON_STDOUT_LOG_FILE,
    ensure_runtime_dirs,
    pid_exists,
    read_json,
)


_LIVE_PROXY_HEALTH_URL = "http://127.0.0.1:8766/health"
_LIVE_CONNECTION_MESSAGE = (
    "CONNECTION IS LIVE — reuse the existing Ghost session. "
    "Do not reconnect, start another Chrome MCP, or use Playwright."
)


def _tool_payload(tool) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema or {},
    }


async def _invoke_tool(name: str, arguments: dict[str, object] | None) -> str:
    return await runtime.call_tool(name, arguments or {})


async def _shutdown_runtime(reason: str) -> None:
    await runtime._close_all_instance_browsers(reason)
    await runtime._stop_playwright()


async def _daemon_request(payload: dict[str, object]) -> dict[str, object]:
    reader, writer = await asyncio.open_connection(CLI_DAEMON_HOST, CLI_DAEMON_PORT)
    try:
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        raw = await reader.readline()
        if not raw:
            raise RuntimeError("ghost daemon closed without a response")
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response, dict):
            raise RuntimeError("ghost daemon returned an invalid response")
        return response
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def _daemon_is_ready() -> bool:
    try:
        response = await _daemon_request({"type": "health"})
    except Exception:
        return False
    return bool(response.get("ok"))


async def _daemon_call_tool(name: str, arguments: dict[str, object]) -> str:
    response = await _daemon_request(
        {
            "type": "call_tool",
            "tool": name,
            "arguments": arguments,
        }
    )
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error", "ghost daemon call failed")))
    return str(response.get("text", ""))


def _read_live_proxy_health() -> dict[str, object]:
    try:
        with urllib.request.urlopen(_LIVE_PROXY_HEALTH_URL, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def _live_instance_is_ready(status: dict[str, object] | None) -> bool:
    return bool(
        status
        and status.get("transport") == "chrome-transport"
        and status.get("browser_connected") is True
        and status.get("cdp_url") == "live-chrome"
    )


async def _find_live_instance_status(instance_id: str) -> dict[str, object] | None:
    if not await _daemon_is_ready():
        return None
    instances_text = await _daemon_call_tool("ghost_instance_list", {})
    try:
        payload = json.loads(instances_text)
    except json.JSONDecodeError:
        return None
    for status in payload.get("instances", []) if isinstance(payload, dict) else []:
        if isinstance(status, dict) and status.get("instance_id") == instance_id:
            return status
    return None


def _live_payload(
    *,
    instance_id: str,
    proxy_health: dict[str, object],
    instance_status: dict[str, object] | None,
    reused_existing_connection: bool,
) -> dict[str, object]:
    broker_connected = proxy_health.get("connected") is True
    instance_ready = _live_instance_is_ready(instance_status)
    connection_live = broker_connected
    if connection_live:
        message = _LIVE_CONNECTION_MESSAGE
        action = (
            f"Reuse instance '{instance_id}' with ./ghost-cli call commands."
            if instance_ready
            else f"The broker is live; ./ghost-cli live-connect --instance-id {instance_id} will register the instance without reconnecting Chrome."
        )
    else:
        message = "Live Chrome is disconnected. Run ./ghost-cli live-connect once."
        action = f"./ghost-cli live-connect --instance-id {instance_id}"
    return {
        "ok": connection_live,
        "connection": "live" if connection_live else "disconnected",
        "message": message,
        "action": action,
        "next": (
            f"./ghost-cli call ghost_vacuum --arguments '{{\"instance_id\":\"{instance_id}\",\"limit\":20}}'"
            if instance_ready
            else action
        ),
        "should_reconnect": not broker_connected,
        "reused_existing_connection": reused_existing_connection,
        "instance_id": instance_id,
        "instance_ready": instance_ready,
        "backend": "chrome-devtools-mcp",
        "transport": "chrome-transport" if broker_connected else "disconnected",
        "browser_connected": broker_connected,
        "cdp_url": "live-chrome" if broker_connected else "none",
        "proxy_pid": proxy_health.get("pid"),
        "playwright_used": False,
    }


def _spawn_daemon() -> int:
    ensure_runtime_dirs()
    command = [sys.executable, str(Path(__file__).with_name("ghost_daemon.py"))]
    with open(CLI_DAEMON_STDOUT_LOG_FILE, "a", encoding="utf-8") as stdout_file, open(
        CLI_DAEMON_STDERR_LOG_FILE,
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


async def _ensure_daemon() -> None:
    if await _daemon_is_ready():
        return

    pid_payload = read_json(CLI_DAEMON_PID_FILE)
    pid = int(pid_payload.get("pid", 0)) if isinstance(pid_payload, dict) else 0
    if not pid_exists(pid):
        _spawn_daemon()

    deadline = asyncio.get_running_loop().time() + 20.0
    while asyncio.get_running_loop().time() < deadline:
        if await _daemon_is_ready():
            return
        await asyncio.sleep(0.25)

    raise RuntimeError(f"ghost daemon did not start on {CLI_DAEMON_HOST}:{CLI_DAEMON_PORT}")


async def _list_tools_payload() -> list[dict[str, object]]:
    tools = await runtime.list_tools()
    return [_tool_payload(tool) for tool in tools]


def _load_arguments(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Arguments payload must be a JSON object.")
    return parsed


def _response_payload(tool: str, text: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": not text.startswith("Error:") and not text.startswith("Ghost error:"),
        "tool": tool,
        "output": text,
    }
    try:
        payload["parsed"] = json.loads(text)
    except json.JSONDecodeError:
        pass
    return payload


def cmd_list_tools(_args) -> None:
    async def _run() -> None:
        payload = await _list_tools_payload()
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    asyncio.run(_run())


def cmd_call(args) -> None:
    async def _run() -> None:
        arguments = _load_arguments(args.arguments)
        # Inject CLI --headless into ghost_instance_create arguments
        if getattr(args, "headless", False) and args.tool_name == "ghost_instance_create":
            arguments["headless"] = True
        # Also respect GHOST_HEADLESS environment variable
        if os.environ.get("GHOST_HEADLESS", "").lower() in ("1", "true", "yes") and args.tool_name == "ghost_instance_create":
            arguments.setdefault("headless", True)
        if args.ephemeral:
            text = await _invoke_tool(args.tool_name, arguments)
        else:
            await _ensure_daemon()
            response = await _daemon_request(
                {
                    "type": "call_tool",
                    "tool": args.tool_name,
                    "arguments": arguments,
                }
            )
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error", "ghost daemon call failed")))
            text = str(response.get("text", ""))
        if args.json_output:
            print(json.dumps(_response_payload(args.tool_name, text), ensure_ascii=False))
        else:
            print(text)
        if args.ephemeral:
            await _shutdown_runtime("cli one-shot command completed")

    asyncio.run(_run())


def cmd_daemon_status(_args) -> None:
    async def _run() -> None:
        if await _daemon_is_ready():
            response = await _daemon_request({"type": "health"})
            print(json.dumps(response, ensure_ascii=False))
            return

        pid_payload = read_json(CLI_DAEMON_PID_FILE)
        print(
            json.dumps(
                {
                    "ok": False,
                    "ready": False,
                    "pid": (pid_payload or {}).get("pid") if isinstance(pid_payload, dict) else None,
                    "pid_file": str(CLI_DAEMON_PID_FILE),
                },
                ensure_ascii=False,
            )
        )

    asyncio.run(_run())


def cmd_daemon_stop(_args) -> None:
    async def _run() -> None:
        if not await _daemon_is_ready():
            print(json.dumps({"ok": True, "stopped": False, "reason": "daemon not running"}, ensure_ascii=False))
            return
        response = await _daemon_request({"type": "shutdown"})
        print(json.dumps(response, ensure_ascii=False))

    asyncio.run(_run())


def cmd_live_status(args) -> None:
    """Report the shared live-Chrome connection without creating or reconnecting it."""

    async def _run() -> bool:
        instance_id = str(args.instance_id or "live")
        proxy_health = await asyncio.to_thread(_read_live_proxy_health)
        status = await _find_live_instance_status(instance_id)
        payload = _live_payload(
            instance_id=instance_id,
            proxy_health=proxy_health,
            instance_status=status,
            reused_existing_connection=proxy_health.get("connected") is True,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return payload["connection"] == "live"

    if not asyncio.run(_run()):
        raise SystemExit(1)


def cmd_live_connect(args) -> None:
    """Attach the canonical Ghost instance to the user's already-open Chrome."""

    async def _run() -> None:
        instance_id = str(args.instance_id or "live")
        proxy_health = await asyncio.to_thread(_read_live_proxy_health)
        broker_was_live = proxy_health.get("connected") is True

        if broker_was_live:
            existing_status = await _find_live_instance_status(instance_id)
            if _live_instance_is_ready(existing_status):
                print(
                    json.dumps(
                        _live_payload(
                            instance_id=instance_id,
                            proxy_health=proxy_health,
                            instance_status=existing_status,
                            reused_existing_connection=True,
                        ),
                        ensure_ascii=False,
                    )
                )
                return

        await _ensure_daemon()

        await _daemon_call_tool(
            "ghost_instance_create",
            {
                "instance_id": instance_id,
                "cdp_url": "live-chrome",
            },
        )
        status_text = await _daemon_call_tool(
            "ghost_status",
            {"instance_id": instance_id},
        )
        try:
            status = json.loads(status_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ghost returned invalid live status: {status_text}") from exc

        transport = status.get("transport")
        connected = status.get("browser_connected") is True
        cdp_url = status.get("cdp_url")
        if transport != "chrome-transport" or not connected or cdp_url != "live-chrome":
            raise RuntimeError(
                "Live Chrome attachment failed strict validation: expected "
                "transport=chrome-transport, browser_connected=true, cdp_url=live-chrome; "
                f"got transport={transport}, browser_connected={status.get('browser_connected')}, "
                f"cdp_url={cdp_url}. Ghost will not fall back to Playwright."
            )

        proxy_health = await asyncio.to_thread(_read_live_proxy_health)
        print(
            json.dumps(
                {
                    **_live_payload(
                        instance_id=instance_id,
                        proxy_health=proxy_health,
                        instance_status=status,
                        reused_existing_connection=broker_was_live,
                    ),
                },
                ensure_ascii=False,
            )
        )

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "command": "live-connect",
                    "error": str(exc),
                    "playwright_fallback": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


def cmd_repl(_args) -> None:
    async def _run() -> None:
        tools = await _list_tools_payload()
        tool_names = [tool["name"] for tool in tools]
        print(json.dumps({"ok": True, "ready": True, "tools": tool_names}, ensure_ascii=False))
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                break

            raw = line.strip()
            if not raw:
                continue
            if raw.lower() in {"exit", "quit"}:
                break
            if raw.lower() == "help":
                print(json.dumps({"ok": True, "tools": tools}, ensure_ascii=False))
                continue

            try:
                if raw.startswith("{"):
                    command = json.loads(raw)
                    if not isinstance(command, dict):
                        raise ValueError("Command must be a JSON object.")
                    tool_name = command.get("tool")
                    arguments = command.get("arguments") or {}
                else:
                    parts = raw.split(maxsplit=1)
                    tool_name = parts[0]
                    arguments = _load_arguments(parts[1] if len(parts) > 1 else None)

                if not isinstance(tool_name, str) or not tool_name:
                    raise ValueError("Command must include a non-empty tool name.")
                if not isinstance(arguments, dict):
                    raise ValueError("Command arguments must be a JSON object.")

                text = await _invoke_tool(tool_name, arguments)
                print(json.dumps(_response_payload(tool_name, text), ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))

        await _shutdown_runtime("ghost cli repl exited")

    asyncio.run(_run())


def cmd_batch(args) -> None:
    """Batch extraction: navigate to N URLs and extract data from each."""
    async def _run() -> None:
        from helpers.extractors import get_recipe

        # Load queries
        queries_raw = args.queries
        if os.path.isfile(queries_raw):
            with open(queries_raw) as f:
                queries = json.load(f)
        else:
            queries = json.loads(queries_raw)

        if not isinstance(queries, list):
            print(json.dumps({"ok": False, "error": "Queries must be a JSON array"}, ensure_ascii=False))
            return

        await _ensure_daemon()
        instance_id = args.instance_id or "batch"
        delay = args.delay
        max_items = args.max_items

        # Ensure instance exists
        await _daemon_request({
            "type": "call_tool",
            "tool": "ghost_instance_create",
            "arguments": {"instance_id": instance_id},
        })

        results = {}
        total = len(queries)
        for i, entry in enumerate(queries):
            label = entry.get("label", entry.get("company", f"query_{i}"))
            url = entry.get("url", "")
            recipe = entry.get("recipe", args.recipe)
            script = entry.get("script")

            if not url:
                results[label] = {"error": "no URL provided"}
                continue

            print(f"[{i+1}/{total}] {label}: {url}", file=sys.stderr)

            # Navigate
            await _daemon_request({
                "type": "call_tool",
                "tool": "ghost_eval",
                "arguments": {
                    "instance_id": instance_id,
                    "script": f'() => {{ location.href = "{url}"; return "navigating"; }}',
                },
            })

            # Wait for page load
            await asyncio.sleep(delay)

            # Extract -- recipes are IIFEs that return formatted text,
            # custom scripts are arrow functions that need to be called.
            if recipe:
                js_code = get_recipe(recipe, max_items)
                eval_script = f"() => ({js_code})"
            elif script:
                js_code = script
                eval_script = f"() => ({js_code})()"
            else:
                eval_script = "() => document.title"

            response = await _daemon_request({
                "type": "call_tool",
                "tool": "ghost_eval",
                "arguments": {
                    "instance_id": instance_id,
                    "script": eval_script,
                },
            })

            raw = str(response.get("text", ""))
            results[label] = {"url": url, "output": raw}
            line_count = len(raw.strip().split('\n'))
            print(f"  -> {line_count} lines extracted", file=sys.stderr)

            # Rate limit
            if i < total - 1:
                await asyncio.sleep(1)  # small extra delay between navigations

        # Output
        output_json = json.dumps(results, indent=2, ensure_ascii=False)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output_json)
            print(f"\nResults written to {args.output}", file=sys.stderr)
        else:
            print(output_json)

    asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghost-cli",
        description="Ghost Browser direct CLI runtime.",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list-tools", help="List the Ghost tool surface exposed by the CLI runtime.")
    p_list.set_defaults(func=cmd_list_tools)

    p_call = sub.add_parser("call", help="Call one Ghost tool once.")
    p_call.add_argument("tool_name", help="Ghost tool name, e.g. ghost_vacuum.")
    p_call.add_argument(
        "--arguments",
        default="{}",
        help="JSON object of tool arguments.",
    )
    p_call.add_argument(
        "--json-output",
        action="store_true",
        help="Wrap the response in a JSON envelope.",
    )
    p_call.add_argument(
        "--ephemeral",
        action="store_true",
        help="Run the tool in a throwaway process instead of the persistent local daemon.",
    )
    p_call.add_argument(
        "--headless",
        action="store_true",
        help="Launch browser in headless mode (no visible window). Only affects ghost_instance_create.",
    )
    p_call.set_defaults(func=cmd_call)

    p_repl = sub.add_parser("repl", help="Run a long-lived JSON-line Ghost CLI session.")
    p_repl.set_defaults(func=cmd_repl)

    p_daemon_status = sub.add_parser("daemon-status", help="Show whether the persistent Ghost CLI daemon is running.")
    p_daemon_status.set_defaults(func=cmd_daemon_status)

    p_daemon_stop = sub.add_parser("daemon-stop", help="Ask the persistent Ghost CLI daemon to shut down cleanly.")
    p_daemon_stop.set_defaults(func=cmd_daemon_stop)

    p_live_status = sub.add_parser(
        "live-status",
        help="Read the shared live-Chrome state without creating or reconnecting anything.",
    )
    p_live_status.add_argument(
        "--instance-id",
        default="live",
        help="Named Ghost instance to inspect (default: live).",
    )
    p_live_status.set_defaults(func=cmd_live_status)

    p_live_connect = sub.add_parser(
        "live-connect",
        help="Attach to the already-open Chrome through the shared Chrome MCP broker (never Playwright).",
    )
    p_live_connect.add_argument(
        "--instance-id",
        default="live",
        help="Named Ghost instance to create or reuse (default: live).",
    )
    p_live_connect.set_defaults(func=cmd_live_connect)

    p_batch = sub.add_parser("batch", help="Batch extract data from multiple URLs.")
    p_batch.add_argument("--queries", required=True, help="JSON file or inline JSON array of {url, recipe?, script?, label?}")
    p_batch.add_argument("--recipe", default=None, help="Default recipe to use for all URLs (e.g. 'linkedin_search')")
    p_batch.add_argument("--output", "-o", default=None, help="Output JSON file path")
    p_batch.add_argument("--delay", type=int, default=4, help="Seconds between navigations (default: 4)")
    p_batch.add_argument("--max-items", type=int, default=10, help="Max items per extraction (default: 10)")
    p_batch.add_argument("--instance-id", default=None, help="Ghost instance to use (default: 'batch')")
    p_batch.set_defaults(func=cmd_batch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
