"""S1-3 env-split access-token bootstrap.

A fresh install ships with ``ARSLAN_API_TOKEN`` empty, which makes
``require_auth`` / ``is_ws_token_valid`` no-ops — every endpoint UNAUTHENTICATED.
That is fine for the daily dev+localhost flow but dangerous for a packaged app, a
prod deployment, or a non-loopback bind.

This module closes that gap *without* adding friction for developers:

  * ``_needs_token(cfg)`` decides whether this deployment must be authenticated:
      - ``ARSLAN_ENV=prod`` (``cfg.is_prod``), OR
      - the packaged build flag ``ARSLAN_PACKAGED`` is truthy (the Tauri wrapper
        sets ``ARSLAN_PACKAGED=1`` — that is the integration hook), OR
      - the *advertised* bind host is non-loopback. The app cannot observe the
        launcher's ``uvicorn --host`` directly; it infers the bind from
        ``HOST`` / ``ARSLAN_BIND_HOST`` (same signal as the boot advisory in
        ``server.main``). LIMITATION: a bare ``uvicorn --host 0.0.0.0`` with
        neither env var set is invisible here — prod/packaged users should set
        one of the env vars, and prod already forces enforcement anyway.

  * ``bootstrap_api_token(cfg)`` (called once at boot):
      - explicit non-empty ``ARSLAN_API_TOKEN`` -> use it, persist nothing;
      - else needs-token + no persisted file -> mint ``secrets.token_urlsafe(32)``,
        persist to ``data_dir/api_token`` (0o600), print it ONCE;
      - else needs-token + persisted file -> load it (never regenerate);
      - else (dev+localhost) -> stay open, no file written.
    The effective token is handed to ``server.auth`` so the REST/WS guards enforce
    it. Packaged users who never see the console can read/rotate it from Settings
    (``server.api.settings`` access-token endpoints, localhost-gated).
"""
from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import stat
from pathlib import Path

from server import auth

logger = logging.getLogger(__name__)

TOKEN_FILENAME = "api_token"
PACKAGED_ENV = "ARSLAN_PACKAGED"
_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in _TRUTHY


def is_loopback_host(host: str | None) -> bool:
    """True when ``host`` is a loopback address / localhost (never exposed).

    ``0.0.0.0`` (all interfaces), real IPs and hostnames are NON-loopback. An
    empty/None host is treated as non-loopback (fail-safe for client gating).
    """
    if not host:
        return False
    h = host.strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _advertised_bind_host(cfg) -> str:
    """The bind host the app can observe (launcher --host is not visible)."""
    return (os.environ.get("HOST") or cfg.bind_host or "").strip()


def _needs_token(cfg) -> bool:
    """Whether this deployment must be authenticated (see module docstring)."""
    if cfg.is_prod:
        return True
    if _is_truthy(os.environ.get(PACKAGED_ENV)):
        return True
    host = _advertised_bind_host(cfg)
    if host and not is_loopback_host(host):
        return True
    return False


def _token_path(data_dir) -> Path:
    return Path(data_dir) / TOKEN_FILENAME


def _write_token(path: Path, token: str) -> None:
    """Persist the token with owner-only (0o600) permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create fresh with 0o600 (open O_CREAT honours the mode only for new files);
    # chmod afterwards makes an overwrite of an existing, laxer file safe too.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _read_token(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _generate_and_persist(data_dir, *, log: logging.Logger) -> str:
    token = secrets.token_urlsafe(32)
    path = _token_path(data_dir)
    _write_token(path, token)
    log.warning(
        "\n"
        "  ┌─────────────────────────────────────────────────────────────┐\n"
        "  │  Arslan access token: %s\n"
        "  │  Enter it in the app (Settings), or set ARSLAN_API_TOKEN.\n"
        "  │  Stored at: %s\n"
        "  └─────────────────────────────────────────────────────────────┘",
        token, path,
    )
    return token


def bootstrap_api_token(cfg, data_dir=None, *, log: logging.Logger = logger) -> str:
    """Resolve and install the effective access token for this boot.

    Returns the active token ("" means auth stays disabled). Idempotent: never
    regenerates a persisted token. Always (re)installs the result into
    ``server.auth`` so the guards reflect it.
    """
    if data_dir is None:
        data_dir = cfg.data_dir

    # 1) An explicit env token always wins — never touch the filesystem.
    if cfg.api_token:
        auth.set_bootstrapped_token(None)  # explicit env token takes precedence
        return cfg.api_token

    # 2) Dev + localhost + no token: zero-friction, stay unauthenticated.
    if not _needs_token(cfg):
        auth.set_bootstrapped_token(None)
        return ""

    # 3) Needs a token. Reuse a persisted one; only mint on first run.
    path = _token_path(data_dir)
    token = _read_token(path)
    if token:
        auth.set_bootstrapped_token(token)
        log.info("Loaded persisted access token from %s (auth enforced).", path)
    else:
        token = _generate_and_persist(data_dir, log=log)
        auth.set_bootstrapped_token(token)
    return token


def reset_api_token(cfg, data_dir=None, *, log: logging.Logger = logger) -> str:
    """Rotate the access token: mint a new one, persist it, install it. Returns it.

    The old token stops working immediately. Used by the localhost-gated Settings
    reset endpoint so a packaged user can never permanently lock themselves out.

    REFUSES (ValueError) when ``ARSLAN_API_TOKEN`` is env-managed: ``auth.active_token``
    makes an explicit env token always win, so minting here would rotate nothing and the
    server would keep demanding the env token — a silent lockout. The env token must be
    rotated where it is set. Defense-in-depth behind the endpoint's 409 (see
    server.api.settings).
    """
    if cfg.api_token:
        raise ValueError(
            "cannot reset: the access token is set via the ARSLAN_API_TOKEN environment "
            "variable; rotate it there, not here.")
    if data_dir is None:
        data_dir = cfg.data_dir
    token = secrets.token_urlsafe(32)
    _write_token(_token_path(data_dir), token)
    auth.set_bootstrapped_token(token)
    log.info("Access token was reset.")
    return token
