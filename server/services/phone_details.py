"""One conversation as the Mac runs it, for the phone's conversation details (IPB,
docs/plans/0164/IPB-frame-list.md §3): `chat.history.result.details`. The Mac does the sums: the phone
sees at most 40 steps of a run and 200 messages, so it would undercount.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote

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
        out["model"] = shown_model(model)
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
    Both are resolved first (a home or a folder reached by a link). Then the folder and each of its parents is
    compared with the home part by part, in one Unicode form and ignoring case, as the startup volume does,
    or found to be the same directory (the Data volume's firmlink, /System/Volumes/Data/Users/…; #650 review).
    A folder outside the home is shown by its last part only, so no volume or full path leaves the Mac (the user,
    2026-11-01)."""
    real, base = Path(os.path.realpath(folder)), Path(os.path.realpath(home))

    def folded(parts) -> list[str]:
        return [unicodedata.normalize("NFC", part).casefold() for part in parts]

    for depth in range(len(real.parts), 0, -1):          # the folder itself, then each parent
        ancestor, rest = Path(*real.parts[:depth]), real.parts[depth:]
        same = folded(ancestor.parts) == folded(base.parts)
        if not same:
            try:
                same = os.path.samefile(ancestor, base)
            except OSError:
                same = False
        if same:
            return "~/" + "/".join(rest) if rest else "~"
    return real.name or str(real)


def _fold_home(text: str) -> str:
    """The home folder in free text as `~` (`home_text.fold_home`: only a whole path, next to any script)."""
    from server.services import home_text
    return home_text.fold_home(text, str(_home()))


def _decoded(text: str) -> str:
    """`text` as the home check reads it: NFKC, percent-decoded until it stops changing (`%252F…`), and with
    JSON-escaped slashes as slashes."""
    flat = unicodedata.normalize("NFKC", text)
    for _ in range(5):
        decoded = unquote(flat)
        if decoded == flat:
            break
        flat = decoded
    return flat.replace("\\/", "/")


def _names_home(text: str) -> bool:
    """Whether `text` still names the home folder in any form `fold_home` does not read: percent-encoded (even
    twice), full-width, with JSON-escaped slashes, under `file://localhost` or the Data volume (#650 reviews)."""
    home = str(_home()).rstrip("/")
    return bool(home) and home.casefold() in _decoded(text).casefold()


def _shown_name(text: str, fallback: str) -> str:
    """A typed name for the phone: anything in it that looks like a secret masked as a server's address and
    arguments are (`connection_secrets.shown`, and an `Authorization: Bearer …` value), the home folder as `~`,
    and `fallback` instead when it still names the home in another form (fail closed)."""
    from server.services import connection_secrets
    masked = " ".join(connection_secrets.shown(None, text.split(" "))[1])
    masked = re.sub(r"(?i)(\b(?:authorization\s*:\s*(?:bearer|basic)\s+|x-api-key\s*:\s*))\S+", r"\1●●●●", masked)
    folded = _fold_home(masked)
    return fallback if not folded or _names_home(folded) else folded


#: An id that is a file path, in any of the forms a local server reports or a user pastes (#650 delta review).
_PATH_ID = re.compile(r"""^(?:[/~\\"']|file:|\.\.?[/\\]|[A-Za-z]:[/\\])|[/\\](?:users|home)[/\\]""", re.I)


def shown_model(model: str) -> str:
    """A model id for the phone: one clean line of at most 200 characters (an id has no length limit, and
    `details` is kept whole in the history envelope), and only the last part of an id that is a path
    (llama.cpp without `--alias` names a model by its file, which can be under the home folder; #650 review).
    A router's `vendor/model` id is not a path. Fail closed: an id that still names the home is its last part."""
    from server.orchestrator import untrusted
    clean = untrusted.clean_name(model, 200)
    last = re.split(r"[/\\]", clean.strip("\"'"))[-1] or clean
    if _PATH_ID.search(clean):
        clean = last
    clean = _fold_home(clean)
    if _names_home(clean):                              # read as the check reads it, then its last part
        return re.split(r"[/\\]", _decoded(clean))[-1]
    return clean


def _connector_name(server) -> str:
    """An MCP server's display name: its label (any script, at most 80 characters), masked and folded
    (`_shown_name`), with its own secret values masked too (`supervisor.mask_for`). A server whose secrets can't
    be read is named by its number, never by a label that could not be checked against them."""
    from server.mcp import discovery, supervisor
    from server.orchestrator import untrusted
    from server import crypto
    fallback = f"MCP {server.id}"
    try:
        for column in (server.env, getattr(server, "secrets", None)):
            # runtime_dict reads an undecryptable or malformed column as {}, silently: check both first.
            if column and not isinstance(json.loads(crypto.decrypt(column)), dict):
                return fallback
        runtime = discovery.runtime_dict(server)
    except Exception:  # noqa: BLE001 — unreadable: named by its number
        return fallback
    return _shown_name(supervisor.mask_for(runtime, untrusted.clean_name(server.label, 80)), fallback)


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
    an MCP server by its label, never its URL, command or arguments, which can hold a
    credential (SEC1), with anything secret-looking in the label masked (`_connector_name`)."""
    from server.mcp import supervisor
    from server.registry import hands_tools
    from server.services import hands_client
    context = await db.get(ConversationContext, conversation_id)
    quick = phone_ids.kind_of(conversation_id, context.kind if context else None) == "quick"
    hands = ([{"name": "Hands", "kind": "hands", "on": not quick and hands_tools.desktop_available()}]
             if hands_client.available() else [])
    others = [{"name": _connector_name(server), "kind": "mcp",
               "on": not quick and bool(server.host_allowed) and supervisor.ready_now(server.id, server.state)}
              for server in (await db.execute(select(MCPServer).order_by(MCPServer.id))).scalars()]
    from server.orchestrator import untrusted
    others += [{"name": _shown_name(untrusted.clean_name(pack.name or pack.key, 80), pack.key), "kind": "skill",
                "on": not quick and pack.enabled is not False}
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
                   RunStep.ref["tool"].as_string().in_(CHANGE_TOOLS))
            .order_by(RunStep.run_id.desc(), RunStep.seq.desc()))).all():
        review = (detail or {}).get("review")
        if not (ref or {}).get("ok") or not isinstance(review, dict):
            continue
        if review.get("kind") == "edit":
            if isinstance(review.get("added"), int) and isinstance(review.get("removed"), int):
                plus, minus = review["added"], review["removed"]          # counted when the step was recorded
            else:                                                         # a step recorded before the counts
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
