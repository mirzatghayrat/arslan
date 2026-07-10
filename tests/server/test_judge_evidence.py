"""E1: the single-run judge sees the trace (step evidence) + continuation skew fix.

- score() must inject the run's RunStep evidence block into the judge prompt, with
  the instruction that fabrication is judged as the diff between claimed
  deliverables and the ACTUAL recorded tool_calls.
- A continuation (auto-continue) round is judged on THIS round's incremental goal,
  not the full original request — the prompt carries that instruction only for
  continuation runs.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.models import LLMResponse
from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunStep, Spawn
from server.services import run_eval_service, run_recorder
from server.services.prompts.run_judge import CONTINUATION_LINE


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    # fresh continuation registry per test (module-level state)
    monkeypatch.setattr(run_recorder, "_continuation_run_ids", set())
    yield Session


_GOOD_VERDICT = (
    '{"dimensions": {'
    '"routing": {"status": "pass", "score": 9, "comment": "ok"},'
    '"fabrication": {"status": "pass", "score": 8, "comment": "ok"},'
    '"identity": {"status": "pass", "score": 10, "comment": "ok"},'
    '"completion": {"status": "pass", "score": 8, "comment": "ok"}},'
    '"overall": {"score": 8, "badge": "good"}}'
)


def _capture_adapter(monkeypatch, seen: dict):
    class _Adapter:
        async def chat(self, system, user):
            seen["system"], seen["user"] = system, user
            return LLMResponse(content=_GOOD_VERDICT, usage={})

    async def fake_build(role=None):
        return _Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)


async def _seed_run(Session, *, steps: list[dict] = ()) -> int:
    async with Session() as db:
        spawn = Spawn(name="Mermer", domain_category="research", system_prompt="You research.")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        run = Run(conversation_id="c1", spawn_id=spawn.id, spawn_name="Mermer",
                  user_message="查上海天气", status="recorded", task_tokens=10)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                             content="s", display_content="今天上海晴", run_id=run.id))
        for i, s in enumerate(steps):
            db.add(RunStep(run_id=run.id, seq=i, **s))
        await db.commit()
        return run.id


async def test_judge_prompt_contains_step_evidence(memdb, monkeypatch):
    run_id = await _seed_run(memdb, steps=[
        {"kind": "tool_call", "ref": {"tool": "web_search", "ok": True},
         "detail": {"args_summary": "q=上海天气", "summary": "found 3 sources"}},
    ])
    seen: dict = {}
    _capture_adapter(monkeypatch, seen)
    await run_eval_service.score(run_id)
    # the rendered step-evidence line is in the judge prompt
    assert "[tool_call] tool=web_search args=q=上海天气 → ok found 3 sources" in seen["user"]
    # and the fabrication-as-diff instruction rides along
    assert "宣称交付物 vs 实际 tool_call" in seen["user"]


async def test_judge_prompt_no_evidence_block_when_no_steps(memdb, monkeypatch):
    run_id = await _seed_run(memdb, steps=[])
    seen: dict = {}
    _capture_adapter(monkeypatch, seen)
    await run_eval_service.score(run_id)
    assert "宣称交付物 vs 实际 tool_call" not in seen["user"]


async def test_continuation_run_prompt_has_incremental_instruction(memdb, monkeypatch):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="继续", continuation=True,
    )
    seen: dict = {}
    _capture_adapter(monkeypatch, seen)
    await run_eval_service.score(rec.run_id)
    assert CONTINUATION_LINE in seen["user"]


async def test_normal_run_prompt_has_no_incremental_instruction(memdb, monkeypatch):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c1", spawn_id=None, spawn_name="Mermer",
        user_message="查天气",
    )
    seen: dict = {}
    _capture_adapter(monkeypatch, seen)
    await run_eval_service.score(rec.run_id)
    assert CONTINUATION_LINE not in seen["user"]
