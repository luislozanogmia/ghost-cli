from __future__ import annotations

import asyncio
import concurrent.futures
import os
import queue
import re
import socket
import subprocess
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


_PAGE_LINE_RE = re.compile(r"^\s*(\d+):\s+(.*?)(\s+\[selected\])?\s*$")
_PROXY_URL = "http://127.0.0.1:8766"
_PROXY_SCRIPT = Path(__file__).parent / "ghost_chrome_proxy.py"
# Resolve venv python cross-platform (Scripts/ on Windows, bin/ on mac/linux)
_VENV_ROOT = Path(__file__).resolve().parent / ".venv"
_PROXY_PYTHON = (
    _VENV_ROOT / "Scripts" / "python.exe"
    if (_VENV_ROOT / "Scripts" / "python.exe").exists()
    else _VENV_ROOT / "bin" / "python"
)
_DEFAULT_CHROME_PATHS = (
    # macOS
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path(os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
    # Windows
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")) / "Google/Chrome/Application/chrome.exe",
)


def _tool_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def _parse_pages(text: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _PAGE_LINE_RE.match(line)
        if not match:
            continue
        pages.append(
            {
                "pageId": int(match.group(1)),
                "url": match.group(2).strip(),
                "selected": bool(match.group(3)),
            }
        )
    return pages


def _normalize_page_url(url: Optional[str]) -> str:
    if not url:
        return ""
    normalized = str(url).strip()
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _resolve_chrome_path() -> str:
    for candidate in _DEFAULT_CHROME_PATHS:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Could not locate chrome.exe for Chrome MCP transport.")


@dataclass
class ChromeMcpRuntime:
    instance_id: str
    context_dir: Path
    browser_url: Optional[str] = None
    auto_connect: bool = False
    logger: Any = None
    _page_id: Optional[int] = None
    _browser_process: Optional[subprocess.Popen] = None
    _browser_debug_port: Optional[int] = None
    _worker_thread: Optional[threading.Thread] = None
    _command_queue: Optional[queue.Queue] = None
    _worker_ready: Optional[threading.Event] = None
    _worker_error: Optional[BaseException] = None

    @property
    def connected(self) -> bool:
        if self.auto_connect:
            return True
        if self.browser_url:
            return True
        return self._browser_process is not None and self._browser_process.poll() is None

    def _log(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    async def _wait_for_browser_port(self, timeout_seconds: float = 15.0) -> None:
        if not self._browser_debug_port:
            return
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", self._browser_debug_port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.25)
        raise RuntimeError(f"Chrome debug port {self._browser_debug_port} did not come up in time.")

    async def _ensure_proxy_running(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{_PROXY_URL}/health", timeout=3.0)
                if resp.status_code == 200:
                    return
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        self._log("Starting Ghost Chrome Proxy...")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        subprocess.Popen(
            [str(_PROXY_PYTHON), str(_PROXY_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(30):
            await asyncio.sleep(0.5)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{_PROXY_URL}/health", timeout=2.0)
                    if resp.status_code == 200:
                        self._log("Ghost Chrome Proxy is ready")
                        return
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
        raise RuntimeError("Ghost Chrome Proxy did not start in time")

    async def ensure_browser(self) -> None:
        if self.auto_connect:
            await self._ensure_proxy_running()
            return
        if self.browser_url:
            return
        if self._browser_process is not None and self._browser_process.poll() is None:
            return

        self.context_dir.mkdir(parents=True, exist_ok=True)
        self._browser_debug_port = _find_free_port()
        chrome_path = _resolve_chrome_path()
        command = [
            chrome_path,
            f"--remote-debugging-port={self._browser_debug_port}",
            f"--user-data-dir={self.context_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self._browser_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.browser_url = f"http://127.0.0.1:{self._browser_debug_port}"
        self._log(
            "Chrome MCP browser launched instance=%s pid=%s browser_url=%s",
            self.instance_id,
            self._browser_process.pid,
            self.browser_url,
        )
        await self._wait_for_browser_port()

    def _server_parameters(self) -> StdioServerParameters:
        if os.name == "nt":
            base_args = ["/c", "npx", "-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]
            command = "cmd"
        else:
            base_args = ["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]
            command = "npx"
        if self.browser_url:
            base_args.extend(["--browserUrl", self.browser_url])
        elif self.auto_connect:
            base_args.extend(["--autoConnect", "--channel=stable"])
        else:
            raise RuntimeError("Chrome MCP runtime has no browser target configured.")
        return StdioServerParameters(command=command, args=base_args)

    def _thread_main(self) -> None:
        try:
            import anyio

            anyio.run(self._async_thread_main)
        except BaseException as exc:  # pragma: no cover - startup/runtime propagation
            self._worker_error = exc
            if self._worker_ready is not None:
                self._worker_ready.set()

    async def _async_thread_main(self) -> None:
        import anyio

        assert self._command_queue is not None
        assert self._worker_ready is not None

        async with stdio_client(self._server_parameters()) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._worker_ready.set()
                while True:
                    operation, payload, future = await anyio.to_thread.run_sync(self._command_queue.get)
                    if operation == "stop":
                        future.set_result(None)
                        break
                    try:
                        result = await session.call_tool(
                            payload["name"],
                            payload.get("arguments") or {},
                            read_timeout_seconds=timedelta(seconds=payload.get("timeout_seconds", 60.0)),
                        )
                        future.set_result(_tool_text(result))
                    except BaseException as exc:  # pragma: no cover - delegated from MCP session
                        future.set_exception(exc)

    async def _ensure_worker(self) -> None:
        if self.auto_connect:
            await self._ensure_proxy_running()
            return
        await self.ensure_browser()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._worker_error = None
        self._command_queue = queue.Queue()
        self._worker_ready = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._thread_main,
            name=f"ghost-chrome-mcp-{self.instance_id}",
            daemon=True,
        )
        self._worker_thread.start()
        await asyncio.to_thread(self._worker_ready.wait, 30.0)
        if self._worker_error is not None:
            raise RuntimeError(f"Chrome MCP worker failed to start: {self._worker_error}") from self._worker_error
        if not self._worker_ready.is_set():
            raise RuntimeError("Chrome MCP worker did not become ready in time.")

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
        *,
        timeout_seconds: float = 60.0,
    ) -> str:
        if self.auto_connect:
            await self._ensure_proxy_running()
            payload: dict[str, Any] = {"name": name, "arguments": arguments or {}, "timeout": timeout_seconds}
            if self._page_id is not None:
                payload["page_id"] = self._page_id
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{_PROXY_URL}/call",
                    json=payload,
                    timeout=timeout_seconds + 5,
                )
                data = resp.json()
                if data.get("error"):
                    raise RuntimeError(data["error"])
                return data.get("result") or ""
        await self._ensure_worker()
        assert self._command_queue is not None
        future: concurrent.futures.Future[str] = concurrent.futures.Future()
        self._command_queue.put(
            (
                "tool",
                {
                    "name": name,
                    "arguments": arguments or {},
                    "timeout_seconds": timeout_seconds,
                },
                future,
            )
        )
        return await asyncio.wrap_future(future)

    async def list_pages(self) -> list[dict[str, Any]]:
        text = await self.call_tool("list_pages", {}, timeout_seconds=20.0)
        pages = _parse_pages(text)
        if self._page_id is not None and not any(page["pageId"] == self._page_id for page in pages):
            self._page_id = None
        return pages

    async def create_tab(self, url: Optional[str] = None) -> dict[str, Any]:
        """Open a new Chrome tab and pin this runtime instance to it."""
        target_url = url or "about:blank"
        text = await self.call_tool(
            "new_page",
            {"url": target_url, "background": False, "timeout": 15000},
            timeout_seconds=30.0,
        )
        pages = _parse_pages(text) or await self.list_pages()
        page = next((p for p in pages if p.get("selected")), None) or (pages[-1] if pages else None)
        if page is None:
            raise RuntimeError("Failed to open new Chrome tab")
        self._page_id = page["pageId"]
        return page

    async def _select_page(self, page_id: int) -> None:
        await self.call_tool("select_page", {"pageId": page_id, "bringToFront": True}, timeout_seconds=20.0)
        self._page_id = page_id

    async def ensure_page(self, url: Optional[str] = None) -> dict[str, Any]:
        pages = await self.list_pages()
        normalized_target = _normalize_page_url(url)

        if self._page_id is not None:
            page = next((page for page in pages if page["pageId"] == self._page_id), None)
            if page is not None:
                if url:
                    await self.call_tool(
                        "navigate_page",
                        {"type": "url", "url": url, "timeout": 30000},
                        timeout_seconds=45.0,
                    )
                    page["url"] = url
                return page

        if url:
            matching_page = next(
                (
                    page
                    for page in pages
                    if _normalize_page_url(page.get("url")) == normalized_target
                    or _normalize_page_url(page.get("url")).startswith(normalized_target)
                    or normalized_target.startswith(_normalize_page_url(page.get("url")))
                ),
                None,
            )
            if matching_page is not None:
                await self._select_page(matching_page["pageId"])
                matching_page["selected"] = True
                return matching_page

            current = next((page for page in pages if page.get("selected")), None) or (pages[0] if pages else None)
            if current is not None:
                self._page_id = current["pageId"]
                await self.call_tool(
                    "navigate_page",
                    {"type": "url", "url": url, "timeout": 30000},
                    timeout_seconds=45.0,
                )
                current["url"] = url
                return current

        if pages:
            page = next((item for item in pages if item.get("selected")), None) or pages[0]
            self._page_id = page["pageId"]
            return page

        text = await self.call_tool(
            "new_page",
            {"url": "about:blank", "background": False, "timeout": 15000},
            timeout_seconds=30.0,
        )
        pages = _parse_pages(text) or await self.list_pages()
        if not pages:
            raise RuntimeError("Chrome MCP could not open an initial page.")
        page = next((item for item in pages if item.get("selected")), None) or pages[-1]
        self._page_id = page["pageId"]
        return page

    async def take_snapshot(self, *, file_path: Optional[str] = None) -> str:
        await self.ensure_page()
        args: dict[str, Any] = {}
        if file_path:
            args["filePath"] = file_path
        return await self.call_tool("take_snapshot", args, timeout_seconds=45.0)

    async def click(self, uid: str) -> str:
        await self.ensure_page()
        return await self.call_tool("click", {"uid": uid, "includeSnapshot": False}, timeout_seconds=30.0)

    async def fill(self, uid: str, value: str) -> str:
        await self.ensure_page()
        return await self.call_tool("fill", {"uid": uid, "value": value, "includeSnapshot": False}, timeout_seconds=30.0)

    async def press_key(self, key: str) -> str:
        await self.ensure_page()
        return await self.call_tool("press_key", {"key": key, "includeSnapshot": False}, timeout_seconds=20.0)

    async def take_screenshot(
        self,
        *,
        file_path: str,
        uid: Optional[str] = None,
        full_page: bool = False,
    ) -> str:
        await self.ensure_page()
        payload: dict[str, Any] = {"filePath": file_path, "format": "png"}
        if uid:
            payload["uid"] = uid
        elif full_page:
            payload["fullPage"] = True
        return await self.call_tool("take_screenshot", payload, timeout_seconds=45.0)

    async def close(self) -> None:
        self._page_id = None
        if self.auto_connect:
            return
        if self._worker_thread is not None and self._worker_thread.is_alive() and self._command_queue is not None:
            future: concurrent.futures.Future[None] = concurrent.futures.Future()
            self._command_queue.put(("stop", {}, future))
            await asyncio.wrap_future(future)
            await asyncio.to_thread(self._worker_thread.join, 5.0)
        self._worker_thread = None
        self._command_queue = None
        self._worker_ready = None
        self._worker_error = None
        if self._browser_process is not None and self._browser_process.poll() is None:
            self._browser_process.terminate()
            try:
                self._browser_process.wait(timeout=5)
            except Exception:
                self._browser_process.kill()
        self._browser_process = None
        self._browser_debug_port = None
