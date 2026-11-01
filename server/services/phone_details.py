"""One conversation as the Mac runs it, for the phone's conversation details (IPB,
docs/plans/0164/IPB-frame-list.md §3): `chat.history.result.details`. The Mac does the sums: the phone
sees at most 40 steps of a run and 200 messages, so it would undercount.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.companion_models import ConversationContext
from server.db.models import ConversationModel, MCPServer, ProviderConfig, Run, RunStep, SkillPack
from server.services import folder_rules, phone_ids, phone_reads

CHANGE_TOOLS = ("edit_file", "write_file")
#: Hands first, then the ones that are on (frame list §3).
CONNECTORS_MAX = 30


def _home() -> Path:
    return Path.home()


async def details(db: AsyncSession, conversation_id: str) -> dict:
    """The block, every optional field left out when the Mac doesn't know it; `connectors` is always there
    (`[]` when none), as the phone's decoder requires it."""
    out: dict = {}
    if (folder := await folder_rules.conversation_folder(db, conversation_id)) is not None:
        out["folder"] = shown_folder(folder, _home())
    if (model := await _model(db, conversation_id)) is not None:
        out["model"] = model
    from server.services import permissions
    out["mode"] = await permissions._mode()          # the one the cards follow (global until per-conversation modes)
    out["connectors"] = await _connectors(db, conversation_id)
    if (changes := await _changes(db, conversation_id)) is not None:
        out["changes"] = changes
    if (spent := await _spent(conversation_id)) is not None:
        out["spent_usd"] = spent
    return out


def shown_folder(folder: Path | str, home: Path | str) -> str:
    """A folder for display on the phone, its home part as `~`, so the absolute home path never leaves.
    Both are resolved first (a home or a folder reached by a link), and compared part by part ignoring
    case, as the startup volume does."""
    real, base = Path(os.path.realpath(folder)), Path(os.path.realpath(home))
    parts, prefix = real.parts, base.parts
    if len(parts) >= len(prefix) and [p.casefold() for p in parts[:len(prefix)]] == [p.casefold() for p in prefix]:
        rest = parts[len(prefix):]
        return "~/" + "/".join(rest) if rest else "~"
    return str(real)


async def _model(db: AsyncSession, conversation_id: str) -> str | None:
    """The model the conversation's turns run on: its own choice while its provider config exists, else the
    primary config's model (no choice is the default, models.ConversationModel). A routing strategy other
    than the default "single" may pick another config per turn; this names the default's. The model id is
    sent as it is: display names live only in the model catalog, which only Settings reads."""
    chosen = await db.get(ConversationModel, conversation_id)
    if chosen is not None and await db.get(ProviderConfig, chosen.config_id) is not None:
        return chosen.model
    return (await db.execute(select(ProviderConfig.model).order_by(ProviderConfig.is_primary.desc(), ProviderConfig.id)
                             .limit(1))).scalar()


async def _connectors(db: AsyncSession, conversation_id: str) -> list[dict]:
    """Hands, the MCP servers and the skills, each `on` when this conversation's turns get it: Hands switched
    on, an MCP server switched on and connected in this process (what a turn is offered, arslan.py), a skill
    switched on. A quick question gets none of them (only its read-only tools). Named by display name only:
    an MCP server by its label (`executor.label_of`), never its URL, command or arguments, which can hold a
    credential (SEC1)."""
    from server.mcp import executor, supervisor
    from server.registry import hands_tools
    from server.services import hands_client
    context = await db.get(ConversationContext, conversation_id)
    quick = phone_ids.kind_of(conversation_id, context.kind if context else None) == "quick"
    hands = ([{"name": "Hands", "kind": "hands", "on": not quick and hands_tools.desktop_available()}]
             if hands_client.available() else [])
    others = [{"name": executor.label_of(server), "kind": "mcp",
               "on": not quick and bool(server.host_allowed) and supervisor.ready_now(server.id, server.state)}
              for server in (await db.execute(select(MCPServer).order_by(MCPServer.id))).scalars()]
    others += [{"name": pack.name or pack.key, "kind": "skill", "on": not quick and pack.enabled is not False}
               for pack in (await db.execute(select(SkillPack).where(
                   SkillPack.status == "registered", SkillPack.body.is_not(None), func.trim(SkillPack.body) != "",
               ).order_by(SkillPack.key))).scalars()]
    others.sort(key=lambda c: not c["on"])             # stable: the ones that are on first, each kind in its order
    return (hands + others)[:CONNECTORS_MAX]


async def _changes(db: AsyncSession, conversation_id: str) -> dict | None:
    """What the edit and write steps changed over every run of the conversation, from each step's recorded
    review (tool_review): distinct paths, lines added and removed, and the newest run that changed a file.
    A change made by a shell command isn't counted (the protocol spec says so), and a very large edit
    counts only its recorded snippet."""
    paths: set[str] = set()
    added = removed = 0
    last = None
    for run_id, ref, detail in (await db.execute(
            select(RunStep.run_id, RunStep.ref, RunStep.detail).join(Run, RunStep.run_id == Run.id)
            .where(Run.conversation_id == conversation_id, Run.kind != "replay", RunStep.kind == "tool_call",
                   RunStep.ref["tool"].as_string().in_(CHANGE_TOOLS)))).all():
        review = (detail or {}).get("review")
        if not (ref or {}).get("ok") or not isinstance(review, dict):
            continue
        if review.get("kind") == "edit":
            _, plus, minus = phone_reads.change_lines(review.get("old") or "", review.get("new") or "")
        elif review.get("kind") == "write":
            lines = review.get("lines")
            # A step recorded before `lines` existed has only its head.
            plus, minus = (lines if isinstance(lines, int) else len((review.get("head") or "").splitlines())), 0
        else:
            continue
        added, removed = added + plus, removed + minus
        if review.get("path"):
            paths.add(review["path"])
        last = run_id if last is None else max(last, run_id)
    if last is None:
        return None
    return {"files": len(paths), "added": added, "removed": removed, "last_run_id": last}


async def _spent(conversation_id: str) -> float | None:
    from server.api.usage import fetch_usage_items, item_usd
    total = None
    for _scope, provider, model, tokens_in, tokens_out, estimated, _tokens, _ts in await fetch_usage_items(
            conversation_id=conversation_id):
        if (usd := item_usd(model, tokens_in, tokens_out, estimated, provider)) is not None:
            total = (total or 0.0) + usd
    return None if total is None else round(total, 4)
