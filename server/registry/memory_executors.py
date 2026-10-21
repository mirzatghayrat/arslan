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

Both run on the unified memory store (memory_tools_v2), the only one since every boot activates it
(storage_boot). The write rules live there: delete and mark_stale go to the user, a write from an
expert stays in its own scope, and a write after outside content is a proposal. 0.1.63 C2a-2 removed
the v1 three-tier path (direct table writes and MemoryProposal rows), which no boot could reach.
"""
from __future__ import annotations

import logging
from datetime import datetime

from server.orchestrator.tool_caller import current_caller

logger = logging.getLogger(__name__)


class RecallExecutor:
    """Read-only search over the Second Brain (memory entries and materials).

    🔴 What a caller may see is memory_tools_v2.recall's: the same assembly and sensitivity rules as the
    memory block (personal_context), and a missing caller gets no hits — "give less", never more.

    🔴 DEBT follow-up (brain-P2 decision point 2, recorded Task 6 — see the fuller
    note at server.services.replay_safety.REPLAY_SAFE_BUILTINS): despite being
    read-only, `recall` deliberately does NOT enter REPLAY_SAFE_BUILTINS yet. The
    sensitive-fact filter above is verified fail-closed on the LIVE path only; its
    prerequisite for ever joining the replay-safe set is a test proving replay-path
    sensitive-exclusion is byte-for-byte identical to live's — not yet written.
    """

    key = "recall"

    async def execute(self, args: dict) -> dict:
        from server.services.memory_tools_v2 import recall
        return await recall(args, current_caller())


class RememberExecutor:
    """Write to the Second Brain. The identity checks below refuse before anything else; the write rules
    are memory_tools_v2.remember's (see the module docstring)."""

    key = "remember"

    async def execute(self, args: dict) -> dict:
        caller = current_caller()
        if caller is None:
            # Fail-closed nail (decision point 1): no identity -> refuse the write,
            # never guess host vs. spawn.
            return {"ok": False, "error": "no caller context; refusing to write"}

        if caller.actor not in ("host", "spawn"):
            # Fail-closed on identity (whole-branch review): the write path
            # treats "not spawn" as host, so an unknown/garbage actor string
            # would otherwise inherit HOST privileges. Refuse anything that
            # isn't one of the two known actors.
            return {"ok": False, "error": "unknown caller actor; refusing to write"}

        if caller.actor == "spawn" and caller.spawn_id is None:
            # An actor=="spawn" caller with no real spawn_id is exactly as
            # dangerous as caller=None -- it can't be scoped to its own
            # memory. Refuse rather than guess.
            return {"ok": False, "error": "spawn actor missing spawn_id; refusing to write"}

        from server.services.memory_tools_v2 import remember
        return await remember(args, caller)


class MemoryNoteExecutor:
    """Edit the always-in-view sets — "About you" and Arslan's notes about this Mac
    and setup — by entry id (0.1.52 S4). Host only; needs the unified memory store."""

    key = "memory_note"

    async def execute(self, args: dict) -> dict:
        from server.services.memory_tools_v2 import note
        return await note(args, current_caller())


class ConversationSearchExecutor:
    """Find the user's own earlier words in past conversations (0.1.52 S3).

    Original snippets with when and where, never summaries. Past messages include
    Arslan's replies, which can carry web or file text, so results are NOT marked
    external:False — the loop wraps them as untrusted data. Follows the same memory
    permissions as the memory block: off in a temporary or "no memory" conversation,
    and off for a cloud model when the user turned memory off for conversations."""

    key = "conversation_search"

    async def execute(self, args: dict) -> dict:

        from server.services import conversation_search, personal_context
        ctx = personal_context.current()
        if ctx is not None and (ctx.no_memory or ctx.temporary):
            return {"ok": False, "external": False, "error": "memory is off for this conversation"}
        if ctx is not None and not ctx.model_is_local and not ctx.cloud_memory_effective:
            return {"ok": False, "external": False,
                    "error": "using past conversations is turned off (Settings › Memory)"}
        query = " ".join(str(args.get("query") or "").split())
        if not query:
            return {"ok": False, "external": False, "error": "missing 'query'"}

        def day(value, end=False):
            if not value:
                return None
            try:
                d = datetime.fromisoformat(str(value)[:10])
            except ValueError:
                return None
            return d.replace(hour=23, minute=59, second=59) if end else d
        try:
            limit = int(args.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        results = await conversation_search.search(
            query, since=day(args.get("since")), until=day(args.get("until"), end=True), limit=limit,
            exclude_conversation=ctx.conversation_id if ctx else None)
        return {"ok": True, "query": query, "count": len(results), "results": results,
                "note": "Original words from earlier conversations; link opens the conversation in Arslan."}
