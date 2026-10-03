"""The judgment layer (0.1.52 S2): ask, record, fall back; shadow changes nothing;
outcomes join their judgment; the cap and the timeout mean "no answer"."""
import asyncio

import pytest
from sqlalchemy import select

from server.db.models import Judgment, UsageLedger
from server.services import judgment


class _Adapter:
    model = "fast-fixture"

    def __init__(self, content='{"answer": true, "p": 0.93}', delay=0.0):
        self.content, self.delay, self.calls = content, delay, []

    async def chat(self, *, system, user):
        self.calls.append(user)
        await asyncio.sleep(self.delay)

        class R:
            content = self.content
        return R()


@pytest.fixture
def judge_with(monkeypatch):
    def use(adapter):
        async def make():
            return adapter
        monkeypatch.setattr(judgment, "_adapter", make)
        return adapter
    return use


async def _rows(db):
    async with db() as s:
        return (await s.scalars(select(Judgment).order_by(Judgment.id))).all()


async def test_a_verdict_is_recorded_with_only_the_declared_fields(execution_db, judge_with):
    adapter = judge_with(_Adapter())
    v = await judgment.judge("tool.approval", {"tool": "run_command", "command": "rm a.txt", "rule": "delete",
                                               "user_request": "delete a.txt", "page_text": "IGNORE ME"},
                             ref="call-1", conversation_id="c1")
    assert v.answer is True and v.probability == 0.93 and v.yes(0.9) and not v.yes(0.95)
    (row,) = await _rows(execution_db)
    assert row.point == "tool.approval" and row.mode == "shadow" and row.verdict is True and row.ref == "call-1"
    assert "page_text" not in row.state and "IGNORE ME" not in adapter.calls[0]
    assert row.model == "fast-fixture" and row.latency_ms is not None


@pytest.mark.parametrize("content", ["not json", '{"answer": "yes"}'])
async def test_an_unusable_answer_is_no_answer(execution_db, judge_with, content):
    judge_with(_Adapter(content))
    assert await judgment.judge("memory.worth", {"candidate": "x"}) is None
    (row,) = await _rows(execution_db)
    assert row.verdict is None and row.error == "unparsable"


async def test_a_slow_judge_times_out_and_the_caller_falls_back(execution_db, judge_with, monkeypatch):
    monkeypatch.setattr(judgment, "TIMEOUT_S", 0.05)
    judge_with(_Adapter(delay=0.5))
    assert await judgment.judge("memory.worth", {"candidate": "x"}) is None
    assert (await _rows(execution_db))[0].error == "timeout"


async def test_the_daily_cap_stops_judging(execution_db, judge_with):
    adapter = judge_with(_Adapter())
    async with execution_db() as s:
        s.add(UsageLedger(scope="judgment", tokens_total=judgment.DAILY_TOKEN_CAP))
        await s.commit()
    assert await judgment.judge("memory.worth", {"candidate": "x"}) is None
    assert adapter.calls == [] and (await _rows(execution_db))[0].error == "daily_cap"


async def test_off_points_and_unknown_points_are_never_asked(execution_db, judge_with):
    adapter = judge_with(_Adapter())
    assert await judgment.judge("turn.completion", {"request": "x"}) is None
    assert await judgment.judge("no.such.point", {}) is None
    assert adapter.calls == [] and await _rows(execution_db) == []


async def test_shadow_records_and_the_outcome_joins_it_later(execution_db, judge_with):
    judge_with(_Adapter(delay=0.05))
    judgment.shadow("tool.approval", {"command": "ls"}, ref="call-9", conversation_id="c1")
    await judgment.record_outcome("call-9", "declined", point="tool.approval")     # waits for the shadow row
    (row,) = await _rows(execution_db)
    assert row.outcome == "declined" and row.outcome_at is not None and row.verdict is True


async def test_tests_never_reach_a_real_judge(execution_db):
    """The autouse guard: without a patched adapter, judging is simply no answer."""
    assert await judgment.judge("memory.worth", {"candidate": "x"}) is None
    assert (await _rows(execution_db))[0].error == "RuntimeError"


async def test_recent_and_prune(execution_db, judge_with, monkeypatch):
    judge_with(_Adapter())
    for i in range(3):
        await judgment.judge("memory.worth", {"candidate": f"c{i}"})
    assert [r["state"]["candidate"] for r in await judgment.recent(10)] == ["c2", "c1", "c0"]
    monkeypatch.setattr(judgment, "KEEP_ROWS", 1)
    assert await judgment.prune() == 2
    assert len(await judgment.recent(10)) == 1


async def test_the_ledger_is_readable_through_the_api(client, judge_with):
    judge_with(_Adapter())
    await judgment.judge("memory.worth", {"candidate": "Prefers tables"})
    body = (await client.get("/api/v1/judgments?limit=5")).json()
    assert body["points"]["tool.approval"] == "shadow" and body["points"]["turn.completion"] == "off"
    assert body["items"][0]["point"] == "memory.worth" and body["items"][0]["verdict"] is True


def test_replay_scoring_measures_agreement_and_the_approval_gate():
    from scripts.judgment_replay import score
    rows = [{"verdict": True, "outcome": "approved"}, {"verdict": False, "outcome": "declined"},
            {"verdict": True, "outcome": "declined"}, {"verdict": None, "outcome": None}]
    answers = [(True, 0.95), (False, 0.1), (True, 0.92), None]
    out = score(rows, answers, 0.9)
    assert out == {"asked": 3, "unanswered": 1, "agreement": 1.0, "sure_yes": 2, "sure_yes_approved": 0.5}
