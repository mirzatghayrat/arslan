"""Token authentication for REST (Bearer header) and WebSocket (query param)."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server import config

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Reject the request unless the Bearer token matches. No-op if unset.

    Reads ``config.settings`` at call time so a test that reloads
    ``server.config`` is reflected without reloading this module.
    """
    token = config.settings.api_token
    if not token:
        return
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def is_ws_token_valid(token: str | None) -> bool:
    """Return True when the WebSocket query-param token is acceptable."""
    expected = config.settings.api_token
    if not expected:
        return True
    return token == expected
