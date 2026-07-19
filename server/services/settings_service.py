"""Read/write user settings, encrypting the API key and masking it on read."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import crypto
from server.db.models import Setting

logger = logging.getLogger(__name__)

# Plain (non-secret) keys returned verbatim.
_PLAIN_KEYS = ("llm_provider", "llm_model", "llm_base_url", "language", "search_provider",
               "llm_strategy", "distill_on_session_end", "orchestrator_shell_enabled",
               "shell_confirm_policy", "synthesis_config_id", "embedding_config_id",
               "evolution_auto", "mcp_server_enabled", "curation_enabled")
# Integer keys, handled like _PLAIN_KEYS but round-tripped through int() on read.
_INT_KEYS = ("run_debug_retention_days", "evolution_max_est_tokens")
# Secret keys stored encrypted, returned masked.
_SECRET_KEYS = ("llm_api_key", "search_api_key", "github_token")

# Matches the two mask shapes produced by mask_secret():
#   "***"                    – short-key mask (len < 8)
#   "<2-3 char prefix>...<4 char suffix>"  – long-key mask
_MASK_RE = re.compile(r"^.{2,3}\.\.\..{4}$")


def _looks_masked(value: str) -> bool:
    """Return True when *value* looks like output of mask_secret().

    This guards the GET→PUT round-trip: a client that GETs settings and PUTs
    the body back unchanged would send the masked echo rather than the real
    secret.  We detect the two mask shapes and skip storage so the stored
    plaintext is never silently overwritten with its own mask.

    The check is anchored to the full string so a real key that happens to
    contain "..." somewhere in the middle still passes through.
    """
    return value == "***" or bool(_MASK_RE.fullmatch(value))


def mask_secret(value: str) -> str:
    """Mask a secret for display: keep a prefix hint and last 4 chars."""
    if not value:
        return ""
    if len(value) < 8:
        return "***"
    prefix = value[:3] if value.startswith("sk-") else value[:2]
    return f"{prefix}...{value[-4:]}"


def _safe_decrypt(enc: str) -> str:
    """Decrypt a stored secret, treating an undecryptable value as unset.

    If ARSLAN_SECRET_KEY changed since the value was encrypted, Fernet raises
    InvalidToken; we degrade gracefully so the settings endpoint stays usable
    and the user can re-enter the key.
    """
    try:
        return crypto.decrypt(enc)
    except InvalidToken:
        logger.warning("settings: stored API key could not be decrypted; treating as unset")
        return ""


async def _get_raw(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set_raw(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(Setting, key)
    if existing:
        existing.value = value
    else:
        session.add(Setting(key=key, value=value))


async def update_settings(session: AsyncSession, data: dict[str, str]) -> None:
    """Persist provided settings. Secret keys are encrypted before storage."""
    for key in _PLAIN_KEYS:
        if key in data and data[key] is not None:
            await _set_raw(session, key, str(data[key]))
    for int_key in _INT_KEYS:
        if int_key in data and data[int_key] is not None:
            await _set_raw(session, int_key, str(data[int_key]))
    for secret_key in _SECRET_KEYS:
        val = data.get(secret_key)
        # Skip masked echoes: a GET→PUT round-trip sends back the masked value
        # (e.g. "sk-...9999" or "***") which must never replace the real key.
        if val and not _looks_masked(str(val)):
            await _set_raw(session, secret_key, crypto.encrypt(str(val)))
    await session.commit()


async def get_settings(session: AsyncSession) -> dict[str, str]:
    """Return settings for display; secret keys are masked."""
    out: dict[str, str] = {}
    for key in _PLAIN_KEYS:
        val = await _get_raw(session, key)
        if val is not None:
            out[key] = val
    for secret_key in _SECRET_KEYS:
        enc = await _get_raw(session, secret_key)
        out[secret_key] = mask_secret(_safe_decrypt(enc)) if enc else ""
    out["run_debug_retention_days"] = await run_debug_retention_days(session)
    out["evolution_auto"] = "on" if await evolution_auto(session) else "off"
    out["evolution_max_est_tokens"] = await evolution_max_est_tokens(session)
    return out


async def get_decrypted(session: AsyncSession, key: str) -> str:
    """Plaintext secret for internal use (never exposed via API)."""
    enc = await _get_raw(session, key)
    return _safe_decrypt(enc) if enc else ""


async def get_decrypted_api_key(session: AsyncSession) -> str:
    """Return the plaintext LLM API key for making LLM calls (never exposed via API)."""
    return await get_decrypted(session, "llm_api_key")


async def distill_enabled(session: AsyncSession) -> bool:
    """Whether session-end distillation is on (default True; only an explicit 'false' disables)."""
    raw = await _get_raw(session, "distill_on_session_end")
    return raw is None or str(raw).strip().lower() != "false"


async def curation_enabled(session: AsyncSession) -> bool:
    """Whether the sleep-time curation loop may run.

    🔴 Default OFF (opt-in), unlike every other toggle here. The loop SPENDS money, and
    its output currently lands in the brain proposal inbox, which has no UI yet (that
    is the F2 frontend round) — so a default-on sweep would burn tokens producing
    something the user cannot see. Per the project's standing rule, the proposing side
    is fail-open but the EXECUTING side (writes, tools, spend) is fail-closed. Flip the
    default once the inbox is visible.

    The loop ALSO requires distill_enabled: ignoring the user's session-end distill
    switch would violate that consent and spend money doing it.
    """
    raw = await _get_raw(session, "curation_enabled")
    return raw is not None and str(raw).strip().lower() == "true"


async def shell_enabled(session: AsyncSession) -> bool:
    """Whether the orchestrator-only run_command tool is exposed to Arslan.
    Default OFF (opt-in): only an explicit 'true' enables it."""
    raw = await _get_raw(session, "orchestrator_shell_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def mcp_server_enabled(session: AsyncSession) -> bool:
    """Whether the inbound MCP server mount accepts requests. Default OFF (opt-in):
    only an explicit 'true' enables it (lowercased so a stored 'True' still matches)."""
    raw = await _get_raw(session, "mcp_server_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def shell_confirm_policy(session: AsyncSession) -> str:
    """Confirmation posture for run_command: 'ask_all' (default) confirms every
    command; 'ask_risky' auto-runs LOW-risk (read-only) commands and confirms
    MEDIUM/HIGH. Any unrecognized value falls back to the safe 'ask_all'."""
    raw = await _get_raw(session, "shell_confirm_policy")
    return "ask_risky" if str(raw).strip().lower() == "ask_risky" else "ask_all"


async def evolution_auto(session: AsyncSession) -> bool:
    """Whether the background evolution watcher may run attempts for spawns.

    Default ON (spec §4: evolution_auto=on is standing consent — estimate is visible in the
    inbox/attempt, not a per-round popup; the budget cap + backoff prevent runaway spend).
    Only an explicit 'off'/'false'/'0' disables it."""
    raw = await _get_raw(session, "evolution_auto")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("off", "false", "0", "no")


async def evolution_max_est_tokens(session: AsyncSession) -> int | None:
    """Per-attempt lower-bound token budget cap. When set, an attempt whose estimate exceeds
    it is recorded as outcome='skipped_budget' and never run. Unset (None) = no cap."""
    raw = await _get_raw(session, "evolution_max_est_tokens")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


# S2 E9 — the developer-declared clean-corpus start (spec §E9 / audit #12).
EVOLUTION_BASELINE_STARTED_AT_KEY = "evolution_baseline_started_at"


def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp to a NAIVE-UTC datetime — matching Run.created_at, which
    is written via datetime.utcnow(). A tz-aware value is converted to UTC and stripped of
    tzinfo so it compares directly against the naive DB column. Unparsable → None."""
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def get_baseline_started_at(session: AsyncSession) -> datetime | None:
    """The clean-corpus start declared in E9. None = never declared → build_corpus /
    replay_set apply no created_at floor (back-compat: every epoch>=1 live run is eligible)."""
    return _parse_iso_utc(await _get_raw(session, EVOLUTION_BASELINE_STARTED_AT_KEY))


async def set_baseline_started_at(session: AsyncSession, dt: datetime) -> None:
    """Persist the clean-corpus start as an ISO-8601 string, stored naive-UTC (a tz-aware
    dt is normalized first) so the round-trip and the DB comparison stay consistent."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    await _set_raw(session, EVOLUTION_BASELINE_STARTED_AT_KEY, dt.isoformat())
    await session.commit()


DEFAULT_RUN_DEBUG_RETENTION_DAYS = 30


async def run_debug_retention_days(session: AsyncSession) -> int:
    """Days a run's sensitive/bulky debug detail (system_prompt, injected_kb,
    per-step args_full/result_raw) is kept before the boot sweep redacts it.
    Default 30. A value of 0 (or an unparsable value) disables the sweep... except
    unset (None) still means "use the default", not "disabled"."""
    raw = await _get_raw(session, "run_debug_retention_days")
    if raw is None:
        return DEFAULT_RUN_DEBUG_RETENTION_DAYS
    try:
        return int(str(raw).strip())
    except ValueError:
        return DEFAULT_RUN_DEBUG_RETENTION_DAYS
