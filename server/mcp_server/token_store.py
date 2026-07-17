"""Dedicated inbound-MCP access token — separate from the app ``api_token``.

Stored in its own file (``<data_dir>/mcp_token``, mode 0o600), minted on demand from
Settings, and NEVER derived from ``ARSLAN_SECRET_KEY`` (one secret does not do two
jobs). The inbound MCP gate compares the presented bearer against this with
``secrets.compare_digest``. Rotating or clearing it invalidates the previous token
immediately — the gate reads the file per request.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

MCP_TOKEN_FILENAME = "mcp_token"


def _resolve_data_dir(data_dir):
    if data_dir is not None:
        return data_dir
    from server.config import settings  # call-time import: honors a reloaded config in tests
    return settings.data_dir


def _token_path(data_dir=None) -> Path:
    return Path(_resolve_data_dir(data_dir)) / MCP_TOKEN_FILENAME


def read_mcp_token(data_dir=None) -> str:
    try:
        return _token_path(data_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_CREAT honours the mode only for a *new* file; chmod afterwards makes an
    # overwrite of an existing, laxer file safe too.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def generate_mcp_token(data_dir=None) -> str:
    token = secrets.token_urlsafe(32)
    _write(_token_path(data_dir), token)
    return token


def clear_mcp_token(data_dir=None) -> None:
    try:
        _token_path(data_dir).unlink()
    except OSError:
        pass


def mcp_token_matches(presented: str | None, data_dir=None) -> bool:
    stored = read_mcp_token(data_dir)
    if not stored or not presented:
        return False
    try:
        return secrets.compare_digest(presented, stored)
    except TypeError:
        # A non-ASCII bearer makes compare_digest raise; treat it as a mismatch so the
        # untrusted surface fails closed with 401, never an uncaught 500.
        return False
