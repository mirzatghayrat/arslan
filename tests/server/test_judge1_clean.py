"""JUDGE1 follow-up (the user, 2026-10-31: a one-time clean): rows the judgment ledger recorded before JUDGE1 for the
memory points hold the lesson's words in plain text. Since JUDGE1 those points record digests only (`redact`). At boot,
the ledger drops every row of a `redact` point whose state still holds plain text; digested rows and other points'
rows stay. Fixture text is synthetic."""
from sqlalchemy import select

from server.db.models import Judgment
from server.services import judgment


def _row(point: str, state: dict) -> Judgment:
    return Judgment(point=point, mode="active", state=state, state_hash="h")


async def test_rows_with_plain_memory_text_go_and_the_rest_stay(execution_db):
    digest = "sha256:0123456789abcdef"
    async with execution_db() as session:
        session.add_all([
            _row("memory.worth", {"kind": "user_correction", "candidate": "use the blue folder", "evidence": "{}"}),
            _row("memory.merge", {"candidate": digest, "existing": "always reply briefly"}),   # one plain field
            _row("memory.conflict", {"candidate": "a", "existing": "b"}),
            _row("memory.worth", {"kind": digest, "candidate": digest, "evidence": digest}),  # after JUDGE1
            _row("memory.applied", {"lesson": "plain words, not a redact point", "steps": "[]"}),
        ])
        await session.commit()

    assert await judgment.drop_unredacted() == 3

    async with execution_db() as session:
        left = (await session.execute(select(Judgment.point, Judgment.state).order_by(Judgment.id))).all()
    assert [point for point, _ in left] == ["memory.worth", "memory.applied"]
    assert left[0][1]["candidate"] == digest
    assert await judgment.drop_unredacted() == 0                                 # nothing left to clean


async def test_every_redact_point_is_cleaned(execution_db):
    points = [p.name for p in judgment.REGISTRY.values() if p.redact]
    assert {"memory.worth", "memory.merge", "memory.conflict"} <= set(points)
    async with execution_db() as session:
        session.add_all([_row(point, {"candidate": "plain"}) for point in points])
        await session.commit()
    assert await judgment.drop_unredacted() == len(points)
