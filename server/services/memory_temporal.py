"""时态取代执行器 — 恒确定性、可逆、规则不是 LLM(P1 spec)。

执行 = 单指针写(old.superseded_by = new_id),旧行永不删除;历史 = 行在 + 指针可查。
undo = 指针清 NULL。发起源:规则(memory.save_facts 扩展匹配)与 LLM Tier-1 工具
(P2 接 initiate_supersede;P1 不建任何工具)。所有拒绝走 SupersedeError(结构化),
所有执行/撤销 logger.info 留痕。provenance 必传——程序员守卫,缺失 raise。

守卫顺序(_apply 内,两种 session 模式共用同一份):
missing_provenance / self_supersede(先于开 session)→ bad_table(_model 查表)→
dangling_new → dangling_old → already_superseded → new_is_superseded → cycle(有界链走查)。

new_is_superseded 挡在链走查之前——被取代者不配当取代者。链走查本身是刻意保留的
defense-in-depth(第二道锁):只要 new_is_superseded 守卫存在,能走到链走查时
new_row.superseded_by 必为 None,循环条件立即为假,此分支在当前逻辑下不可达
(对抗审 #10 结论)。保留不删,不是活代码。
"""
from __future__ import annotations

import logging

from server.db import session as db_session
from server.db.models import Learning, UserFact

logger = logging.getLogger(__name__)

_TABLES = {"user_facts": UserFact, "learnings": Learning}
_MAX_CHAIN = 64


class SupersedeError(ValueError):
    """结构化拒绝:reason 供 API 层转 4xx,不落 500。"""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _model(table: str):
    try:
        return _TABLES[table]
    except KeyError:
        raise SupersedeError("bad_table", f"unknown table {table!r}") from None


async def execute_supersede(
    table: str, new_id: int, old_id: int, *, provenance: dict, db=None
) -> None:
    """db=None → 自建 session 并 commit(REST/独立调用);db 传入 → 用调用方 open session、
    **不 commit**(调用方事务内原子执行,规则自动取代路径用——对抗审:规则路径必须走
    executor 的完整守卫,不许裸写指针)。两种模式共用同一份守卫(_apply)。
    """
    if not provenance:
        raise SupersedeError("missing_provenance", "provenance is mandatory (programmer guard)")
    if new_id == old_id:
        raise SupersedeError("self_supersede", f"id {new_id} cannot supersede itself")
    model = _model(table)

    async def _apply(session) -> None:
        new_row = await session.get(model, new_id)
        old_row = await session.get(model, old_id)
        if new_row is None:
            raise SupersedeError("dangling_new", f"{table} id {new_id} does not exist")
        if old_row is None:
            raise SupersedeError("dangling_old", f"{table} id {old_id} does not exist")
        if old_row.superseded_by is not None:
            raise SupersedeError(
                "already_superseded",
                f"{table} id {old_id} already superseded by {old_row.superseded_by}",
            )
        if new_row.superseded_by is not None:
            raise SupersedeError(
                "new_is_superseded", f"{table} id {new_id} is itself superseded; refusing"
            )
        # 有界链走查防环:从 new 沿 superseded_by 前行,途中遇 old → 成环拒绝。
        # inert-by-design defense-in-depth — see module docstring.
        cursor, hops = new_row, 0
        while cursor is not None and cursor.superseded_by is not None and hops < _MAX_CHAIN:
            if cursor.superseded_by == old_id:
                raise SupersedeError(
                    "cycle", f"supersede {new_id}->{old_id} would create a cycle"
                )
            cursor = await session.get(model, cursor.superseded_by)
            hops += 1
        old_row.superseded_by = new_id

    if db is None:
        async with db_session.AsyncSessionLocal() as session:
            await _apply(session)
            await session.commit()
        logger.info(
            "supersede: %s %d -> superseded_by %d (committed, provenance=%s)",
            table, old_id, new_id, provenance.get("source_kind", "?"),
        )
    else:
        await _apply(db)
        # Honesty-in-logging: in db= mode the caller owns the commit — the write is only
        # staged here; a Task-4 batch rollback would discard it. Do NOT claim "committed".
        logger.info(
            "supersede: %s %d -> superseded_by %d (staged, caller commits, provenance=%s)",
            table, old_id, new_id, provenance.get("source_kind", "?"),
        )


async def _apply_undo(db, model, table: str, old_id: int, *, commit: bool) -> None:
    """The guards, shared by both modes (never duplicate them per-mode)."""
    row = await db.get(model, old_id)
    if row is None:
        raise SupersedeError("dangling_old", f"{table} id {old_id} does not exist")
    if row.superseded_by is None:
        raise SupersedeError("not_superseded", f"{table} id {old_id} is not superseded")
    row.superseded_by = None
    if commit:
        await db.commit()


async def undo_supersede(table: str, old_id: int, *, provenance: dict, db=None) -> None:
    """Restore a superseded row to active.

    `db=None` → own session + commit (the REST route); `db` passed → use the caller's
    open session and do NOT commit. Mirrors execute_supersede's two modes deliberately:
    without it, a route declaring Depends(get_session) would be MISLEADING, because
    app.dependency_overrides would not reach a write this function made on its own
    session — the exact test seam the proposal routes exist to preserve.
    """
    if not provenance:
        raise SupersedeError("missing_provenance", "provenance is mandatory (programmer guard)")
    model = _model(table)
    if db is not None:
        await _apply_undo(db, model, table, old_id, commit=False)
    else:
        async with db_session.AsyncSessionLocal() as own:
            await _apply_undo(own, model, table, old_id, commit=True)
    # Do not claim "committed" in caller-session mode — there the commit belongs to
    # the caller and may never happen (a later failure in the same request rolls this
    # back). An audit line asserting a durable write that did not land is worse than a
    # vaguer one.
    logger.info(
        "undo_supersede: %s %d restored to active (%s, provenance=%s)",
        table, old_id,
        "pending caller commit" if db is not None else "committed",
        provenance.get("source_kind", "?"),
    )


async def initiate_supersede(table: str, new_id: int, old_id: int, *, provenance: dict) -> None:
    """Tier-1 发起 seam(可逆故属 Tier 1)。P2 的记忆工具调这里;P1 无任何工具接线。"""
    await execute_supersede(table, new_id, old_id, provenance=provenance)
