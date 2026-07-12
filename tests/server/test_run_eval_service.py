import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.models import LLMResponse
from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunEvaluation, RunStep, Spawn
from server.services import run_eval_service


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_run(Session, *, output: str = "今天晴",
                    step_kinds: tuple[str, ...] = ()) -> int:
    async with Session() as db:
        spawn = Spawn(name="Mermer", domain_category="research", system_prompt="You research.")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        run = Run(conversation_id="c1", spawn_id=spawn.id, spawn_name="Mermer",
                  user_message="查天气", status="recorded", task_tokens=10)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                             content="s", display_content=output, run_id=run.id))
        for i, kind in enumerate(step_kinds, start=1):
            db.add(RunStep(run_id=run.id, seq=i, kind=kind))
        await db.commit()
        return run.id


_GOOD_VERDICT = (
    '{"dimensions": {'
    '"routing": {"status": "pass", "score": 9, "comment": "选对了人"},'
    '"fabrication": {"status": "pass", "score": 8, "comment": "无编造"},'
    '"identity": {"status": "pass", "score": 10, "comment": "身份一致"},'
    '"completion": {"status": "warn", "score": 6, "comment": "略简略"}},'
    '"overall": {"score": 8, "badge": "good"}}'
)


async def test_score_persists_dimensions_and_overall(memdb, monkeypatch):
    run_id = await _seed_run(memdb)

    class _Adapter:
        async def chat(self, system, user):
            return LLMResponse(content=_GOOD_VERDICT, usage={})

    async def fake_build(role=None):
        return _Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)

    await run_eval_service.score(run_id)

    async with memdb() as db:
        run = await db.get(Run, run_id)
        dims = (await db.execute(
            select(RunEvaluation).where(RunEvaluation.run_id == run_id)
        )).scalars().all()

    assert run.status == "scored"
    assert run.overall_score == 8
    assert run.overall_badge == "good"
    assert {d.dimension for d in dims} == {"routing", "fabrication", "identity", "completion"}


async def test_score_marks_failed_on_unparseable(memdb, monkeypatch):
    run_id = await _seed_run(memdb)

    class _Adapter:
        async def chat(self, system, user):
            return LLMResponse(content="not json at all", usage={})

    async def fake_build(role=None):
        return _Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)

    await run_eval_service.score(run_id)

    async with memdb() as db:
        run = await db.get(Run, run_id)
    assert run.status == "score_failed"


# --- HX-5 A4: deterministic fabrication pre-check --------------------------------

_PROMISING_OUTPUT = "我把 PPT 交给 Deck Master 来生成,它正在生成中,稍等"


def _capturing_adapter(seen: dict):
    class _Adapter:
        async def chat(self, system, user):
            seen["system"], seen["user"] = system, user
            return LLMResponse(content=_GOOD_VERDICT, usage={})
    return _Adapter


async def _score_captured(memdb, monkeypatch, *, output: str,
                          step_kinds: tuple[str, ...] = ()) -> tuple[int, dict]:
    run_id = await _seed_run(memdb, output=output, step_kinds=step_kinds)
    seen: dict = {}
    Adapter = _capturing_adapter(seen)

    async def fake_build(role=None):
        return Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)
    await run_eval_service.score(run_id)
    return run_id, seen


async def _fabrication_comment(memdb, run_id: int) -> str:
    async with memdb() as db:
        row = (await db.execute(
            select(RunEvaluation).where(RunEvaluation.run_id == run_id,
                                        RunEvaluation.dimension == "fabrication")
        )).scalars().first()
    return row.comment


async def test_fabrication_signal_promise_without_tool_calls(memdb, monkeypatch):
    """Promise language + zero tool_call steps → signal injected into the judge
    prompt AND recorded in the persisted fabrication verdict."""
    run_id, seen = await _score_captured(memdb, monkeypatch,
                                         output=_PROMISING_OUTPUT, step_kinds=("route", "dispatch"))
    assert "确定性预检" in seen["user"]
    assert "fabrication" in seen["user"]
    comment = await _fabrication_comment(memdb, run_id)
    assert comment.startswith("[fabrication_signal]")


async def test_no_fabrication_signal_when_tool_calls_present(memdb, monkeypatch):
    """Same promising text but the run really called tools → honest narration, no signal."""
    run_id, seen = await _score_captured(memdb, monkeypatch,
                                         output=_PROMISING_OUTPUT,
                                         step_kinds=("route", "dispatch", "tool_call"))
    assert "确定性预检" not in seen["user"]
    comment = await _fabrication_comment(memdb, run_id)
    assert not comment.startswith("[fabrication_signal]")


async def test_no_fabrication_signal_on_honest_text(memdb, monkeypatch):
    run_id, seen = await _score_captured(memdb, monkeypatch, output="今天晴,气温 28 度。")
    assert "确定性预检" not in seen["user"]
    comment = await _fabrication_comment(memdb, run_id)
    assert not comment.startswith("[fabrication_signal]")


# --- Provider-P4: defensive judge parsing + failure-reason persistence ------------


def _adapter_returning(content: str):
    class _Adapter:
        async def chat(self, system, user):
            return LLMResponse(content=content, usage={})
    return _Adapter


async def _score_with(memdb, monkeypatch, content: str, *, run_id: int | None = None) -> int:
    if run_id is None:
        run_id = await _seed_run(memdb)
    Adapter = _adapter_returning(content)

    async def fake_build(role=None):
        return Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)
    await run_eval_service.score(run_id)
    return run_id


async def _run_and_dims(memdb, run_id: int):
    async with memdb() as db:
        run = await db.get(Run, run_id)
        dims = {d.dimension: d for d in (await db.execute(
            select(RunEvaluation).where(RunEvaluation.run_id == run_id)
        )).scalars().all()}
    return run, dims


async def test_score_failed_persists_reason(memdb, monkeypatch):
    """(a) Plain non-JSON judge output → score_failed AND the reason lands on
    the run row (error_kind/error_text), not only in a log line."""
    run_id = await _score_with(memdb, monkeypatch, "totally not json")
    run, _ = await _run_and_dims(memdb, run_id)
    assert run.status == "score_failed"
    assert run.error_kind == "score_failed"
    assert run.error_text and "dimensions" in run.error_text


async def test_string_dimension_degrades_to_warn_not_fail(memdb, monkeypatch):
    """(b) A weak model wrote a bare string for ONE dimension → that dim
    degrades to warn/0 with the string preserved; the eval still lands."""
    verdict = (
        '{"dimensions": {'
        '"routing": "looks fine",'
        '"fabrication": {"status": "pass", "score": 8, "comment": "无编造"},'
        '"identity": {"status": "pass", "score": 10, "comment": "身份一致"},'
        '"completion": {"status": "warn", "score": 6, "comment": "略简略"}},'
        '"overall": {"score": 7, "badge": "ok"}}'
    )
    run_id = await _score_with(memdb, monkeypatch, verdict)
    run, dims = await _run_and_dims(memdb, run_id)
    assert run.status == "scored"
    assert dims["routing"].status == "warn"
    assert dims["routing"].score == 0.0
    assert "looks fine" in dims["routing"].comment
    # the other dimensions parse normally
    assert dims["fabrication"].status == "pass"
    assert dims["fabrication"].score == 8
    assert dims["identity"].score == 10


async def test_dimensions_non_dict_is_score_failed_with_clear_reason(memdb, monkeypatch):
    """(c) "dimensions" itself is a string → whole eval fails with a clear reason."""
    run_id = await _score_with(
        memdb, monkeypatch,
        '{"dimensions": "all good", "overall": {"score": 9, "badge": "good"}}')
    run, _ = await _run_and_dims(memdb, run_id)
    assert run.status == "score_failed"
    assert run.error_kind == "score_failed"
    assert "非对象" in (run.error_text or "")


async def test_overall_non_dict_degrades_to_zero_ok(memdb, monkeypatch):
    """(d) "overall" as a string degrades to score 0 / badge ok — still scored."""
    verdict = (
        '{"dimensions": {'
        '"routing": {"status": "pass", "score": 9, "comment": "ok"}},'
        '"overall": "great"}'
    )
    run_id = await _score_with(memdb, monkeypatch, verdict)
    run, _ = await _run_and_dims(memdb, run_id)
    assert run.status == "scored"
    assert run.overall_score == 0
    assert run.overall_badge == "ok"


async def test_overall_non_numeric_score_degrades_to_zero_not_fail(memdb, monkeypatch):
    """(d') A weak judge emits a NON-NUMERIC overall score (a bare word) while
    the dimensions parse fine → the run must still land SCORED with
    overall_score 0.0 (badge preserved), NOT collapse to score_failed."""
    verdict = (
        '{"dimensions": {'
        '"routing": {"status": "pass", "score": 9, "comment": "ok"}},'
        '"overall": {"score": "high", "badge": "good"}}'
    )
    run_id = await _score_with(memdb, monkeypatch, verdict)
    run, dims = await _run_and_dims(memdb, run_id)
    assert run.status == "scored"
    assert run.overall_score == 0.0
    assert run.overall_badge == "good"
    assert dims["routing"].score == 9


async def test_existing_error_kind_never_clobbered(memdb, monkeypatch):
    """(e) A run that already carries a REAL error keeps it — score_failed must
    not overwrite error_kind/error_text."""
    run_id = await _seed_run(memdb)
    async with memdb() as db:
        run = await db.get(Run, run_id)
        run.error_kind = "llm_error"
        run.error_text = "upstream 500"
        await db.commit()
    await _score_with(memdb, monkeypatch, "not json", run_id=run_id)
    run, _ = await _run_and_dims(memdb, run_id)
    assert run.status == "score_failed"
    assert run.error_kind == "llm_error"
    assert run.error_text == "upstream 500"


async def test_fenced_json_still_scores(memdb, monkeypatch):
    """(f) Regression pin: ```json fenced``` judge output keeps parsing to scored."""
    run_id = await _score_with(memdb, monkeypatch, f"```json\n{_GOOD_VERDICT}\n```")
    run, dims = await _run_and_dims(memdb, run_id)
    assert run.status == "scored"
    assert run.overall_badge == "good"
    assert set(dims) == {"routing", "fabrication", "identity", "completion"}
