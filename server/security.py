"""Host / Origin trust policy for the FastAPI app (S1 OSS safety).

A localhost-bound service with no Host validation is reachable by any web page the
user visits via DNS rebinding, and browsers can open cross-site WebSockets freely
(the WS handshake is exempt from the same-origin fetch rules). This module holds the
single allowed-host / allowed-origin policy used by three layers:

  * TrustedHostMiddleware  — rejects foreign ``Host:`` headers (HTTP + WS handshake).
  * CORSMiddleware         — bounds cross-origin browser fetches (never ``*`` + creds).
  * ws_origin_allowed()    — a pre-accept guard each WS handler calls to refuse a
                             cross-site WebSocket open.

Every helper reads ``config.settings`` at call time (mirroring ``server.auth``) so a
test that reloads ``server.config`` is reflected without reloading this module.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from server import config

# Loopback hostnames trusted locally in dev (any scheme/port). Not trusted
# implicitly in prod — prod uses the explicit ARSLAN_ALLOWED_ORIGINS allowlist.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def trusted_allowed_hosts() -> list[str]:
    """Host patterns for Starlette's ``TrustedHostMiddleware``.

    Starlette strips the port from the incoming ``Host`` before matching and asserts
    that no pattern contains ``*`` outside a leading ``*.`` (so ``localhost:*`` would
    crash construction). We therefore normalise any ``host:port`` / ``host:*`` entry
    down to the bare hostname — which then matches every port form of that host,
    exactly the "localhost / 127.0.0.1 and their :port forms" the dev policy wants.
    """
    out: list[str] = []
    for raw in config.settings.allowed_hosts:
        h = (raw or "").strip()
        if not h:
            continue
        if h != "*" and not h.startswith("*."):
            h = h.split(":", 1)[0]  # drop :port / :* — Starlette matches host only
        if h and h not in out:
            out.append(h)
    return out


def cors_allow_origins() -> list[str]:
    """Explicit cross-origin allowlist for ``CORSMiddleware`` (never ``*``)."""
    return [o.strip() for o in config.settings.allowed_origins if o.strip()]


def _norm(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def ws_origin_allowed(origin: str | None, host: str | None = None) -> bool:
    """Return True if a WebSocket handshake with this ``Origin`` may be accepted.

    Policy:
      * No ``Origin`` header → a non-browser client (the smoke's ``websockets`` lib,
        curl, native tools). Browsers ALWAYS send ``Origin`` on a WS handshake, so its
        absence means cross-site-WS (the threat) is not in play. Allowed in dev (keeps
        the daily dev/smoke flow alive), refused in prod (require ``Origin``).
      * Same-origin — the ``Origin`` host:port equals this request's own ``Host`` —
        is always allowed: a page can only send that ``Origin`` if it was itself
        served from this exact host (keeps a same-origin packaged app working).
      * An origin in the configured allowlist (dev default = the vite dev server;
        prod = ``ARSLAN_ALLOWED_ORIGINS``) → allowed.
      * Dev only: any loopback origin (localhost / 127.0.0.1 / ::1, any scheme/port)
        → allowed, so ``http://localhost:5173`` etc. pass without enumerating ports.
      * Everything else (e.g. ``http://evil.com``) → refused.
    """
    cfg = config.settings
    if not origin:
        return not cfg.is_prod

    parts = urlsplit(origin)
    hostname = parts.hostname

    # Same-origin: Origin's netloc (host[:port]) == the request's own Host header.
    if host and parts.netloc and parts.netloc.lower() == host.strip().lower():
        return True

    if _norm(origin) in {_norm(o) for o in cfg.allowed_origins if o.strip()}:
        return True

    if not cfg.is_prod and hostname in _LOOPBACK_HOSTS:
        return True

    return False
