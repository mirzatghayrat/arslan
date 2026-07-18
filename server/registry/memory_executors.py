"""Second Brain agentic tools: recall (read) + remember (write). brain-P2 Task 3.

Registered under toolset key "second_brain" — NOT the literal "memory" (that key
lives in server.registry.seeder.RETIRED_TOOLSET_KEYS and is deleted on every boot).

Both executors read WHO is calling via server.orchestrator.tool_caller.current_caller()
(threaded by tool_loop._dispatch_tool, brain-P2 Task 1). None means "no caller was
set" and every write path here fails closed rather than guessing host vs. spawn.

RememberExecutor is a SKELETON: Task 3 implements only action=="append" for
kind in {fact, learning, note} on the HOST path (Tier1 direct-write). Every other
combination (host preference append, any spawn actor, supersede/mark_stale/delete)
returns {"ok": False, "error": "not yet implemented"} — Task 4 completes the
three-tier authorization + scope isolation.
"""
from __future__ import annotations

import logging

from server.orchestrator.tool_caller import current_caller

logger = logging.getLogger(__name__)

# Task-3 scope: only these (kind, action) combos are implemented as Tier1 direct
# writes, and only for actor=="host". Everything else -> "not yet implemented".
_TASK3_APPEND_KINDS = ("fact", "learning", "note")


class RecallExecutor:
    """Read-only search over the Second Brain (facts, materials, learnings, notes).

    🔴 Sensitive-fact isolation (fail-closed, mirrors server.orchestrator.memory's
    facts_text discipline): sensitive facts are visible ONLY to an explicit host
    caller. A spawn actor and a missing caller (current_caller() is None) both see
    the sensitive-filtered set — the leak direction on a forgotten/omitted caller
    is always "give less", never "let sensitive data reach a spawn prompt".
    """

    key = "recall"

    async def execute(self, args: dict) -> dict:
        from server.orchestrator import memory
        from server.services import knowledge

        query = (args.get("query") or "").strip()
        kind = args.get("kind")
        caller = current_caller()
        # ONLY an explicit host caller sees sensitive facts — caller=None and any
        # spawn actor both fail closed to the sensitive-filtered set.
        include_sensitive = caller is not None and caller.actor == "host"
        spawn_id = caller.spawn_id if (caller is not None and caller.actor == "spawn") else None

        hits: list[dict] = []

        if query and kind in (None, "material", "learning", "note"):
            # retrieve_scoped returns list[tuple[source, text]] — NO provenance field.
            # Don't fabricate one; the human-readable `source` string is carried as-is.
            scoped = await knowledge.retrieve_scoped(query, spawn_id=spawn_id, record_usage=False)
            hits.extend(
                {"kind": "material", "content": text, "source": source, "superseded": False}
                for source, text in scoped
            )

        if kind in (None, "fact"):
            facts = await memory.list_facts()   # active-only default (P0 single throat)
            if not include_sensitive:
                # NULL sensitive -> treated as sensitive (fail-closed), same rule as
                # memory.facts_text's default (include_sensitive=False).
                facts = [f for f in facts if f.sensitive is False]
            hits.extend(
                {"kind": "fact", "content": f.content, "provenance": f.provenance,
                 "superseded": False}
                for f in facts
            )

        return {"ok": True, "hits": hits}


class RememberExecutor:
    """Write to the Second Brain. Task 3 = append-only Tier1 skeleton + fail-closed
    nail; Task 4 adds the three-tier authorization (spawn scope downgrade to
    MemoryProposal, preference handling, supersede/mark_stale/delete)."""

    key = "remember"

    async def execute(self, args: dict) -> dict:
        caller = current_caller()
        if caller is None:
            # Fail-closed nail (decision point 1): no identity -> refuse the write,
            # never guess host vs. spawn.
            return {"ok": False, "error": "no caller context; refusing to write"}

        kind = args.get("kind")
        action = args.get("action")
        content = (args.get("content") or "").strip()

        if action != "append" or caller.actor != "host" or kind not in _TASK3_APPEND_KINDS:
            return {"ok": False, "error": "not yet implemented"}

        if not content:
            return {"ok": False, "error": "missing 'content'"}

        provenance = {"source_kind": "agentic", "actor": "host",
                      "conversation_id": caller.conversation_id}

        if kind == "fact":
            from server.orchestrator import memory
            rows = await memory.save_facts([{"content": content}], provenance=provenance)
            if not rows:
                return {"ok": False, "error": "fact not written (write failed)"}
            return {"ok": True, "id": rows[0].id}

        if kind == "note":
            from server.services import note_service
            row = await note_service.create(title=content[:200], content=content, tags=None)
            return {"ok": True, "id": row.id}

        # kind == "learning": learning_service has no public id-returning append yet
        # (Task 4 adds one — see plan's learning_service.append BLOCKER note). Reuse
        # the existing write path and report success/failure honestly without
        # fabricating an id we don't have.
        from server.services import learning_service
        wrote = await learning_service._write(  # noqa: SLF001 — interim until Task 4's public append
            content, label=content[:60], source_kind="agentic",
            source_ref=provenance, spawn_id=None)
        if not wrote:
            return {"ok": False, "error": "learning not written (duplicate or write failed)"}
        return {"ok": True}
