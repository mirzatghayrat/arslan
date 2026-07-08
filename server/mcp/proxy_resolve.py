"""PB-1: dynamic proxy resolution for MCP stdio children.

Chain (first hit wins): explicit server.env > backend os.environ > macOS `scutil --proxy`.
The host proxy port changes over time — never hardcode it; resolve at spawn time.
Pure besides the scutil subprocess call, which is isolated in `_scutil_proxy` (test seam)
and fails open: non-macOS / missing binary / timeout → no additions, never raises.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY")
_SCUTIL_TIMEOUT = 2.0
_SCUTIL_LINE = re.compile(r"^\s*(\w+) : (.+?)\s*$", re.MULTILINE)


def _has_proxy_key(env: dict) -> bool:
    keys = {str(k).upper() for k in env}
    return any(k in keys for k in _PROXY_KEYS)


def _parse_scutil(out: str) -> dict[str, str]:
    """Parse `scutil --proxy` output into HTTP(S)_PROXY additions for enabled protocols."""
    fields = dict(_SCUTIL_LINE.findall(out))
    additions: dict[str, str] = {}
    for proto, env_key in (("HTTP", "HTTP_PROXY"), ("HTTPS", "HTTPS_PROXY")):
        if fields.get(f"{proto}Enable") == "1":
            host, port = fields.get(f"{proto}Proxy"), fields.get(f"{proto}Port")
            if host and port:
                additions[env_key] = f"http://{host}:{port}"
    return additions


def _scutil_proxy() -> dict[str, str]:
    """Read the macOS system proxy. Fail-open: any problem → {} (never raises)."""
    try:
        proc = subprocess.run(
            ["scutil", "--proxy"], capture_output=True, text=True, timeout=_SCUTIL_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — non-macOS / missing binary / timeout
        logger.debug("scutil --proxy unavailable: %s", exc)
        return {}
    return _parse_scutil(proc.stdout or "")


def resolve_proxy(server_env: dict) -> tuple[dict, str]:
    """Resolve proxy env additions for an MCP stdio child.

    Returns (env_additions, source). Sources "server_env" and "os_environ" add nothing:
    the explicit server env / **os.environ inheritance already carry the variables.
    """
    if _has_proxy_key(server_env or {}):
        return {}, "server_env"
    if _has_proxy_key(os.environ):
        return {}, "os_environ"
    additions = _scutil_proxy()
    if additions:
        return additions, "scutil"
    return {}, "none"
