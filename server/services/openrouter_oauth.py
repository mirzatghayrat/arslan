"""OpenRouter one-click sign-in — spec ③'s plumbing under a simpler flow.

NOT the MCP SDK's OAuthClientProvider, deliberately: OpenRouter's flow has no
client_id, no token endpoint and no DCR — an auth page, a code, one JSON
exchange (verified against openrouter.ai/docs, not memory: localhost callbacks
on ANY port, no app pre-registration). What carries over from ③ is the
infrastructure and its rules — the loopback catcher, the pinned HTTP path for
every outbound call, and the provenance rule that the auth URL travels
backend → response → the shell doorway and nowhere else.

The PKCE pair here is three lines of stdlib (secrets + hashlib + base64). The
"never hand-write auth" ruling bans protocol STATE MACHINES, not one hash.

THE FREE DEFAULT IS CHOSEN, NOT HARDCODED. A third-party model id is data that
rots; after the exchange we list /models over the same pinned path and pick a
`:free` one (deepseek preferred). When none can be found the fallback to the
preset default is STATED in the result — a silent paid default would 402 on the
exact zero-card user this feature exists for. Money stays on OpenRouter's side:
no balances, no top-ups, nothing here touches it.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

from server.mcp.oauth_loopback import catch_authorization_code
from server.db import session as db_session
from server.registry import net_pin
from server.services import provider_config_service

logger = logging.getLogger(__name__)

_AUTH_BASE = "https://openrouter.ai/auth"
_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
_MODELS_URL = "https://openrouter.ai/api/v1/models"
#: The preset's default — used only as the stated fallback when no free model
#: can be found. Kept equal to arslan/llm/presets.py's openrouter entry.
_FALLBACK_MODEL = "anthropic/claude-sonnet-5"


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256: verifier (>=43 chars) and BASE64URL(SHA256(verifier))."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _auth_url(redirect_uri: str, challenge: str) -> str:
    return _AUTH_BASE + "?" + urlencode(
        {
            "callback_url": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def _pick_free_model(models_payload: dict) -> str | None:
    """A `:free` model id, deepseek preferred, or None — never a guess."""
    data = models_payload.get("data")
    if not isinstance(data, list):
        return None
    free = [
        m.get("id")
        for m in data
        if isinstance(m, dict)
        and isinstance(m.get("id"), str)
        and str((m.get("pricing") or {}).get("prompt", "")) in ("0", "0.0")
    ]
    free = [f for f in free if f]
    if not free:
        return None
    for f in free:
        if f.startswith("deepseek/"):
            return f
    return free[0]


async def run_flow(*, on_auth_url, timeout: float = 180.0) -> dict:
    """One complete sign-in: loopback up → URL out through `on_auth_url` → code
    in → key exchanged → free model chosen → provider_config created (existing
    encrypted path; first config becomes primary via add_config's own rule).

    Raises on refusal/timeout — a failed exchange must not leave a keyless
    config behind, so the config is only created after the key is in hand.
    """
    verifier, challenge = _pkce_pair()
    catcher = await catch_authorization_code(timeout=timeout)
    try:
        await on_auth_url(_auth_url(catcher.redirect_uri, challenge))
        code, _state = await catcher.result

        resp = await net_pin.pinned_request(
            "POST",
            _KEYS_URL,
            json={
                "code": code,
                "code_verifier": verifier,
                "code_challenge_method": "S256",
            },
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        key = (resp.json() or {}).get("key", "")
        if not key:
            raise RuntimeError("OpenRouter answered without a key")

        model, free = _FALLBACK_MODEL, False
        try:
            models_resp = await net_pin.pinned_request("GET", _MODELS_URL)
            models_resp.raise_for_status()
            picked = _pick_free_model(models_resp.json())
            if picked:
                model, free = picked, True
        except Exception:  # noqa: BLE001 — fallback is legitimate, silence is not
            logger.warning("openrouter: model listing failed; falling back to %s", _FALLBACK_MODEL)

        async with db_session.AsyncSessionLocal() as db:
            cfg = await provider_config_service.add_config(
                db,
                label="OpenRouter",
                provider="openrouter",
                model=model,
                base_url="",
                api_key=key,
            )
        return {"config_id": cfg["id"], "model": model, "free_model": free}
    finally:
        catcher.cancel()
