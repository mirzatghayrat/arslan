"""One ledger row per skill decision a person made directly (0.1.61 §A8): an import from
Capabilities, or Save / Not now on a draft. The row is PR 2's (plan Ruling F): kind `capability`,
which `permissions.KINDS` knows and which is once-only; decided by the user; `extra` cut to 1 KB and
never carrying PR 2's reserved "Always" key, so it is not a row the Inbox lists or "Always allow"
could be given for. A row that cannot be written never undoes the decision.

This file is the one definition of the capability ledger row (PR 5 plans `capability_ledger.record`
with this same signature, and re-exports this module's `KIND` and `record`; there is no second copy).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The ledger kind of every decision here: a member of `permissions.KINDS` (a test pins it).
KIND = "capability"


async def record(*, target: str, detail: str, allowed: bool, conversation_id: str | None = None,
                 extra: dict | None = None) -> None:
    from server.db import session as db_session
    from server.services import permission_store, permissions
    try:
        mode = await permissions._mode()           # PR 2's single source of the mode
        # PR 2's own cap (1 KB, spec §A8), with its reserved key left out: a refused row's "Always"
        # set is the server's alone (`permissions._record_in` drops a caller's the same way).
        kept = permissions._extra({k: v for k, v in (extra or {}).items() if k != permissions.ALWAYS_KEY})
        async with db_session.AsyncSessionLocal() as db:
            await permission_store.record(
                db, conversation_id=conversation_id, kind=KIND, target=target[:2000],
                detail=detail[:500], extra=kept, mode=mode, decided_by="user",
                decision="allow" if allowed else "deny",
                scope="once" if allowed else None)  # a user's no has no scope, as `permissions._ask` records it
            await db.commit()
    except Exception:  # noqa: BLE001 — the ledger never undoes a decision
        logger.warning("skill ledger write failed", exc_info=True)
