from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from itertools import count
from pathlib import Path
from typing import Any


class ToolProcessError(RuntimeError):
    pass


def extract_text_content(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(part for part in parts if part).strip()


class ToolProcessClient:
    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._ids = count(1)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        process_group_args: dict[str, Any] = {}
        if os.name == "nt":
            process_group_args["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            # Keep the MCP subprocess and its npm/node descendants out of the
            # Ghost daemon's process group so failed starts can be reaped as one
            # unit without terminating Ghost itself.
            process_group_args["start_new_session"] = True
        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            cwd=str(self.cwd) if self.cwd is not None else None,
            env=self.env or os.environ.copy(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_group_args,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def initialize(self) -> dict[str, Any]:
        await self.start()
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ghost-cli", "version": "0.2.0"},
            },
        )
        await self.notify("notifications/initialized", {})
        if not isinstance(result, dict):
            raise ToolProcessError("Invalid initialize result from tool process.")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.request("tools/list", {})
        if not isinstance(result, dict):
            raise ToolProcessError("Invalid tools/list result from tool process.")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ToolProcessError("Tool process returned malformed tool list.")
        return [tool for tool in tools if isinstance(tool, dict)]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float = 60.0,
    ) -> str:
        result = await self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(result, dict):
            raise ToolProcessError("Invalid tools/call result from tool process.")
        if result.get("isError"):
            message = extract_text_content(result) or "Tool call failed."
            raise ToolProcessError(message)
        return extract_text_content(result)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> Any:
        await self.start()
        if self._proc is None or self._proc.stdin is None:
            raise ToolProcessError("Tool process is not running.")

        request_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        try:
            await self._write_message(message)
            return await asyncio.wait_for(future, timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ToolProcessError(f"Timed out waiting for {method}.") from exc

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self.start()
        await self._write_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        )

    async def _write_message(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise ToolProcessError("Tool process stdin is unavailable.")
        # MCP stdio uses one JSON-RPC message per line. The old LSP-style
        # Content-Length framing is ignored by current chrome-devtools-mcp and
        # leaves initialization hanging forever.
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self._proc.stdin.write(raw)
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                message = await self._read_message()
                if message is None:
                    break

                request_id = message.get("id")
                if request_id is None:
                    continue

                future = self._pending.pop(request_id, None)
                if future is None or future.done():
                    continue

                if "error" in message:
                    error = message["error"]
                    if isinstance(error, dict):
                        future.set_exception(ToolProcessError(str(error.get("message", error))))
                    else:
                        future.set_exception(ToolProcessError(str(error)))
                else:
                    future.set_result(message.get("result"))
        except Exception as exc:
            self._fail_pending(exc)
        finally:
            self._fail_pending(ToolProcessError("Tool process disconnected."))

    async def _read_message(self) -> dict[str, Any] | None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return None
            decoded = line.decode("utf-8").strip()
            if not decoded:
                continue
            return json.loads(decoded)

    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return

    def _fail_pending(self, exc: BaseException) -> None:
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending.pop(request_id, None)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

        if self._proc is not None:
            proc = self._proc
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            if proc.returncode is None:
                if os.name == "nt":
                    proc.terminate()
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    await asyncio.wait_for(proc.wait(), 5.0)
                except asyncio.TimeoutError:
                    if os.name == "nt":
                        proc.kill()
                    else:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    await proc.wait()

        self._proc = None
        self._reader_task = None
        self._stderr_task = None
