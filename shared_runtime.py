from __future__ import annotations

import ctypes
import json
import logging
import os
from pathlib import Path
from typing import Any


GHOST_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = GHOST_DIR / "runtime"
LOG_DIR = GHOST_DIR / "logs"

GHOST_SHARED_HOST = os.environ.get("GHOST_SHARED_HOST", "127.0.0.1")
GHOST_SHARED_PORT = int(os.environ.get("GHOST_SHARED_PORT", "8765"))
GHOST_SHARED_HTTP_PATH = os.environ.get("GHOST_SHARED_HTTP_PATH", "/mcp")
GHOST_SHARED_URL = os.environ.get(
    "GHOST_SHARED_URL",
    f"http://{GHOST_SHARED_HOST}:{GHOST_SHARED_PORT}{GHOST_SHARED_HTTP_PATH}",
)

SERVER_LOG_FILE = LOG_DIR / "ghost_cli_server.log"
PROXY_LOG_FILE = LOG_DIR / "chrome_transport_proxy.log"
DAEMON_STDOUT_LOG_FILE = LOG_DIR / "ghost_shared_daemon.stdout.log"
DAEMON_STDERR_LOG_FILE = LOG_DIR / "ghost_shared_daemon.stderr.log"
DAEMON_PID_FILE = RUNTIME_DIR / "ghost_shared_daemon.json"


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(name: str, log_file: Path) -> logging.Logger:
    ensure_runtime_dirs()

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)
    logger.propagate = False
    return logger


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    access_denied = 5
    return ctypes.windll.kernel32.GetLastError() == access_denied


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
