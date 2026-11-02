"""JUDGE1 follow-up (the user, 2026-10-31: "the text outlives the lessons you deleted"; a one-time clean at boot): rows
the judgment ledger recorded before JUDGE1 can hold a lesson's words. At boot, after the prune, the ledger drops every
row of a `redact` point with a field that isn't a digest, and every row naming a lesson that is gone (or older than the
lesson that now has its id). Rows `judge` writes today, and other points' rows of live lessons, stay. Fixture text is
synthetic."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from server.db.models import Judgment, Lesson
from server.services import judgment

DIGEST = "sha256:0123456789abcdef"


def _row(point: str, state: dict, **kw) -> Judgment:
    return Judgment(point=point, mode="active", state=state, state_hash="h", **kw)


async def _left(db):
    async with db() as session:
        return (await session.execute(select(Judgment.point, Judgment.state, Judgment.ref).order_by(Judgment.id))).all()


async def _lesson(db, created_at: datetime) -> int:
    async with db() as session:
        row = Lesson(situation="renaming files in the synthetic project", advice="use the blue folder first",
                     polarity="do", source="user_correction", evidence={}, status="active",
                     created_at=created_at, updated_at=created_at)
        session.add(row)
        await session.commit()
        return row.id


async def test_rows_with_plain_memory_text_go_and_the_rest_stay(execution_db):
    async with execution_db() as session:
        session.add_all([
            _row("memory.worth", {"kind": "user_correction", "candidate": "use the blue folder", "evidence": "{}"}),
            _row("memory.merge", {"candidate": DIGEST, "existing": "always reply briefly"}),    # one plain field
            _row("memory.conflict", {"candidate": "a", "existing": "b"}),
            _row("memory.merge", {"candidate": "sha256: check downloads with shasum", "existing": "sha256: verify"}),
            _row("memory.worth", {"kind": DIGEST, "candidate": DIGEST, "evidence": DIGEST}),   # as judge writes it
            _row("memory.applied", {"lesson": "not a redact point, no lesson named", "steps": "[]"}),
        ])
        await session.commit()

    assert await judgment.drop_unredacted() == 4

    left = await _left(execution_db)
    assert [point for point, _, _ in left] == ["memory.worth", "memory.applied"]
    assert left[0][1]["candidate"] == DIGEST
    assert await judgment.drop_unredacted() == 0                                 # nothing left to clean


async def test_every_redact_point_is_cleaned(execution_db):
    points = [p.name for p in judgment.REGISTRY.values() if p.redact]
    assert {"memory.worth", "memory.merge", "memory.conflict"} <= set(points)
    async with execution_db() as session:
        session.add_all([_row(point, {"candidate": "plain"}) for point in points])
        await session.commit()
    assert await judgment.drop_unredacted() == len(points)


async def test_rows_of_deleted_lessons_go_and_a_live_lessons_stay(execution_db):
    """memory.applied keeps the lesson's words (lessons.record_applied); before JUDGE1, deleting the lesson left them."""
    now = datetime.utcnow()
    live = await _lesson(execution_db, now - timedelta(days=3))
    gone = await _lesson(execution_db, now - timedelta(days=3))
    async with execution_db() as session:
        session.add_all([
            _row("memory.applied", {"lesson": "the live lesson's words", "steps": "[]"}, ref=f"lesson:{live}",
                 created_at=now - timedelta(days=2)),
            _row("memory.applied", {"lesson": "the deleted lesson's words", "steps": "[]"}, ref=f"lesson:{gone}",
                 created_at=now - timedelta(days=2)),
            _row("job.accomplished", {"goal": "x"}, ref="job:12", created_at=now),                # another kind of ref
        ])
        await session.commit()
        await session.delete(await session.get(Lesson, gone))                   # as DELETE /lessons did before JUDGE1
        await session.commit()

    assert await judgment.drop_unredacted() == 1
    assert [ref for _, _, ref in await _left(execution_db)] == [f"lesson:{live}", "job:12"]


async def test_a_reused_lesson_id_does_not_keep_the_old_lessons_rows(execution_db):
    now = datetime.utcnow()
    first = await _lesson(execution_db, now - timedelta(days=5))
    async with execution_db() as session:
        session.add(_row("memory.applied", {"lesson": "the old lesson's words", "steps": "[]"}, ref=f"lesson:{first}",
                         created_at=now - timedelta(days=4)))
        await session.commit()
        await session.delete(await session.get(Lesson, first))
        await session.commit()
    again = await _lesson(execution_db, now - timedelta(days=1))
    assert again == first                                                        # the newest id is given out again
    async with execution_db() as session:
        session.add(_row("memory.applied", {"lesson": "the new lesson's words", "steps": "[]"}, ref=f"lesson:{again}",
                         created_at=now))
        await session.commit()

    assert await judgment.drop_unredacted() == 1
    assert [state["lesson"] for _, state, _ in await _left(execution_db)] == ["the new lesson's words"]


async def test_more_rows_than_one_batch(execution_db):
    async with execution_db() as session:
        session.add_all([_row("memory.merge", {"candidate": f"plain {i}", "existing": "x"}) for i in range(1201)])
        session.add(_row("memory.merge", {"candidate": DIGEST, "existing": DIGEST}))
        await session.commit()
    assert await judgment.drop_unredacted() == 1201
    assert len(await _left(execution_db)) == 1
    assert await judgment.drop_unredacted() == 0


# -- what judge() writes today is never cleaned (#582 review, L1) ------------------------------------------------

class _Adapter:
    model = "fast-fixture"

    def __init__(self, content='{"answer": true, "p": 0.93}', delay=0.0, fails=False):
        self.content, self.delay, self.fails = content, delay, fails

    async def chat(self, *, system, user):
        if self.fails:
            raise RuntimeError("synthetic provider failure")
        await asyncio.sleep(self.delay)
        return SimpleNamespace(content=self.content)


@pytest.mark.parametrize("adapter", [_Adapter(), _Adapter(content="not json"), _Adapter(fails=True),
                                     _Adapter(delay=1.0)], ids=["answer", "unparsable", "raises", "timeout"])
async def test_rows_judge_writes_for_every_redact_point_are_kept(execution_db, monkeypatch, adapter):
    async def make():
        return adapter
    monkeypatch.setattr(judgment, "_adapter", make)
    monkeypatch.setattr(judgment, "AFTER_TURN_TIMEOUT_S", 0.2)
    lesson = await _lesson(execution_db, datetime.utcnow() - timedelta(days=1))
    shapes = [{"kind": "user_correction", "candidate": "use the blue folder", "evidence": "{}", "existing": "x"},
              {"kind": 3, "candidate": ["a", "b"], "evidence": {"nested": True}, "existing": None},
              {"kind": "detour", "candidate": "sha256: looks like a digest", "evidence": "x" * 5000, "existing": ""}]
    points = [p.name for p in judgment.REGISTRY.values() if p.redact]
    for point in points:
        for state in shapes:
            await judgment.judge(point, state, ref=f"lesson:{lesson}")
    written = len(await _left(execution_db))
    assert written == len(points) * len(shapes)
    assert await judgment.drop_unredacted() == 0
    assert len(await _left(execution_db)) == written


# -- boot (#582 review, L2 and L3) --------------------------------------------------------------------------------

class _BootWentOn(BaseException):
    """Raised by the boot step after the judgment ledger's: boot got past it (the reaper's block catches Exception)."""


def _boot_past_the_ledger(monkeypatch, tmp_path, maker):
    """server.main.lifespan itself, on the test database, stopped at the run reaper, the step after the ledger's."""
    from server import auth, config, main, token_bootstrap
    from server.services import crypto_boot, native_locale, run_reaper

    async def nothing(*_a, **_k):
        pass

    async def stop_here():
        raise _BootWentOn

    monkeypatch.setattr(main, "engine", maker.kw["bind"])
    monkeypatch.setattr(config, "settings", SimpleNamespace(db_path=tmp_path / "unused.db", spawns_dir=tmp_path / "spawns"))
    monkeypatch.setattr(token_bootstrap, "bootstrap_api_token", lambda _: None)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-only")
    monkeypatch.setattr(main, "_validate_settings", lambda *a, **k: None)
    monkeypatch.setattr(main, "_log_data_location", lambda _: None)
    monkeypatch.setattr(main, "_boot_mcp", nothing)
    monkeypatch.setattr(crypto_boot, "resolve_and_adopt_salt", lambda _: None)
    monkeypatch.setattr(crypto_boot, "migrate_legacy_ciphertext", lambda _: None)
    monkeypatch.setattr(native_locale, "sync", nothing)
    monkeypatch.setattr(run_reaper, "mark_interrupted_runs", stop_here)

    async def boot():
        from fastapi import FastAPI
        with pytest.raises(_BootWentOn):
            async with main.lifespan(FastAPI()):
                pytest.fail("must stop at the run reaper")
    return boot


async def _boot_ledger(execution_db):
    async with execution_db() as session:
        session.add_all([
            _row("memory.merge", {"candidate": "the old words", "existing": "x"}),
            _row("memory.merge", {"candidate": DIGEST, "existing": DIGEST}),
            _row("memory.applied", {"lesson": "y", "steps": "[]"}, created_at=datetime.utcnow() - timedelta(days=95)),
        ])
        await session.commit()


async def test_boot_cleans_the_ledger_after_pruning_it(execution_db, tmp_path, monkeypatch):
    await _boot_ledger(execution_db)
    await _boot_past_the_ledger(monkeypatch, tmp_path, execution_db)()
    assert [(point, state) for point, state, _ in await _left(execution_db)] == [
        ("memory.merge", {"candidate": DIGEST, "existing": DIGEST})]


async def test_a_failing_clean_does_not_skip_the_prune_and_says_what_failed(execution_db, tmp_path, monkeypatch, caplog):
    await _boot_ledger(execution_db)

    async def broken():
        raise RuntimeError("synthetic clean failure")
    monkeypatch.setattr(judgment, "drop_unredacted", broken)
    await _boot_past_the_ledger(monkeypatch, tmp_path, execution_db)()
    assert [point for point, _, _ in await _left(execution_db)] == ["memory.merge", "memory.merge"]   # the old row pruned
    assert "judgment ledger clean failed" in caplog.text and "prune failed" not in caplog.text
