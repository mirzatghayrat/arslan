"""Unified-memory implementation of legacy recall/remember tool names."""
from dataclasses import replace
from datetime import UTC

from pydantic import ValidationError

from arslan.companion.memory import MemoryError, MemoryScope, MemoryWrite
from server.db.models import MemoryRevision
from server.services import personal_context as pc
from server.services.memory_repository import repository


def _context(caller):
    ctx = pc.current()
    if ctx is None or caller is None or caller.actor not in {"host", "spawn"}:
        return None
    if caller.actor == "spawn":
        if caller.spawn_id is None:
            return None
        return replace(ctx, expert_id=str(caller.spawn_id), explicit_save_ref=None, allow_global_save=False)
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
    try:
        async with repository() as repo:
            if action == "append":
                result = await repo.create(MemoryWrite(content=str(args.get("content") or ""),
                                                       kind=kind, scope=scope), actor)
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
                    sensitivity=entry.sensitivity, use_policy=entry.use_policy,
                    topic=(revision.structured_value or {}).get("topic"),
                    valid_from=entry.valid_from.replace(tzinfo=UTC) if entry.valid_from else None,
                    review_at=entry.review_at.replace(tzinfo=UTC) if entry.review_at else None,
                    expires_at=entry.expires_at.replace(tzinfo=UTC) if entry.expires_at else None,
                ), replace(actor, explicit_save_ref=None, allow_global_save=False))
        return {"ok": True, **result, "saved": result.get("status") == "active",
                "requires_confirmation": result.get("status") == "proposed"}
    except MemoryError as exc:
        return {"ok": False, "code": exc.code}
    except ValidationError:
        return {"ok": False, "code": "invalid_memory_input"}
