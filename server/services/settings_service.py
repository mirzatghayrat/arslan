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

from server.services.secret_state import secret_state

logger = logging.getLogger(__name__)

# Plain (non-secret) keys returned verbatim.
_PLAIN_KEYS = (
    "curation_backfill_from","llm_provider", "llm_model", "llm_base_url", "language", "search_provider", "search_base_url",
               "llm_strategy", "distill_on_session_end", "orchestrator_shell_enabled",
               "shell_confirm_policy", "synthesis_config_id", "embedding_config_id",
               # Per-task model slots (spec ②). Registered here AND on both
               # pydantic schemas — being on only one is how github_token became
               # a settings field that looked saveable and was not.
               "compaction_config_id", "title_config_id",
               "router_config_id", "vision_config_id",
               "evolution_auto", "mcp_server_enabled", "curation_enabled", "ocr_languages",
               "workspace_dir", "heartbeat_enabled", "heartbeat_checklist",
               "heartbeat_interval_s", "lan_discovery_enabled", "ssh_enabled", "default_read_enabled",
               "voice_output_enabled")
# Integer keys, handled like _PLAIN_KEYS but round-tripped through int() on read.
_INT_KEYS = ("run_debug_retention_days", "evolution_max_dispatches",
             "brain_usage_event_retention_days", "brain_usage_event_max_rows")
# Secret keys stored encrypted, returned masked.
_SECRET_KEYS = ("llm_api_key", "search_api_key", "github_token")
#: Read-only companions emitted for each secret: "unset" | "set" | "undecryptable".
#: DERIVED from _SECRET_KEYS, never hand-listed — a hand-written list is how
#: github_token came to be missing from both pydantic schemas while the frontend was
#: sending it (see tests/server/test_secret_three_state.py). They are not settings:
#: nothing stores them, `SettingsIn` does not accept them, and a client echoing the
#: GET body back cannot create rows for them.
_SECRET_STATE_KEYS = tuple(f"{k}_status" for k in _SECRET_KEYS)

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


async def _clear_raw(session: AsyncSession, key: str) -> None:
    """Delete a setting outright. Distinct from storing "" — the boundary readers treat
    an unparsable value as "not recorded", but leaving a blank row behind would make a
    cleared boundary indistinguishable from a corrupt one in the DB."""
    existing = await session.get(Setting, key)
    if existing:
        await session.delete(existing)


def _truthy(value) -> bool:
    """The one place that decides what an incoming settings value means. Accepts real
    bools (the API) and the strings the DB round-trips."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "on", "yes")


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

    # 🔴 Turning curation OFF discards the backfill boundary, so a later re-enable
    # records a FRESH one. The boundary belongs to the CURRENT enablement, not to the
    # database: written once per DB, the most likely real sequence — enable, find it
    # expensive, disable, use the app for months, enable again — would sweep the entire
    # off-period, which is the mass historical backfill the gate exists to prevent.
    # Cleared HERE rather than only in the loop because the toggle can happen while the
    # app is down; the loop's own off-tick clearing is belt and braces for a direct DB edit.
    if "curation_enabled" in data and not _truthy(data["curation_enabled"]):
        await _clear_raw(session, CURATION_BACKFILL_FROM_KEY)

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
        # The honest state alongside the mask. Without it the response cannot tell
        # "never entered" from "entered, and we can no longer open it" — and
        # mask_secret("") is "", so the second one arrives looking like the first.
        out[f"{secret_key}_status"] = secret_state(enc)
    # 🔴 The int keys are emitted from ONE registry, not hand-listed.
    #
    # This used to be three literal lines, which made get_settings a SIXTH touch point
    # that the "five touch points" rule does not name — and D5 promptly forgot it: both
    # brain_usage_event_* keys were in _INT_KEYS (so PUT persisted them) and had
    # accessors (so the pruner honored them) while GET returned the pydantic defaults.
    # A user could set retention to 0, get a 200 saying 30, and have the ceiling
    # silently removed with no way to observe it; worse, the ordinary settings-form
    # round-trip (GET the body, PUT it back) would write the default back over a
    # deliberately longer retention and delete the difference on the next tick.
    # Deriving from _INT_ACCESSORS makes that class of omission impossible: the
    # registry is asserted complete against _INT_KEYS by test_settings_int_keys.
    for int_key, accessor in _INT_ACCESSORS.items():
        out[int_key] = await accessor(session)
    # 🔴 Same treatment for the BOOL keys, and for the same reason one type up.
    #
    # They ride _PLAIN_KEYS, which emits the RAW STRING and only `if val is not None` —
    # so on a fresh install the key is ABSENT from the response and SettingsOut's
    # pydantic default answers for it. That gave every bool TWO independent definitions
    # of its default (the accessor and the schema) with nothing asserting they agree.
    # A change that moved only one of them — exactly what flipping curation_enabled
    # would be — produces a UI reporting OFF while the loop runs, or the reverse.
    # Asserted complete against _BOOL_KEYS by test_settings_bool_keys.
    for bool_key, accessor in _BOOL_ACCESSORS.items():
        out[bool_key] = await accessor(session)
    out["evolution_auto"] = "on" if await evolution_auto(session) else "off"
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


async def lan_discovery_enabled(session: AsyncSession) -> bool:
    """Whether Arslan may look at what is on the local network. Default OFF:
    scanning a network is something a person should choose, not discover
    having happened."""
    raw = await _get_raw(session, "lan_discovery_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def default_read_enabled(session: AsyncSession) -> bool:
    """Whether Arslan may READ ~/Desktop, ~/Documents, ~/Downloads without a
    configured workspace. Default **ON** (spec 2026-08-24, user ruling): the whole
    point is that a novice can 'look at my desktop' the moment they install. Only
    an explicit 'false' turns it off — the exit for a privacy-sensitive user, not
    a gate for everyone. Mirrors distill_on_session_end's default-on shape.

    This governs READS only. Writes stay workspace-bound and gated regardless."""
    raw = await _get_raw(session, "default_read_enabled")
    return raw is None or str(raw).strip().lower() != "false"


async def ssh_enabled(session: AsyncSession) -> bool:
    """Whether Arslan may reach another machine over SSH. Default OFF, and it stays
    OFF on its own: this is the switch for the highest-risk surface in the product,
    so it is opt-in even for a user who already turned on shell and LAN discovery."""
    raw = await _get_raw(session, "ssh_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def heartbeat_enabled(session: AsyncSession) -> bool:
    """Whether the periodic checklist turn runs. Default OFF (裁决③)."""
    raw = await _get_raw(session, "heartbeat_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def heartbeat_checklist(session: AsyncSession) -> str:
    """The user's checklist text. Empty means there is nothing to check."""
    raw = await _get_raw(session, "heartbeat_checklist")
    return str(raw) if raw is not None else ""


async def heartbeat_interval_s(session: AsyncSession) -> int:
    """Seconds between checks. The scheduler's floor still applies on top."""
    from server.services.heartbeat import DEFAULT_INTERVAL_S

    raw = await _get_raw(session, "heartbeat_interval_s")
    try:
        return int(str(raw).strip()) if raw is not None else DEFAULT_INTERVAL_S
    except ValueError:
        return DEFAULT_INTERVAL_S


async def workspace_dir(session: AsyncSession):
    """The directory Arslan's file tools may work in, or None when unset.

    Default UNSET (opt-in, zero default by user ruling 2026-08-20): with no
    workspace the file tools are not registered at all — not registered and
    erroring, which would advertise a capability that cannot work. A stored
    path that no longer resolves to a directory reads as unset for the same
    reason."""
    from pathlib import Path

    raw = await _get_raw(session, "workspace_dir")
    if raw is None or not str(raw).strip():
        return None
    try:
        path = Path(str(raw).strip()).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    return path if path.is_dir() else None


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

    🔴 Default OFF. It used to default ON, justified as "standing consent — the estimate
    is visible in the inbox, and the budget cap + backoff prevent runaway spend". Both
    halves of that justification turned out to be false:

      * the budget cap did not exist at the time. `evolution_max_dispatches` now caps
        projected DISPATCHES, but is still unset by default,
        because the estimate it would gate on is a known over-estimate that grows with
        the corpus (see evolution_estimate.py) — a fixed cap over a growing number is a
        permanent kill switch, so no cap is set and nothing bounds the total;
      * "visible in the inbox" is visible only to someone who already knows to look.
        There was no Settings control for this at all, so a user could neither see that
        it was running nor turn it off without calling the API by hand.

    Which left: clone the repo, run it, and a background loop starts spending YOUR API
    credits without being asked. That is not consent, standing or otherwise.

    This is the same rule `curation_enabled` above already states — the proposing side is
    fail-open, the EXECUTING side (writes, tools, spend) is fail-closed — applied to the
    loop that spends two orders of magnitude more. It was written down there and not
    applied here, because this default predates the discovery that its cap was fiction.

    Only an explicit 'on'/'true'/'1'/'yes' enables it.
    """
    raw = await _get_raw(session, "evolution_auto")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("on", "true", "1", "yes")


_LEGACY_TOKEN_CAP_KEY = "evolution_max_est_tokens"


async def legacy_token_cap_if_set(session: AsyncSession) -> str | None:
    """The pre-dispatch-cap key, if an install had actually set one.

    🔴 fail-LOUD, not fail-silent. The replacement changed the UNIT, so the old value
    cannot be carried over — any conversion would be invented, since tokens-per-dispatch
    is exactly the figure this project does not reliably know. But a limit that vanishes
    without a word is worse than one that is refused with an explanation: the user set a
    spending limit and would go on believing it applied. Surfaced by the diagnostics
    payload so it reaches a screen instead of a log line nobody reads."""
    return await _get_raw(session, _LEGACY_TOKEN_CAP_KEY)


async def evolution_max_dispatches(session: AsyncSession) -> int | None:
    """Per-attempt cap on PROJECTED REPLAY DISPATCHES. Unset (None) = no cap, and that is
    still the default: the `actual` ledger is empty on every install, so there is no
    distribution to pick a number from.

    🔴 Counts dispatches, not tokens, and it REPLACED `evolution_max_est_tokens` rather
    than being renamed from it. Renaming while changing the unit is a silent-corruption
    trap: a stored 30,000,000 would survive as a "30 million dispatch" cap — no cap at all
    — and no conversion is honest, because tokens-per-dispatch is precisely the figure we
    do not reliably know. The old key was verified unset before removal, and any install
    that DID set it gets a warning rather than a silently dropped limit.

    The unit changed because the old one gated on a number that over-states by 3.7-5.2x:
    a user setting a cap from what evolution really costs would have had every attempt
    refused. The gate failed in the direction where setting a limit switches the feature
    off, with nothing on screen explaining why."""
    raw = await _get_raw(session, "evolution_max_dispatches")
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


# D5 — the two gates that bound brain_usage_events. Both are settable so an install
# that wants a longer timeline can pay for it explicitly; neither may be silently
# unbounded, which is why an unparsable value falls back to the DEFAULT rather than to
# "no limit". 0 disables that one gate (the other still applies), matching
# run_debug_retention_days' meaning of 0.
DEFAULT_BRAIN_USAGE_EVENT_RETENTION_DAYS = 30
DEFAULT_BRAIN_USAGE_EVENT_MAX_ROWS = 200_000


async def brain_usage_event_retention_days(session: AsyncSession) -> int:
    """Age gate for the per-use event log. Default 30 days; 0 disables the age gate."""
    raw = await _get_raw(session, "brain_usage_event_retention_days")
    if raw is None:
        return DEFAULT_BRAIN_USAGE_EVENT_RETENTION_DAYS
    try:
        return int(str(raw).strip())
    except ValueError:
        return DEFAULT_BRAIN_USAGE_EVENT_RETENTION_DAYS


async def brain_usage_event_max_rows(session: AsyncSession) -> int:
    """Row-count gate for the per-use event log — the gate that actually bounds a
    burst, since age alone cannot. Default 200k; 0 disables the count gate."""
    raw = await _get_raw(session, "brain_usage_event_max_rows")
    if raw is None:
        return DEFAULT_BRAIN_USAGE_EVENT_MAX_ROWS
    try:
        return int(str(raw).strip())
    except ValueError:
        return DEFAULT_BRAIN_USAGE_EVENT_MAX_ROWS


#: Read-path registry for _INT_KEYS. Defined at module bottom because it references the
#: accessors above; resolved at call time by get_settings. Every key in _INT_KEYS MUST
#: appear here — a key that is writable but not readable is a silent one-way setting
#: (see the comment in get_settings). test_settings_int_keys pins the equality.
_INT_ACCESSORS = {
    "run_debug_retention_days": run_debug_retention_days,
    "evolution_max_dispatches": evolution_max_dispatches,
    "brain_usage_event_retention_days": brain_usage_event_retention_days,
    "brain_usage_event_max_rows": brain_usage_event_max_rows,
}


#: Read-path registry for the BOOL settings. Every entry in `_BOOL_KEYS` MUST appear
#: here — a key that is writable but not readable reports the schema default forever
#: (see the comment in get_settings). `evolution_auto` is deliberately absent: it is a
#: bool in the service but a STRING ("on"/"off") on the wire, so it keeps its own line.
_BOOL_ACCESSORS = {
    "distill_on_session_end": distill_enabled,
    "curation_enabled": curation_enabled,
    "mcp_server_enabled": mcp_server_enabled,
}

#: The bool keys this registry is responsible for.
_BOOL_KEYS = tuple(_BOOL_ACCESSORS)


#: The moment curation was switched on. Everything idle BEFORE it is history and is not
#: swept; see curation_loop.ensure_backfill_boundary for why.
CURATION_BACKFILL_FROM_KEY = "curation_backfill_from"


async def curation_backfill_from(session: AsyncSession) -> datetime | None:
    """When the curation sweep's scope begins. None = not recorded yet.

    An UNPARSABLE stored value returns None rather than falling through to "no gate":
    reopening the historical backfill is the expensive direction, and it would happen
    invisibly. The loop treats None as "record a boundary now and sweep only forward",
    so a corrupt value costs a small amount of scope, never a surprise bill.
    """
    return _parse_iso_utc(await _get_raw(session, CURATION_BACKFILL_FROM_KEY))


async def clear_curation_backfill_from(session: AsyncSession) -> None:
    """Forget the boundary, so the next enable records a fresh one."""
    await _clear_raw(session, CURATION_BACKFILL_FROM_KEY)
    await session.commit()


async def set_curation_backfill_from(session: AsyncSession, dt: datetime) -> None:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    await _set_raw(session, CURATION_BACKFILL_FROM_KEY, dt.isoformat())
    await session.commit()
