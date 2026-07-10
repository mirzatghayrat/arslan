"""Token authentication for REST (Bearer header) and WebSocket (query param)."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server import config

_bearer = HTTPBearer(auto_error=False)

# Process-wide token minted at boot when the deployment is packaged / prod /
# non-loopback but no explicit ARSLAN_API_TOKEN was supplied (see
# server.token_bootstrap.bootstrap_api_token). An explicit env token always wins;
# this is only consulted when ARSLAN_API_TOKEN is empty. Stays None in the
# dev+localhost zero-friction flow, so require_auth remains a no-op there.
_bootstrapped_token: str | None = None


def set_bootstrapped_token(token: str | None) -> None:
    """Install (or clear) the boot-minted access token. Empty string clears it."""
    global _bootstrapped_token
    _bootstrapped_token = token or None


def active_token() -> str:
    """The token that currently gates the API/WS, resolved live.

    Precedence: an explicit non-empty ``ARSLAN_API_TOKEN`` (read from
    ``config.settings`` at call time) always wins; otherwise the boot-minted
    token (if any). Empty string means auth is disabled (dev+localhost).
    """
    explicit = config.settings.api_token
    if explicit:
        return explicit
    return _bootstrapped_token or ""


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Reject the request unless the Bearer token matches. No-op if no token active.

    Reads the effective token at call time (explicit env token or the boot-minted
    one) so a test that reloads ``server.config`` or bootstraps a token is
    reflected without reloading this module.
    """
    token = active_token()
    if not token:
        return
    if credentials is None or not secrets.compare_digest(credentials.credentials, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def is_ws_token_valid(token: str | None) -> bool:
    """Return True when the WebSocket query-param token is acceptable."""
    expected = active_token()
    if not expected:
        return True
    if token is None:
        return False
    return secrets.compare_digest(token, expected)
