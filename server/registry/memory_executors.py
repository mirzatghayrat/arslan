"""Second Brain agentic tools: recall (read) + remember (write). brain-P2 Task 3
(skeleton + fail-closed nail) + Task 4 (full three-tier write authorization +
scope isolation).

Registered under toolset key "second_brain" — NOT the literal "memory" (that key
lives in server.registry.seeder.RETIRED_TOOLSET_KEYS and is deleted on every boot).

🔴 Both executors read WHO is calling via
server.orchestrator.tool_caller.current_caller() (threaded by
tool_loop._dispatch_tool, brain-P2 Task 1) — that contextvar is set ONLY by
run_native's dispatch path. A Claude session talking to this backend directly
(no native tool-calling round trip through run_native) never populates it, so
current_caller() reads None and every write here refuses (fail-closed nail,
decision point 1). "Agentic remember/recall needs a native-tool-calling
provider" is a real product constraint, not a bug.

RememberExecutor's three tiers (plan: docs/superpowers/plans/
2026-07-18-brain-p2-agentic-memory.md, Task 4):
  - Tier1 direct write (reversible, immediate): host append/supersede/mark_stale
    on fact/learning/note; a spawn appending/superseding its OWN well
    (learning) or its OWN preferences (memory_facts).
  - Tier2 propose (MemoryProposal, REST-accept only — decision point 3): delete
    (any kind, any actor — never direct); a spawn writing a GLOBAL table
    (fact/note) downgrades EVERY action to a proposal, never a direct write;
    a non-spawn actor (host) writing a spawn's preference (no direct write —
    there's no "own well" for host to write into). The proposal's provenance
    JSON carries whatever Task 5's accept endpoint needs to materialize the
    write later (content / new_array) — new_id is always None at propose time.
  - Capability errors: supersede only exists for fact/learning (has
    superseded_by); mark_stale only exists for fact; note/preference have no
    temporal concept at all (plan's "矩阵按表能力").
"""
from __future__ import annotations

import logging
from datetime import datetime

from server.orchestrator.tool_caller import current_caller

logger = logging.getLogger(__name__)

# kind -> the table a spawn's non-own-well write downgrades into (Tier2 scope
# check). Only fact/note are GLOBAL, host-owned tables — learning is naturally
# spawn-scoped (its own row carries spawn_id) and preference lives on the
# Spawn row itself, so neither needs the scope-downgrade branch below.
_GLOBAL_TABLE = {"fact": "user_facts", "note": "notes"}

# kind -> table for the supersede action (only tables with `superseded_by`).
_SUPERSEDE_TABLE = {"fact": "user_facts", "learning": "learnings"}


class RecallExecutor:
    """Read-only search over the Second Brain (facts, materials, learnings, notes).

    🔴 Sensitive-fact isolation (fail-closed, mirrors server.orchestrator.memory's
    facts_text discipline): sensitive facts are visible ONLY to an explicit host
    caller. A spawn actor and a missing caller (current_caller() is None) both see
    the sensitive-filtered set — the leak direction on a forgotten/omitted caller
    is always "give less", never "let sensitive data reach a spawn prompt".

    🔴 DEBT follow-up (brain-P2 decision point 2, recorded Task 6 — see the fuller
    note at server.services.replay_safety.REPLAY_SAFE_BUILTINS): despite being
    read-only, `recall` deliberately does NOT enter REPLAY_SAFE_BUILTINS yet. The
    sensitive-fact filter above is verified fail-closed on the LIVE path only; its
    prerequisite for ever joining the replay-safe set is a test proving replay-path
    sensitive-exclusion is byte-for-byte identical to live's — not yet written.
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
    """Write to the Second Brain — the full three-tier authorization (brain-P2
    Task 4). See the module docstring for the tier breakdown; the routing below
    follows the plan's decision tree exactly."""

    key = "remember"

    async def execute(self, args: dict) -> dict:
        caller = current_caller()
        if caller is None:
            # Fail-closed nail (decision point 1): no identity -> refuse the write,
            # never guess host vs. spawn.
            return {"ok": False, "error": "no caller context; refusing to write"}

        if caller.actor not in ("host", "spawn"):
            # Fail-closed on identity (whole-branch review): the routing below
            # treats "not spawn" as host, so an unknown/garbage actor string
            # would otherwise inherit HOST privileges (direct global writes).
            # Refuse anything that isn't one of the two known actors.
            return {"ok": False, "error": "unknown caller actor; refusing to write"}

        actor, spawn_id = caller.actor, caller.spawn_id
        if actor == "spawn" and spawn_id is None:
            # An actor=="spawn" caller with no real spawn_id is exactly as
            # dangerous as caller=None -- it can't be scoped to any well, so
            # every downstream check below (own-well append, cross-well
            # supersede) would be meaningless. Refuse rather than guess.
            return {"ok": False, "error": "spawn actor missing spawn_id; refusing to write"}

        kind = args.get("kind")
        action = args.get("action")
        content = (args.get("content") or "").strip()
        target_id = args.get("target_id")

        prov = {
            "source_kind": "agentic",
            "actor": f"spawn:{spawn_id}" if actor == "spawn" else "host",
            "conversation_id": caller.conversation_id,
        }

        # ---- Scope downgrade: a spawn writing a GLOBAL table (fact/note)
        # NEVER writes directly, for ANY action -- always Tier2 propose. ----
        if actor == "spawn" and kind in _GLOBAL_TABLE:
            table = _GLOBAL_TABLE[kind]
            if action == "append":
                if not content:
                    return {"ok": False, "error": "missing 'content'"}
                return await self._propose(
                    "append_suspect", table=table, old_id=None,
                    provenance={**prov, "content": content},
                    reason=f"{prov['actor']} proposes appending a {kind}")
            if action == "delete":
                return await self._propose(
                    "delete_suspect", table=table, old_id=target_id, provenance=prov,
                    reason=f"{prov['actor']} proposes deleting {table}#{target_id}")
            if action in ("supersede", "mark_stale"):
                if kind != "fact":
                    # notes have no superseded_by column (no temporal concept,
                    # plan's "矩阵按表能力") -- same "unsupported" contract as
                    # preference's supersede/mark_stale gate above and
                    # _mark_stale_tier1/_supersede_tier1's own kind gates on
                    # the host path. Refuse cleanly here too rather than
                    # creating a Tier2 proposal Task 5's accept endpoint could
                    # never actually resolve (a permanent dismiss-only dead
                    # end -- there is no new_id materialization that could
                    # make a note "superseded").
                    return {"ok": False, "error": f"{action} unsupported for this kind"}
                payload = dict(prov)
                if content:
                    payload["content"] = content
                return await self._propose(
                    "edit_high_conf_suspect", table=table, old_id=target_id,
                    provenance=payload,
                    reason=f"{prov['actor']} proposes editing {table}#{target_id}")
            return {"ok": False, "error": f"unsupported action {action!r}"}

        # ---- preference: no dedicated row -- lives on Spawn.memory_facts. ----
        if kind == "preference":
            if action in ("supersede", "mark_stale"):
                return {"ok": False, "error": f"{action} unsupported for this kind"}
            if action == "delete":
                # Ownership guard (Task 5 self-check, Minor #3): a spawn may only
                # ever propose deleting its OWN preferences, never another
                # spawn's. Omitting target_id defaults to the caller's own well
                # (mirrors _append_own_preference's implicit self-scope below);
                # an explicit target_id that disagrees with the caller's own
                # spawn_id is a cross-well attempt and is refused outright --
                # never silently redirected to "own well" nor silently honored
                # against the mismatched id.
                if actor == "spawn":
                    if target_id is not None and target_id != spawn_id:
                        return {"ok": False, "code": "out_of_scope",
                               "error": "cannot delete another spawn's preference; refusing"}
                    target_spawn_id = spawn_id
                else:
                    # host (or any non-spawn actor): needs an explicit target,
                    # same requirement as the append/overwrite branch below --
                    # there's no "own well" for host to default into.
                    if target_id is None:
                        return {"ok": False,
                               "error": "missing 'target_id' (target spawn id required "
                                        "for a preference delete proposal)"}
                    target_spawn_id = target_id
                return await self._propose(
                    "delete_suspect", table="spawns", old_id=target_spawn_id,
                    provenance={**prov, "target_spawn_id": target_spawn_id},
                    reason=f"{prov['actor']} proposes deleting spawn {target_spawn_id}'s preferences")
            if action != "append":
                return {"ok": False, "error": f"unsupported action {action!r}"}
            if not content:
                return {"ok": False, "error": "missing 'content'"}
            if actor == "spawn":
                return await self._append_own_preference(spawn_id, content)
            # host (or any non-spawn actor): needs an explicit target spawn.
            # The native remember tool schema (frozen in Task 3) has no
            # separate target_spawn_id field -- target_id doubles as the
            # target spawn id here.
            if target_id is None:
                return {"ok": False,
                       "error": "missing 'target_id' (target spawn id required "
                                "for a preference overwrite proposal)"}
            return await self._propose_preference_overwrite(target_id, content, prov)

        # ---- Tier1 direct writes: host on any global kind, or a spawn
        # writing its OWN well (learning is the only kind that reaches here
        # for a spawn actor -- fact/note were caught by the scope-downgrade
        # branch above, preference by the branch just above). ----
        if action == "append":
            return await self._append_tier1(kind, content, prov, spawn_id)
        if action == "supersede":
            return await self._supersede_tier1(kind, actor, spawn_id, target_id, content, prov)
        if action == "mark_stale":
            return await self._mark_stale_tier1(kind, target_id)
        if action == "delete":
            table = _SUPERSEDE_TABLE.get(kind) or _GLOBAL_TABLE.get(kind)
            if table is None:
                return {"ok": False, "error": f"unsupported kind {kind!r}"}
            return await self._propose(
                "delete_suspect", table=table, old_id=target_id, provenance=prov,
                reason=f"{prov['actor']} proposes deleting {table}#{target_id}")

        return {"ok": False, "error": "not yet implemented"}

    # ------------------------------------------------------------------
    # Tier1 helpers
    # ------------------------------------------------------------------

    async def _append_tier1(self, kind: str, content: str, prov: dict,
                            spawn_id: int | None) -> dict:
        if not content:
            return {"ok": False, "error": "missing 'content'"}

        if kind == "fact":
            from server.orchestrator import memory
            rows = await memory.save_facts([{"content": content}], provenance=prov)
            if not rows:
                return {"ok": False, "error": "fact not written (write failed)"}
            return {"ok": True, "id": rows[0].id}

        if kind == "learning":
            from server.services import learning_service
            new_id = await learning_service.append(
                content, label=content[:60], source_kind="agentic",
                source_ref={"actor": prov["actor"], "conversation_id": prov["conversation_id"]},
                spawn_id=spawn_id)
            if not new_id:
                return {"ok": False, "error": "learning not written (duplicate or write failed)"}
            return {"ok": True, "id": new_id}

        if kind == "note":
            from server.services import note_service
            row = await note_service.create(title=content[:200], content=content, tags=None)
            return {"ok": True, "id": row.id}

        return {"ok": False, "error": f"unsupported kind {kind!r}"}

    async def _supersede_tier1(self, kind: str, actor: str, spawn_id: int | None,
                               target_id, content: str, prov: dict) -> dict:
        if kind not in _SUPERSEDE_TABLE:
            return {"ok": False, "error": "supersede unsupported for this kind"}
        if target_id is None:
            return {"ok": False, "error": "missing 'target_id'"}
        if not content:
            return {"ok": False, "error": "missing 'content'"}
        table = _SUPERSEDE_TABLE[kind]

        if actor == "spawn":
            # Only reachable for kind=="learning" -- a spawn superseding a
            # global fact/note was already intercepted by the scope-downgrade
            # branch above. Verify the target row is actually in the caller's
            # own well before writing anything.
            from server.db import session as db_session
            from server.db.models import Learning
            async with db_session.AsyncSessionLocal() as db:
                row = await db.get(Learning, target_id)
            if row is None or row.spawn_id != spawn_id:
                return {"ok": False, "code": "out_of_scope",
                       "error": "target not in caller's scope; refusing cross-well supersede"}

        write = await self._append_tier1(kind, content, prov, spawn_id)
        if not write.get("ok"):
            return {"ok": False, "error": f"{write.get('error')}; supersede aborted"}
        new_id = write["id"]

        from server.services import memory_temporal
        try:
            await memory_temporal.initiate_supersede(table, new_id, target_id, provenance=prov)
        except memory_temporal.SupersedeError as exc:
            return {"ok": False, "error": f"{exc.code}: {exc.detail}"}
        logger.info("remember: %s supersede %s -> %s (%s)", prov["actor"], target_id, new_id, table)
        return {"ok": True, "id": new_id}

    async def _mark_stale_tier1(self, kind: str, target_id) -> dict:
        if kind != "fact":
            return {"ok": False, "error": "mark_stale unsupported for this kind"}
        if target_id is None:
            return {"ok": False, "error": "missing 'target_id'"}

        from server.db import session as db_session
        from server.db.models import UserFact
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(UserFact, target_id)
            if row is None:
                return {"ok": False, "error": f"fact {target_id} not found"}
            prov_json = dict(row.provenance or {})
            # Same action, no separate action verb for "undo" -- toggles: a
            # second mark_stale on an already-stale fact clears the mark
            # (plan: "可 undo=清标记").
            now_stale = not prov_json.get("stale", False)
            if now_stale:
                prov_json["stale"] = True
                prov_json["marked_at"] = datetime.utcnow().isoformat()
            else:
                prov_json.pop("stale", None)
                prov_json.pop("marked_at", None)
            row.provenance = prov_json
            await db.commit()
        return {"ok": True, "id": target_id, "stale": now_stale}

    async def _append_own_preference(self, spawn_id: int, content: str) -> dict:
        from server.db import session as db_session
        from server.db.models import Spawn
        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, spawn_id)
            if spawn is None:
                return {"ok": False, "error": f"spawn {spawn_id} not found"}
            arr = list(spawn.memory_facts or [])
            arr.append(content)
            spawn.memory_facts = arr           # single transaction, no intermediate await
            await db.commit()
        return {"ok": True, "id": spawn_id}

    async def _propose_preference_overwrite(self, target_spawn_id: int, content: str,
                                            prov: dict) -> dict:
        from server.db import session as db_session
        from server.db.models import Spawn
        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, target_spawn_id)
        if spawn is None:
            return {"ok": False, "error": f"spawn {target_spawn_id} not found"}
        new_array = list(spawn.memory_facts or []) + [content]
        return await self._propose(
            "preference_overwrite_suspect", table="spawns", old_id=target_spawn_id,
            provenance={**prov, "target_spawn_id": target_spawn_id, "new_array": new_array},
            reason=f"{prov['actor']} proposes overwriting spawn {target_spawn_id}'s preferences")

    # ------------------------------------------------------------------
    # Tier2 helper
    # ------------------------------------------------------------------

    async def _propose(self, kind: str, *, table: str, old_id, provenance: dict,
                       reason: str) -> dict:
        """Write a MemoryProposal — new_id is ALWAYS None here (nothing has been
        materialized yet); the to-be-written payload lives entirely in
        `provenance` JSON (append_suspect: "content"; preference_overwrite_suspect:
        "target_spawn_id" + "new_array"). Task 5's accept endpoint reads it from
        there. Never a direct write — that's the whole point of Tier2."""
        from server.db import session as db_session
        from server.db.models import MemoryProposal
        async with db_session.AsyncSessionLocal() as db:
            row = MemoryProposal(
                kind=kind, table_name=table, new_id=None, old_id=old_id or 0,
                reason=reason, provenance=provenance)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        logger.info("remember: proposed %s on %s#%s (proposal_id=%s)",
                   kind, table, old_id, row.id)
        return {"ok": True, "proposed": True, "proposal_id": row.id,
               "message": "已提议,待你在记忆里确认(REST accept)"}
