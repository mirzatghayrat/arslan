"""MEM1 (#559), its fail-safe through the real judge (②Main's point 7: no model means no merge, never a merge on a
guess). #559's own test fakes `judgment.judge` returning None; these go through judgment.judge itself, so the ways
it gives no answer are the real ones: judging switched off, the daily token cap, no model, a timeout. In each, the
same meaning in other words is stored as a new entry. A positive control shows a real "yes" does merge."""
import asyncio
import dataclasses
import json

import pytest
from sqlalchemy import select

from arslan.models import LLMResponse
from server.db.companion_models import MemoryEntry
from server.services import judgment
from tests.server.test_inb2_about_you_direct import _write, memory  # noqa: F401  (the fixture)

FIRST = "The user prefers short answers"
SAME = "The user likes brief replies"


class Model:
    """The judge's model: answers "same" with p=0.99, or waits `delay` seconds first."""

    def __init__(self, delay: float = 0.0):
        self.delay, self.calls, self.model = delay, 0, "fake-judge"

    async def chat(self, system, user, **kwargs):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return LLMResponse(content=json.dumps({"answer": True, "p": 0.99}), usage={})


@pytest.fixture
def model(monkeypatch):
    fake = Model()

    async def adapter():
        return fake
    monkeypatch.setattr(judgment, "_adapter", adapter)
    return fake


async def _rows(db):
    async with db() as session:
        return (await session.scalars(select(MemoryEntry).where(MemoryEntry.kind == "preference"))).all()


async def test_a_real_yes_merges(memory, model):  # noqa: F811
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert model.calls == 1 and len(await _rows(memory)) == 1               # positive control


async def test_judging_switched_off_stores_a_new_entry(memory, model, monkeypatch):  # noqa: F811
    point = judgment.REGISTRY["memory.merge"]
    monkeypatch.setitem(judgment.REGISTRY, "memory.merge", dataclasses.replace(point, mode="off"))
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert model.calls == 0 and len(await _rows(memory)) == 2


async def test_over_the_daily_cap_stores_a_new_entry(memory, model, monkeypatch):  # noqa: F811
    async def spent(db):
        return judgment.DAILY_TOKEN_CAP
    monkeypatch.setattr(judgment, "_tokens_today", spent)
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert model.calls == 0 and len(await _rows(memory)) == 2


async def test_no_model_stores_a_new_entry(memory, monkeypatch):  # noqa: F811
    """The real path: no provider configured, so llm_factory.build_adapter raises ModelNotConfiguredError
    (_legacy_build_adapter) before any network call, and the judge records that and answers nothing. tests/conftest.py
    stubs judgment._adapter for every test, so its own two lines are put back here."""
    from server.db.models import Judgment
    from server.services.llm_factory import build_adapter, build_slot_adapter

    async def real_adapter():                                               # judgment._adapter, as written
        slotted = await build_slot_adapter("router_config_id")
        return slotted if slotted is not None else await build_adapter(role="router")
    monkeypatch.setattr(judgment, "_adapter", real_adapter)
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert len(await _rows(memory)) == 2
    async with memory() as session:
        errors = (await session.scalars(select(Judgment.error).where(Judgment.point == "memory.merge"))).all()
    assert errors == ["ModelNotConfiguredError"]


async def test_a_judge_that_times_out_stores_a_new_entry(memory, model, monkeypatch):  # noqa: F811
    model.delay = 1.0
    monkeypatch.setattr(judgment, "AFTER_TURN_TIMEOUT_S", 0.05)
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert model.calls == 1 and len(await _rows(memory)) == 2
