"""SMART-2 (v0.1.64, docs/plans/0164/SMART-feels-smart.md): what Arslan knows about itself, read live each time the
`my_status` tool runs. Asked "which model are you on / is the sandbox on / what can you reach / what failed", it
answers from this, never from memory or from a folder it guessed on this Mac.

Nothing private leaves here: phones by the name the user gave them (no device id), SSH hosts by their enrolled name
(no address or user), failures by what failed and when (never the command, the file or the error text).
"""
from __future__ import annotations

from sqlalchemy import func, select

from server.db import session as db_session
from server.db.models import ApprovalEvent, ConversationModel, ProviderConfig, Run, RunStep, SshNode
from server.services import phone_bridge, release_notes, settings_service

FAILURES = 5
NOTES_MAX = 600
#: Where Arslan's own code and plans are: the public repository's main branch. A copy on this Mac may be old or
#: someone's work in progress, so it is never the answer to "what is planned" or "how does this work".
SOURCE = {
    "repository": "https://github.com/mirzatghayrat/arslan",
    "branch": "main",
    "plans": "docs/plans/ on main (the newest numbered folder is the version being planned)",
    "note": "Read these on GitHub, not a folder on this Mac.",
}
APPROVALS = {"ask_all": "every command asks", "ask_risky": "harmless commands run, the rest ask"}


def _at(moment) -> str:
    return moment.replace(microsecond=0).isoformat() + "Z"


async def _model(db, config_id=None, model=None) -> dict | None:
    query = select(ProviderConfig.provider, ProviderConfig.model)
    query = query.where(ProviderConfig.id == config_id) if config_id is not None else query.where(ProviderConfig.is_primary)
    row = (await db.execute(query.limit(1))).first()
    return None if row is None else {"model": model or row.model, "provider": row.provider}


async def _failures(db) -> list[dict]:
    """The newest failures of three kinds, merged: a tool call that failed, a card that was refused, a run that
    ended in an error."""
    at = func.coalesce(RunStep.started_at, Run.started_at)
    tools = (await db.execute(
        select(RunStep.ref, at).join(Run, Run.id == RunStep.run_id)
        .where(RunStep.kind == "tool_call", RunStep.ref["ok"].as_boolean().is_(False))
        .order_by(at.desc(), RunStep.id.desc()).limit(FAILURES))).all()
    refused = (await db.execute(
        select(ApprovalEvent.kind, ApprovalEvent.decided_by, ApprovalEvent.created_at)
        .where(ApprovalEvent.decision == "deny").order_by(ApprovalEvent.id.desc()).limit(FAILURES))).all()
    runs = (await db.execute(
        select(Run.error_kind, Run.started_at).where(Run.error_kind.is_not(None), Run.kind != "replay")
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(FAILURES))).all()
    found = ([(when, f"tool {(ref or {}).get('tool') or 'call'} failed") for ref, when in tools]
             + [(when, f"refused: {kind} (by {by})") for kind, by, when in refused]
             + [(when, f"run failed: {kind}") for kind, when in runs])
    found.sort(key=lambda item: item[0], reverse=True)
    return [{"what": what, "at": _at(when)} for when, what in found[:FAILURES]]


async def snapshot(conversation_id: str | None = None) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        models = {"chat": await _model(db), "quick_ask": "same as chat"}
        if conversation_id:
            picked = await db.get(ConversationModel, conversation_id)
            if picked is not None and (mine := await _model(db, picked.config_id, picked.model)) is not None:
                models["this_conversation"] = mine
        safety = {
            "command_sandbox": "on" if await settings_service.terminal_sandbox_enabled(db) else "off",
            "approvals": APPROVALS[await settings_service.shell_confirm_policy(db)],
            "local_network_scan": "on" if await settings_service.lan_discovery_enabled(db) else "off",
        }
        hosts = list((await db.execute(select(SshNode.name).order_by(SshNode.name))).scalars())
        failures = await _failures(db)
    hub = phone_bridge.hub
    return {
        "version": release_notes.settings.app_version,
        "whats_new": [{"version": r["version"], "notes": r["notes"][:NOTES_MAX]} for r in release_notes.recent(1)],
        "models": models,
        "safety": safety,
        "reach": {"iphone_bridge": "connected" if hub.connected else "not connected",
                  "phones": [d.get("name") or "iPhone" for d in hub.devices], "ssh_hosts": hosts},
        "recent_failures": failures,
        "source": SOURCE,
    }
