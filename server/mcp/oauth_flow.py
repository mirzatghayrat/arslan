"""OAuth for remote MCP servers — the SDK's flow, our storage and doorways.

WHAT THIS DELIBERATELY IS NOT (user ruling, spec ③): a hand-written OAuth. The
SDK's OAuthClientProvider owns PKCE, state, discovery, registration (DCR) and
refresh; this module contributes exactly three things — where tokens live, how
the browser gets opened, and how the authorization code comes back. Auth is the
last protocol anyone should hand-roll.

STORAGE (ruling §2.1): tokens ride the EXISTING crypto path into the EXISTING
Setting table (`mcp_oauth_tokens_{id}` / `mcp_oauth_client_{id}`, values through
crypto.encrypt). No new table, no new cipher route — spec ⓪ spent a round
collapsing secret storage into one path, and every "just one more" route is how
that un-collapses. Undecryptable blobs read as ABSENT (the flow simply re-runs),
the same stance MCPServer.env takes, and for the same reason: a token written
under yesterday's secret must not take today's session path down.
"""
from __future__ import annotations

import json
import logging

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Setting
from server import crypto

logger = logging.getLogger(__name__)

_TOKENS_KEY = "mcp_oauth_tokens_{server_id}"
_CLIENT_KEY = "mcp_oauth_client_{server_id}"


async def _read(key: str) -> dict | None:
    async with db_session.AsyncSessionLocal() as db:
        row = (
            await db.execute(select(Setting).where(Setting.key == key))
        ).scalar_one_or_none()
    if row is None or not row.value:
        return None
    try:
        return json.loads(crypto.decrypt(row.value))
    except Exception:  # noqa: BLE001 — absent, not broken (module docstring)
        logger.warning("mcp oauth: stored blob for %s is unreadable; treating as absent", key)
        return None


async def _write(key: str, payload: dict) -> None:
    value = crypto.encrypt(json.dumps(payload))
    async with db_session.AsyncSessionLocal() as db:
        row = (
            await db.execute(select(Setting).where(Setting.key == key))
        ).scalar_one_or_none()
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


class EncryptedTokenStorage:
    """The SDK's TokenStorage protocol over Arslan's one crypto path."""

    def __init__(self, server_id: int) -> None:
        self._tokens_key = _TOKENS_KEY.format(server_id=server_id)
        self._client_key = _CLIENT_KEY.format(server_id=server_id)

    async def get_tokens(self) -> OAuthToken | None:
        data = await _read(self._tokens_key)
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await _write(self._tokens_key, tokens.model_dump(mode="json", exclude_none=True))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = await _read(self._client_key)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await _write(self._client_key, client_info.model_dump(mode="json", exclude_none=True))


async def has_tokens(server_id: int) -> bool:
    return await _read(_TOKENS_KEY.format(server_id=server_id)) is not None


def _metadata(redirect_uri: str) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Arslan",
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",  # public client + PKCE (RFC 8252)
    )


def silent_provider(server: dict) -> OAuthClientProvider:
    """Auth for a BACKGROUND connect: refresh with stored tokens is fine, but a
    flow that wants a browser must fail fast — a health probe or a boot-time
    connect has no user at the keyboard, and 'quietly opened a browser at 3am'
    is not a feature."""

    async def refuse_redirect(url: str) -> None:
        raise RuntimeError(
            "this MCP server wants interactive authorization — use the Authorize "
            "button; background connects never open a browser"
        )

    async def refuse_callback() -> tuple[str, str | None]:
        raise RuntimeError("no interactive callback available in a background connect")

    return OAuthClientProvider(
        server_url=server["url"],
        # redirect_uris cannot be empty; for silent refresh it is never used. The
        # port is a placeholder from the loopback range, not a listener.
        client_metadata=_metadata("http://127.0.0.1:1/callback"),
        storage=EncryptedTokenStorage(server["id"]),
        redirect_handler=refuse_redirect,
        callback_handler=refuse_callback,
    )


async def authorize(server: dict, *, on_auth_url, timeout: float = 180.0) -> None:
    """Run the interactive flow once: loopback up, browser URL surfaced through
    `on_auth_url` (the API layer hands it to the frontend, which asks the shell
    to open it — ruling ③A's provenance half: the URL goes straight from the SDK
    to the doorway, nothing in between may invent one), code caught, tokens in
    storage. Raises on refusal/timeout; the loopback closes on every path."""
    from server.mcp.oauth_loopback import catch_authorization_code

    catcher = await catch_authorization_code(timeout=timeout)
    try:
        async def redirect(url: str) -> None:
            await on_auth_url(url)

        async def callback() -> tuple[str, str | None]:
            code, state = await catcher.result
            return code, (state or None)

        provider = OAuthClientProvider(
            server_url=server["url"],
            client_metadata=_metadata(catcher.redirect_uri),
            storage=EncryptedTokenStorage(server["id"]),
            redirect_handler=redirect,
            callback_handler=callback,
        )
        # Drive the flow by doing the thing the tokens are FOR: one authed
        # connect. The SDK sees the 401 challenge, walks discovery/registration/
        # PKCE, and calls our two handlers.
        from server.mcp.session import manager

        await manager.probe_with_auth(server, provider)
    finally:
        catcher.cancel()
