"""Read/write user settings, encrypting the API key and masking it on read."""
from __future__ import annotations

import logging
import re

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import crypto
from server.db.models import Setting

from server.services.secret_state import secret_state

logger = logging.getLogger(__name__)

# Plain (non-secret) keys returned verbatim.
_PLAIN_KEYS = (
    "llm_provider", "llm_model", "llm_base_url", "language", "first_run_seen", "search_provider", "search_base_url",
               # 0.1.63 D5: how a chosen Tavily / SearXNG is used: "" or "only" (as before D5) | "backup".
               "search_provider_role",
               "llm_strategy", "distill_on_session_end", "orchestrator_shell_enabled",
               "shell_confirm_policy", "background_job_budget", "task_usd_cap", "synthesis_config_id",
               "embedding_config_id",
               # Per-task model slots (spec ②). Registered here AND on both
               # pydantic schemas — being on only one is how github_token became
               # a settings field that looked saveable and was not.
               "compaction_config_id",
               "router_config_id", "vision_config_id",
               # 0.1.58 §6: one model of the slot's config (empty = the config's own model).
               "compaction_model", "synthesis_model", "router_model", "vision_model",
               "mcp_server_enabled", "research_review_enabled", "keep_awake_enabled",
               "desktop_notifications_enabled", "island_enabled", "terminal_sandbox_enabled",
               "memory_in_conversations", "learned_practices_take_effect", "phone_bridge_enabled", "ocr_languages",
               "workspace_dir", "heartbeat_enabled", "heartbeat_checklist",
               # 0.1.56 §5: Arslan clears project levels itself ("true" | "false"; default off).
               "projects_auto_advance",
               # 0.1.58 §1: raw tool input/output under a reply's steps ("true" | "false"; default off).
               "show_technical_details",
               # 0.1.63 K7: every tool on every request ("true" | "false"; default off). No UI: M1's A/B
               # and the rollback. DELETE-BY: v0.1.64 (see arslan.RESIDENT).
               "tools_all_resident",
               # 0.1.63 K8a: show an answer only once it is complete ("true" | "false"; default off: answers
               # go out as they are written). No UI yet. DELETE-BY: v0.1.64, when v0.1.63's M1 shows streaming
               # no worse than buffering two rounds running and no issue was opened for it (card K8).
               "answer_when_complete",
               "heartbeat_interval_s", "lan_discovery_enabled", "ssh_enabled", "default_read_enabled",
               "voice_input_locale", "voice_mode", "voice_endpoint_silence_ms")
# Integer keys, handled like _PLAIN_KEYS but round-tripped through int() on read.
_INT_KEYS = ("run_debug_retention_days",
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

    await session.commit()
    if "language" in data and data["language"] is not None:
        from server.services import native_locale

        await native_locale.sync(session)


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
    # A change that moved only one of them produces a UI reporting OFF while the
    # feature runs, or the reverse.
    # Asserted complete against _BOOL_KEYS by test_settings_bool_keys.
    for bool_key, accessor in _BOOL_ACCESSORS.items():
        out[bool_key] = await accessor(session)
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


async def keep_awake_enabled(session: AsyncSession) -> bool:
    """Whether the desktop shell holds a sleep assertion while work is in flight.
    Default ON (user ruling 2026-09-26): a task started before walking away
    should finish. Only an explicit 'false' turns it off. Never fights lid-close
    or battery sleep; that is the system's call."""
    raw = await _get_raw(session, "keep_awake_enabled")
    return raw is None or str(raw).strip().lower() != "false"


async def island_enabled(session: AsyncSession) -> bool:
    """Whether Arslan shows in the notch (the island, 0.1.51). Default ON; only an
    explicit 'false' turns it off. It spends nothing and only shows what is on."""
    raw = await _get_raw(session, "island_enabled")
    return raw is None or str(raw).strip().lower() != "false"


async def desktop_notifications_enabled(session: AsyncSession) -> bool:
    """Whether the desktop shell posts native notifications while its window is
    hidden. Default ON; only an explicit 'false' turns it off."""
    raw = await _get_raw(session, "desktop_notifications_enabled")
    return raw is None or str(raw).strip().lower() != "false"


async def memory_in_conversations(session: AsyncSession) -> bool:
    """"Remember me and use it in conversations" (0.1.52 P4a, user decision D1).
    Default ON: what Arslan remembers reaches the chosen model, cloud models
    included; sensitive entries still need the per-conversation allowance. Only
    an explicit 'false' turns it off (back to the 0.1.51 behaviour)."""
    raw = await _get_raw(session, "memory_in_conversations")
    return raw is None or str(raw).strip().lower() != "false"


async def learned_practices_take_effect(session: AsyncSession) -> bool:
    """"Learned practices take effect" (0.1.52 S5, D2). Default ON: a practice from
    the user's own correction, or from a detour in a turn that read nothing from
    outside, is used at once (visible, undoable). Off: every learned practice waits
    for the user's OK. Only an explicit 'false' turns it off."""
    raw = await _get_raw(session, "learned_practices_take_effect")
    return raw is None or str(raw).strip().lower() != "false"


async def phone_bridge_enabled(session: AsyncSession) -> bool:
    """"Use Arslan from your iPhone" (mobile bridge §6.1). Default OFF: the Arslan Bridge
    polls iCloud every few seconds, which nobody without an iPhone should pay for. Only an
    explicit 'true' turns it on; the desktop shell starts or stops the Bridge from this."""
    raw = await _get_raw(session, "phone_bridge_enabled")
    return raw is not None and str(raw).strip().lower() == "true"


async def terminal_sandbox_enabled(session: AsyncSession) -> bool:
    """Whether run_command runs inside the workspace sandbox (0.1.51 P3). Default
    ON; only an explicit 'false' turns it off (back to the 0.1.50 behaviour)."""
    raw = await _get_raw(session, "terminal_sandbox_enabled")
    return raw is None or str(raw).strip().lower() != "false"


async def research_review_enabled(session: AsyncSession) -> bool:
    """Whether a saved multi-source research report gets an advisory source
    review after saving. Default OFF (user ruling 2026-09-26): it spends one
    extra model request on the user's key per qualifying save, and its false-
    positive rate is being calibrated. Never a gate on saving."""
    raw = await _get_raw(session, "research_review_enabled")
    return raw is not None and str(raw).strip().lower() == "true"


async def answer_when_complete(session: AsyncSession) -> bool:
    """K8a: answers shown only when complete, as before K8. Default off. DELETE-BY: v0.1.64 (card K8)."""
    raw = await _get_raw(session, "answer_when_complete")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def tools_all_resident(session: AsyncSession) -> bool:
    """K7: every tool on every request, as before tools were found on demand. Default off.
    DELETE-BY: v0.1.64, with the key (see arslan.RESIDENT)."""
    raw = await _get_raw(session, "tools_all_resident")
    return str(raw).strip().lower() == "true" if raw is not None else False


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


def default_workspace():
    """Arslan's own folder: ~/Arslan (0.1.48). Tests point it elsewhere through
    ARSLAN_DEFAULT_WORKSPACE so a test run never touches the user's home."""
    import os
    from pathlib import Path

    override = os.environ.get("ARSLAN_DEFAULT_WORKSPACE", "").strip()
    return Path(override).expanduser() if override else Path.home() / "Arslan"


async def workspace_dir(session: AsyncSession):
    """The directory Arslan's file tools may work in.

    0.1.48: there is always one. With nothing chosen it is Arslan's own folder
    (`default_workspace()`, created on first use), so writing a report or a list is
    something Arslan can simply do. Before this, the default was "none", the write
    tools were not registered at all, and a job that had found 34 postings could not
    save them. A chosen folder that no longer exists reads as unset (None), as before:
    Arslan must not quietly write somewhere else than the user picked."""
    from pathlib import Path

    raw = await _get_raw(session, "workspace_dir")
    if raw is None or not str(raw).strip():
        path = default_workspace()
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path.resolve()
        except OSError:
            return None
    try:
        path = Path(str(raw).strip()).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    return path if path.is_dir() else None


async def workspace_is_default(session: AsyncSession) -> bool:
    """True when Arslan is working in its own folder rather than one the user chose."""
    raw = await _get_raw(session, "workspace_dir")
    return raw is None or not str(raw).strip()


async def shell_enabled(session: AsyncSession) -> bool:
    """Whether Arslan has its terminal (run_command). 0.1.48: ON unless switched off —
    without it every skill that is a command-line tool is dead text. What it may run
    is terminal_policy's job, not this switch's."""
    raw = await _get_raw(session, "orchestrator_shell_enabled")
    return str(raw).strip().lower() != "false" if raw is not None else True


async def mcp_server_enabled(session: AsyncSession) -> bool:
    """Whether the inbound MCP server mount accepts requests. Default OFF (opt-in):
    only an explicit 'true' enables it (lowercased so a stored 'True' still matches)."""
    raw = await _get_raw(session, "mcp_server_enabled")
    return str(raw).strip().lower() == "true" if raw is not None else False


async def shell_confirm_policy(session: AsyncSession) -> str:
    """'ask_risky' (0.1.48 default): harmless commands run, the rest show a card.
    'ask_all': every command shows a card (only an explicit choice gives this)."""
    raw = await _get_raw(session, "shell_confirm_policy")
    return "ask_all" if str(raw).strip().lower() == "ask_all" else "ask_risky"


async def background_job_budget(session: AsyncSession) -> str:
    """The work budget tier (0.1.43 for background jobs; K4a, v0.1.63: for chat turns too):
    lean | standard | ample. Anything else is the default tier. The key keeps its 0.1.43 name."""
    from arslan.execution_budget import DEFAULT_TIER, TIERS
    raw = str(await _get_raw(session, "background_job_budget") or "").strip().lower()
    return raw if raw in TIERS else DEFAULT_TIER


async def task_usd_cap(session: AsyncSession) -> float:
    """The per-task dollar cap (K4a): $2 by default; anything unreadable or not above zero is the default,
    and at most MAX_USD_CAP."""
    import math

    from arslan.execution_budget import DEFAULT_USD_CAP, MAX_USD_CAP
    try:
        value = float(str(await _get_raw(session, "task_usd_cap") or "").strip())
    except ValueError:
        return DEFAULT_USD_CAP
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_USD_CAP
    return min(value, MAX_USD_CAP)


async def run_budget_from_settings():
    """The budget of a run that starts at an entry point (`execution_budget.governed`, a chat turn): the
    tier the user picked. Registered at startup (server/main.py); the default tier if settings can't be
    read."""
    from arslan.execution_budget import run_budget
    from server.db import session as db_session
    try:
        async with db_session.AsyncSessionLocal() as db:
            return run_budget(await background_job_budget(db), usd_cap=await task_usd_cap(db))
    except Exception:  # noqa: BLE001 — a run must not fail to start over its budget tier
        logger.warning("work budget tier not read; using the default", exc_info=True)
        return run_budget()


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
    "brain_usage_event_retention_days": brain_usage_event_retention_days,
    "brain_usage_event_max_rows": brain_usage_event_max_rows,
}


#: Read-path registry for the BOOL settings. Every entry in `_BOOL_KEYS` MUST appear
#: here — a key that is writable but not readable reports the schema default forever
#: (see the comment in get_settings).
async def first_run_seen(session: AsyncSession) -> bool:
    """Whether onboarding was dismissed or completed. Default False."""
    return _truthy(await _get_raw(session, "first_run_seen"))


_BOOL_ACCESSORS = {
    "first_run_seen": first_run_seen,
    "distill_on_session_end": distill_enabled,
    "research_review_enabled": research_review_enabled,
    "keep_awake_enabled": keep_awake_enabled,
    "desktop_notifications_enabled": desktop_notifications_enabled,
    "island_enabled": island_enabled,
    "terminal_sandbox_enabled": terminal_sandbox_enabled,
    "memory_in_conversations": memory_in_conversations,
    "learned_practices_take_effect": learned_practices_take_effect,
    "phone_bridge_enabled": phone_bridge_enabled,
    "mcp_server_enabled": mcp_server_enabled,
}

#: The bool keys this registry is responsible for.
_BOOL_KEYS = tuple(_BOOL_ACCESSORS)

