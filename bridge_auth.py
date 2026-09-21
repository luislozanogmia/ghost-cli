"""Authentication helpers for Ghost's loopback Chrome bridge."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


TOKEN_ENV = "GHOST_BRIDGE_TOKEN"
TOKEN_FILE_ENV = "GHOST_BRIDGE_TOKEN_FILE"
DEFAULT_TOKEN_PATH = Path.home() / ".ghost" / "bridge.token"
MIN_TOKEN_BYTES = 32


class BridgeAuthError(RuntimeError):
    """The local bridge token is missing or stored unsafely."""


def token_path() -> Path:
    return Path(os.environ.get(TOKEN_FILE_ENV, DEFAULT_TOKEN_PATH)).expanduser()


def _validate_token(token: str) -> str:
    token = token.strip()
    if len(token.encode("utf-8")) < MIN_TOKEN_BYTES:
        raise BridgeAuthError(
            f"{TOKEN_ENV} must contain at least {MIN_TOKEN_BYTES} bytes"
        )
    return token


def _read_private_file(path: Path) -> str:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BridgeAuthError(f"Bridge token path must be a regular file: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise BridgeAuthError(f"Bridge token file is not owned by the current user: {path}")
    if info.st_mode & 0o077:
        raise BridgeAuthError(f"Bridge token file permissions must be 0600: {path}")
    return _validate_token(path.read_text(encoding="utf-8"))


def load_bridge_token(*, create: bool = False) -> str:
    """Load the bridge token from the environment or a private token file."""
    configured = os.environ.get(TOKEN_ENV)
    if configured:
        return _validate_token(configured)

    path = token_path()
    if path.exists() or path.is_symlink():
        return _read_private_file(path)
    if not create:
        raise BridgeAuthError(
            f"Bridge token not found at {path}. Start bridge_server.py once to create it."
        )

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    value = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (value + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return value
