import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import phase_service
from server.services import staffing_gather as sg


def test_prompt_distinguishes_one_off_from_recurring():
    """Fix #1: _SYSTEM prompt must express false (one-off) not just true/null."""
    assert "false" in sg._SYSTEM
    assert "one-off" in sg._SYSTEM


def test_merge_does_not_overwrite_with_null():
    old = {"domain": "game-design.numerical", "capability": None, "first_task": None, "recurrence": None}
    new = {"domain": None, "capability": "概率建模", "first_task": None, "recurrence": None}
    assert sg.merge_slots(old, new) == {
        "domain": "game-design.numerical", "capability": "概率建模",
        "first_task": None, "recurrence": None}


def test_is_ready_requires_all_four():
    assert sg.is_ready({"domain": "a.b", "capability": "c", "first_task": "t", "recurrence": True}) is True
    assert sg.is_ready({"domain": "a.b", "capability": "c", "first_task": "t", "recurrence": None}) is False
    assert sg.is_ready({"domain": None, "capability": "c", "first_task": "t", "recurrence": True}) is False


def test_missing_slots_lists_nulls():
    assert sg.missing_slots({"domain": "a.b", "capability": None,
                             "first_task": None, "recurrence": True}) == ["capability", "first_task"]


async def test_extract_slots_returns_nullable(monkeypatch):
    class Resp:
        content = ('{"domain":"game-design.numerical","capability":"概率建模",'
                   '"first_task":null,"recurrence":null}')
    class A:
        async def chat(self, *, system, user): return Resp()
    monkeypatch.setattr(sg, "_get_adapter", lambda: A())
    out = await sg.extract_slots("做个手游数值的分身，要做概率建模")
    assert out["domain"] == "game-design.numerical"
    assert out["capability"] == "概率建模"
    assert out["first_task"] is None and out["recurrence"] is None


def test_is_ready_with_false_recurrence():
    # recurrence=False is a filled state (user signalled NOT recurring), not missing.
    assert sg.is_ready({"domain": "a.b", "capability": "c", "first_task": "t", "recurrence": False}) is True


async def test_extract_slots_normalizes_false_recurrence(monkeypatch):
    # A literal false recurrence must pass through, NOT be coerced to None.
    class Resp:
        content = '{"domain":"a","capability":"b","first_task":"c","recurrence":false}'
    class A:
        async def chat(self, *, system, user): return Resp()
    monkeypatch.setattr(sg, "_get_adapter", lambda: A())
    out = await sg.extract_slots("one-off task, not recurring")
    assert out["recurrence"] is False


async def test_extract_slots_wraps_history_in_external_delimiters(monkeypatch):
    """Fix #4: extract_slots must wrap history_text with wrap_external before
    sending to the LLM so injected spawn/attached content cannot forge slot values."""
    captured = {}

    class Resp:
        content = '{"domain":"a","capability":"b","first_task":"c","recurrence":false}'

    class A:
        async def chat(self, *, system, user):
            captured["user"] = user
            return Resp()

    monkeypatch.setattr(sg, "_get_adapter", lambda: A())
    history = "user: build me a researcher spawn\narslan: on it"
    await sg.extract_slots(history)
    wrapped = captured.get("user", "")
    from server.orchestrator.untrusted import DELIM_OPEN, DELIM_CLOSE
    assert DELIM_OPEN in wrapped, "wrap_external opening delimiter must appear in LLM user arg"
    assert DELIM_CLOSE in wrapped, "wrap_external closing delimiter must appear in LLM user arg"
    assert history in wrapped, "original history_text must be present inside the wrapped content"


# --- Phase round-trip tests (use real in-memory DB like test_phase_service.py) ---


@pytest_asyncio.fixture
async def temp_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


@pytest.mark.asyncio
async def test_set_get_gathering_round_trip(temp_db):
    slots = {"domain": "game-design.numerical", "capability": "概率建模",
             "first_task": None, "recurrence": None}
    await phase_service.set_gathering("conv-gather", slots)
    got = await phase_service.get_gathered_slots("conv-gather")
    assert got == slots


@pytest.mark.asyncio
async def test_get_gathered_slots_returns_empty_when_no_phase(temp_db):
    result = await phase_service.get_gathered_slots("conv-nonexistent")
    assert result == {}


@pytest.mark.asyncio
async def test_get_gathered_slots_returns_empty_when_wrong_phase(temp_db):
    await phase_service.set_proposing("conv-proposing", 5, "some direction")
    result = await phase_service.get_gathered_slots("conv-proposing")
    assert result == {}


# --------------------------------------------------------------------------- BUG1 domain-conflict extraction


async def test_extract_conflicting_domain_affirmative(monkeypatch):
    """Happy path: the model names one of the OTHER registry domains -> returned.
    The allowed list + pick domain live in the USER turn (prompt-cache discipline:
    system stays static) and the task text is wrap_external'd."""
    captured = {}

    class Resp:
        content = '{"domain":"marketing.content-copywriting"}'

    class A:
        async def chat(self, *, system, user):
            captured.update(system=system, user=user)
            return Resp()

    monkeypatch.setattr(sg, "_get_adapter", lambda: A())
    out = await sg.extract_conflicting_domain(
        "把报告里的 CSS 图换成 Mermaid", "engineering.software-development",
        ["design.presentation", "marketing.content-copywriting"])
    assert out == "marketing.content-copywriting"
    assert "engineering.software-development" in captured["user"]
    assert "design.presentation" in captured["user"]
    assert "marketing.content-copywriting" not in captured["system"]
    from server.orchestrator.untrusted import DELIM_CLOSE, DELIM_OPEN
    assert DELIM_OPEN in captured["user"] and DELIM_CLOSE in captured["user"]


async def test_extract_conflicting_domain_null_and_off_list(monkeypatch):
    """null -> None; the pick's own domain or anything off the OTHER list -> None."""
    responses = iter(['{"domain": null}',
                      '{"domain": "engineering.software-development"}',
                      '{"domain": "made-up.thing"}'])

    class A:
        async def chat(self, *, system, user):
            class R:
                content = next(responses)
            return R()

    monkeypatch.setattr(sg, "_get_adapter", lambda: A())
    args = ("task", "engineering.software-development", ["marketing.content-copywriting"])
    assert await sg.extract_conflicting_domain(*args) is None
    assert await sg.extract_conflicting_domain(*args) is None
    assert await sg.extract_conflicting_domain(*args) is None


async def test_extract_conflicting_domain_garbage_and_raise(monkeypatch):
    """Best-effort: unparseable output or a raising adapter -> None, never an exception."""
    class Bad:
        async def chat(self, *, system, user):
            class R:
                content = "not json at all"
            return R()

    monkeypatch.setattr(sg, "_get_adapter", lambda: Bad())
    assert await sg.extract_conflicting_domain("t", "a.b", ["c.d"]) is None

    class Boom:
        async def chat(self, *, system, user):
            raise RuntimeError("adapter dead")

    monkeypatch.setattr(sg, "_get_adapter", lambda: Boom())
    assert await sg.extract_conflicting_domain("t", "a.b", ["c.d"]) is None
