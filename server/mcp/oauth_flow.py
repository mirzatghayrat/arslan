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
from urllib.parse import urlsplit

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from sqlalchemy import literal, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from server.db import session as db_session
from server.db.models import MCPServer, Setting
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


async def _write(key: str, payload: dict, server_id: int) -> None:
    """Stored only for a server that exists, in one statement: a browser flow or a token refresh can finish while its
    server is being removed, and a separate check could pass just before the remove and write just after it."""
    value = crypto.encrypt(json.dumps(payload))
    exists = select(MCPServer.id).where(MCPServer.id == server_id).exists()
    insert = sqlite_insert(Setting).from_select(["key", "value"], select(literal(key), literal(value)).where(exists))
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(insert.on_conflict_do_update(index_elements=[Setting.key],
                                                      set_={"value": insert.excluded.value}))
        await db.commit()


def stored_keys(server_id: int) -> list[str]:
    """Where one server's sign-in is kept: they go with the server (`mcp_service.delete_server`)."""
    return [_TOKENS_KEY.format(server_id=server_id), _CLIENT_KEY.format(server_id=server_id)]


class EncryptedTokenStorage:
    """The SDK's TokenStorage protocol over Arslan's one crypto path."""

    def __init__(self, server_id: int) -> None:
        self._server_id = server_id
        self._tokens_key = _TOKENS_KEY.format(server_id=server_id)
        self._client_key = _CLIENT_KEY.format(server_id=server_id)

    async def get_tokens(self) -> OAuthToken | None:
        data = await _read(self._tokens_key)
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await _write(self._tokens_key, tokens.model_dump(mode="json", exclude_none=True), self._server_id)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = await _read(self._client_key)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await _write(self._client_key, client_info.model_dump(mode="json", exclude_none=True), self._server_id)


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


SIGN_IN_CHECK_TIMEOUT_S = 5.0


async def offers_sign_in(url: str) -> bool:
    """Does this server say it takes OAuth? A server with no stored sign-in gets no provider (`session`), so its 401
    reads as "no credentials", the same as one that wants a key. What it publishes tells them apart: the 401's challenge
    naming its metadata (RFC 9728), or that metadata at the well-known addresses on its own origin. Read-only and only
    what it says about itself: no client is registered, and no address its metadata names is visited."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    known = ((f"{origin}/.well-known/oauth-protected-resource{parts.path.rstrip('/')}", "authorization_servers"),
             (f"{origin}/.well-known/oauth-protected-resource", "authorization_servers"),
             (f"{origin}/.well-known/oauth-authorization-server", "authorization_endpoint"))
    try:
        async with httpx.AsyncClient(timeout=SIGN_IN_CHECK_TIMEOUT_S, follow_redirects=False) as client:
            r = await client.post(url, json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                                  headers={"Accept": "application/json, text/event-stream"})
            if r.status_code == 401 and "resource_metadata" in r.headers.get("www-authenticate", "").lower():
                return True
            for address, field in known:
                r = await client.get(address)
                if r.status_code != 200:
                    continue
                try:
                    body = r.json()
                except ValueError:
                    continue
                if isinstance(body, dict) and body.get(field):
                    return True
    except httpx.HTTPError:
        return False
    return False


class NeedsInteractiveAuth(RuntimeError):
    """A background connect reached a step that needs the user's browser (0.1.61 §B1: needs_auth)."""


def silent_provider(server: dict) -> OAuthClientProvider:
    """Auth for a BACKGROUND connect: refresh with stored tokens is fine, but a
    flow that wants a browser must fail fast — a health probe or a boot-time
    connect has no user at the keyboard, and 'quietly opened a browser at 3am'
    is not a feature."""

    async def refuse_redirect(url: str) -> None:
        raise NeedsInteractiveAuth(
            "this MCP server wants interactive authorization — use the Authorize "
            "button; background connects never open a browser"
        )

    async def refuse_callback() -> tuple[str, str | None]:
        raise NeedsInteractiveAuth("no interactive callback available in a background connect")

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
