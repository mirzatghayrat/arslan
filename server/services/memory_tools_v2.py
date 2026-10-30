"""Unified-memory implementation of legacy recall/remember tool names."""
from dataclasses import replace
from datetime import UTC

from pydantic import ValidationError
from sqlalchemy import select

from arslan.companion.memory import MemoryError, MemoryScope, MemoryWrite
from server.db.models import MemoryEntry, MemoryRevision
from server.services import personal_context as pc
from server.services.memory_repository import repository


async def _about_you(actor, ctx):
    """INB2: the turn's own state for a new "about you" entry: the user present (the allowlist,
    server/services/presence.py) and the whole conversation clean: everything this turn took in is on the
    user's allowlist (untrusted.known_local: nothing attached, no project knowledge, only known-local tools;
    #475 F2), and every other run of the conversation recorded the same (`runs.read_outside`; no record,
    NULL, counts as off it: older runs, a crashed one, a job still running). Off the list too: a turn with a
    note or practice in view that came from a run off it, or with the project card (#475 H1/H2)."""
    from sqlalchemy import or_

    from server.db import session as db_session
    from server.db.models import Run
    from server.orchestrator import run_trace, untrusted
    from server.services import presence
    # This turn and every earlier turn of this run (#475 review, F5); with no conversation whose other runs can
    # be checked, nothing is known to be clean (F7).
    clean = untrusted.known_local() and run_trace.outside() is not True and bool(ctx.conversation_id)
    if clean:
        async with db_session.AsyncSessionLocal() as db:
            query = select(Run.id).where(Run.conversation_id == ctx.conversation_id,
                                         or_(Run.read_outside.is_(None), Run.read_outside.is_(True)))
            if ctx.source_run_id is not None:
                query = query.where(Run.id != ctx.source_run_id)
            clean = (await db.execute(query.limit(1))).first() is None
    return replace(actor, user_present=presence.present(), conversation_clean=clean)


# #475 H1 (the user, 2026-10-29): entries that took effect as the user's words or choice, or as an "about you"
# entry from a clean conversation. Every other entry in a turn's context (Arslan's notes, and any kind added
# later) is traced back to the run that wrote it.
USER_KINDS = frozenset({"user_form", "explicit_user_request", "legacy_user_edit", "legacy_manual", "auto_noticed",
                        "arslan_about_you"})


async def from_off_the_list(used) -> bool:
    """#475 H1 (the user, 2026-10-29): whether a memory entry in a turn's context (its receipt's `used`) came
    from a run off the list, which puts the turn off it too (untrusted.off_list_in), so what it writes or says
    counts the same later. The version in view is traced: one the user wrote or switched on (a source of
    theirs) is clean; otherwise every run its sources name must have recorded `runs.read_outside` false. No
    run named, a run that is not there, or NULL counts as off the list."""
    from server.db import session as db_session
    from server.db.companion_models import MemorySource
    from server.db.models import Run
    shown = {(ref.id, ref.revision) for ref in used if ref.kind == "memory"}
    if not shown:
        return False
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(MemoryEntry.id, MemoryEntry.confirmation_kind, MemoryRevision.id,
                                        MemoryRevision.version).join(
            MemoryRevision, MemoryRevision.entry_id == MemoryEntry.id).where(
            MemoryEntry.id.in_({entry for entry, _ in shown})))).all()
        traced = {revision for entry, kind, revision, version in rows
                  if (entry, version) in shown and kind not in USER_KINDS}
        if not traced:
            return False
        sources = (await db.scalars(select(MemorySource).where(MemorySource.revision_id.in_(traced)))).all()
        named = {source.source_ref.get("run_id") for source in sources} - {None}
        clean = set((await db.scalars(select(Run.id).where(Run.id.in_(named), Run.read_outside.is_(False)))).all())
    for revision in traced:
        mine = [source for source in sources if source.revision_id == revision]
        if any(source.author == "user" for source in mine):
            continue
        if not mine or any(source.source_ref.get("run_id") not in clean for source in mine):
            return True
    return False


def _flagged(args, sensitivity: str = "normal") -> str:
    """#475 F4 (the user, 2026-10-29): Arslan may add `sensitive: true` to a write. It only ever makes the
    write stricter: normal or unknown becomes sensitive; leaving it out or saying false changes nothing, and
    decide_write's keywords still apply. Judging sensitivity by category is later."""
    return "sensitive" if args.get("sensitive") and sensitivity in ("normal", "unknown") else sensitivity


async def _same_meaning(content: str, kind: str, scope, core, args, ctx):
    """MEM1: the entry this new one would repeat in other words (memory_merge), or None."""
    from server.services import memory_merge
    return await memory_merge.same_meaning(content, ctx=ctx, kind=kind, scope=scope, core=core,
                                           sensitive=_flagged(args) != "normal")


def _tell_the_window(ctx, result: dict) -> None:
    """INB2: the chat line after a turn. A new entry that took effect reads "remembered … [Undo]"
    (fact_saved); one that waits names its proposal, version, text and reason (memory_proposed), so a
    sensitive one's two buttons answer exactly that proposal. Window socket only; the Bridge never
    forwards these frames (desktop/bridge FrameMapper maps a fixed list of types)."""
    from server.services import run_registry
    if not ctx.conversation_id or not result.get("ok") or not result.get("id"):
        return
    if result.get("status") not in ("active", "proposed"):
        return          # #475 recheck, G2: it landed on a paused or quarantined entry: nothing was remembered
    waiting = result.get("status") == "proposed"
    frame = {"type": "memory_proposed" if waiting else "fact_saved", "content": result.get("content"),
             "sensitive": result.get("sensitivity", "normal") != "normal",
             "entry_id": result.get("id"), "version": result.get("version")}
    if waiting:
        frame |= {"proposal_id": result.get("proposal_id"), "reason": result.get("reason")}
    run_registry.make_emit(ctx.conversation_id)(frame)     # each window is isolated there: a dead one breaks nothing


def _context(caller):
    ctx = pc.current()
    if ctx is None or caller is None or caller.actor not in {"host", "spawn"}:
        return None
    if caller.actor == "spawn":
        if caller.spawn_id is None:
            return None
        return pc.worker_context(ctx, str(caller.spawn_id))
    return ctx


async def recall(args, caller):
    ctx = _context(caller)
    if ctx is None:
        return {"ok": True, "hits": [], "reason": "memory_context_unavailable"}
    query = str(args.get("query") or "")
    result = await pc.assemble(query, context=ctx)
    hits = [{"kind": "memory", "content": result.text,
             "references": [ref.model_dump(mode="json") for ref in result.receipt.used]}] if (
                 result.text and args.get("kind") in {None, "fact", "learning", "preference"}) else []
    if hits:
        with pc.bind(ctx):
            await pc.record(result)
    if query and args.get("kind") in {None, "material"}:
        from server.services import knowledge
        with pc.bind(ctx):
            materials = await knowledge.retrieve_scoped(query, spawn_id=caller.spawn_id, record_usage=False)
        hits.extend({"kind": "material", "content": content, "source": source} for source, content in materials)
    return {"ok": True, "hits": hits,
            "receipt": result.receipt.model_dump(mode="json")}


async def remember(args, caller):
    ctx = _context(caller)
    if ctx is None:
        return {"ok": False, "code": "memory_context_unavailable"}
    if ctx.no_learning or ctx.temporary:
        return {"ok": False, "code": "learning_disabled"}
    action = args.get("action")
    if action in {"delete", "mark_stale"}:
        return {"ok": False, "code": "user_confirmation_required",
                "next_action": "open_memory_settings"}
    if args.get("kind") not in {"fact", "learning", "preference"} or action not in {"append", "supersede"}:
        return {"ok": False, "code": "unsupported_memory_action"}
    actor = ctx.actor("worker" if caller.actor == "spawn" else "host")
    scope = MemoryScope(kind="expert", id=ctx.expert_id) if caller.actor == "spawn" else (
        MemoryScope(kind="project", id=ctx.project_id) if ctx.project_id else MemoryScope(kind="global"))
    kind = "experience" if args.get("kind") == "learning" else "preference"
    if action == "append" and caller.actor == "host" and kind == "preference":
        actor = await _about_you(actor, ctx)                  # INB2: a new "about you" entry only
    content = str(args.get("content") or "")
    match = await _same_meaning(content, kind, scope, None, args, ctx) if action == "append" else None
    try:
        async with repository() as repo:
            if action == "append":
                write = MemoryWrite(content=content, kind=kind, scope=scope, sensitivity=_flagged(args))
                result = (await repo.merge_into(match.id, match.version, write, actor) if match else None) \
                    or await repo.create(write, actor)
            else:
                target = args.get("target_id")
                if not isinstance(target, int) or isinstance(target, bool):
                    return {"ok": False, "code": "memory_target_required"}
                table = "learnings" if kind == "experience" else "user_facts"
                entry = await repo.by_compatibility_id(table, target)
                if (entry.scope_kind, entry.scope_id) != (scope.kind, scope.id):
                    return {"ok": False, "code": "memory_scope_denied"}
                expected = args.get("expected_version")
                if not isinstance(expected, int) or isinstance(expected, bool):
                    return {"ok": False, "code": "memory_version_required"}
                revision = await repo.db.get(MemoryRevision, entry.current_revision_id)
                # A model's supersede is an edit proposal, even when a previous
                # explicit save request exists. Replacing confirmed text needs UI
                # review of the exact old/new versions.
                result = await repo.revise(entry.id, expected, MemoryWrite(
                    content=str(args.get("content") or ""), kind=entry.kind, scope=scope,
                    sensitivity=_flagged(args, entry.sensitivity), use_policy=entry.use_policy,
                    topic=(revision.structured_value or {}).get("topic"),
                    valid_from=entry.valid_from.replace(tzinfo=UTC) if entry.valid_from else None,
                    review_at=entry.review_at.replace(tzinfo=UTC) if entry.review_at else None,
                    expires_at=entry.expires_at.replace(tzinfo=UTC) if entry.expires_at else None,
                ), replace(actor, explicit_save_ref=None, allow_global_save=False))
        out = {"ok": True, **result, "saved": result.get("status") == "active",
               "requires_confirmation": result.get("status") == "proposed"}
        # MEM1: a refresh is not a new memory; a proposal a merge made or joined is announced (②Main's L2).
        if action == "append" and kind == "preference" and caller.actor == "host" and (
                not result.get("merged") or result.get("proposal_id")):
            _tell_the_window(ctx, out)
        return out
    except MemoryError as exc:
        return {"ok": False, "code": exc.code}
    except ValidationError:
        return {"ok": False, "code": "invalid_memory_input"}


NOTE_SETS = {"about_you": ("preference", pc.CORE_ABOUT_YOU_CHARS), "notes": ("experience", pc.CORE_NOTES_CHARS)}


async def _note_set(repo, owner_id: str, member: str) -> list[dict]:
    kind = NOTE_SETS[member][0]
    rows = (await repo.db.execute(select(MemoryEntry, MemoryRevision).join(
        MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id,
    ).where(MemoryEntry.owner_id == owner_id, MemoryEntry.kind == kind, MemoryEntry.scope_kind == "global",
            MemoryEntry.status.in_(("active", "proposed"))).order_by(MemoryEntry.updated_at.desc()))).all()
    return [{"id": entry.id, "version": entry.version, "status": entry.status,
             "text": " ".join((revision.content or "").split())}
            for entry, revision in rows if (revision.structured_value or {}).get("core") == member]


async def note(args, caller):
    """0.1.52 S4: memory_note — edit the two always-in-view sets by entry id.

    "about_you" follows the normal write rules: active only when it is the user's own
    explicit save request, otherwise a proposal. "notes" (facts about this Mac and
    setup) take effect at once only when this turn read nothing from outside
    (D2); after web, file or command output the same write is a proposal. "remove"
    takes an entry out of the set; deleting stays the user's (Brain)."""
    from server.orchestrator import untrusted
    if caller is None or caller.actor != "host":
        return {"ok": False, "code": "memory_note_host_only"}
    ctx = _context(caller)
    if ctx is None:
        return {"ok": False, "code": "memory_context_unavailable"}
    if ctx.no_learning or ctx.temporary:
        return {"ok": False, "code": "learning_disabled"}
    action, member = args.get("action"), args.get("set")
    if action not in {"add", "replace", "remove"} or member not in NOTE_SETS:
        return {"ok": False, "code": "unsupported_memory_action"}
    kind, cap = NOTE_SETS[member]
    text = " ".join(str(args.get("text") or "").split())
    if action != "remove" and not text:
        return {"ok": False, "code": "memory_text_required"}
    actor = ctx.actor("host")
    if member == "notes":
        actor = replace(actor, auto_activate_own_notes=not untrusted.external_seen())
    elif action == "add":
        actor = await _about_you(actor, ctx)                  # INB2: a new "about you" entry only
    match = await _same_meaning(text, kind, MemoryScope(kind="global"), member, args, ctx) if action == "add" else None
    try:
        async with repository() as repo:
            current = await _note_set(repo, ctx.owner_id, member)
            used = sum(len(row["text"]) for row in current if row["status"] == "active")
            listing = {"set": member, "limit_chars": cap, "used_chars": used, "entries": current}
            merged = await repo.merge_into(match.id, match.version, MemoryWrite(
                content=text, kind=kind, scope=MemoryScope(kind="global"), core=member,
                sensitivity=_flagged(args)), actor) if match else None
            if merged is not None:
                result = merged                               # MEM1: nothing added to the set
                if member == "about_you" and merged.get("proposal_id"):
                    _tell_the_window(ctx, {"ok": True, **merged})
            elif action == "add":
                if used + len(text) > cap:
                    return {"ok": False, "code": "core_set_full", **listing,
                            "next_action": "replace or remove an entry by id, then add"}
                result = await repo.create(MemoryWrite(content=text, kind=kind, scope=MemoryScope(kind="global"),
                                                       core=member, sensitivity=_flagged(args)), actor)
                if member == "about_you":
                    _tell_the_window(ctx, {"ok": True, **result})
            else:
                target = next((row for row in current if row["id"] == args.get("id")), None)
                if target is None:
                    return {"ok": False, "code": "memory_note_not_in_set", **listing}
                freed = len(target["text"]) if target["status"] == "active" else 0
                if action == "replace" and used - freed + len(text) > cap:
                    return {"ok": False, "code": "core_set_full", **listing}
                entry = await repo.get(target["id"], owner_id=ctx.owner_id)
                revision = await repo.db.get(MemoryRevision, entry.current_revision_id)
                # Like remember's supersede: an earlier explicit save request never
                # covers a different text or leaving the set.
                result = await repo.revise(entry.id, entry.version, MemoryWrite(
                    content=text if action == "replace" else (revision.content or target["text"]),
                    kind=kind, scope=MemoryScope(kind="global"),
                    sensitivity=_flagged(args, entry.sensitivity if entry.sensitivity != "secret" else "unknown"),
                    use_policy=entry.use_policy if entry.use_policy != "never" else "local_only",
                    topic=(revision.structured_value or {}).get("topic"),
                    core=member if action == "replace" else None,
                ), replace(actor, explicit_save_ref=None, allow_global_save=False))
        return {"ok": True, "id": result.get("id") or result.get("target_id"), "status": result.get("status"),
                "version": result.get("version"), "saved": result.get("status") == "active",
                "requires_confirmation": result.get("status") == "proposed",
                "note": "Takes effect from the next turn." if result.get("status") == "active" else
                        "Proposed: the user confirms it in Brain."}
    except MemoryError as exc:
        return {"ok": False, "code": exc.code}
    except ValidationError:
        return {"ok": False, "code": "invalid_memory_input"}
