"""The verdict vocabulary must reach routing intact.

Two files have to agree on a small set of words: the one that WRITES
``ProviderConfig.last_health`` and the one that READS it. They have disagreed
twice, and both times the failure was silent — a config the user had tested was
the one routing refused, while never-tested rows stayed usable.

  1st: the reader tested for ("ok","healthy","true","1"). No writer ever wrote
       any of those, so every tested config read as healthy=False.
  2nd: the words were pinned to a /models probe that has since been deleted. It
       answered "did the list endpoint return anything" — and for a PUBLIC model
       list (OpenRouter's is public) that is 200 with no key at all, so a dead,
       capped, or region-blocked key still read as reachable.

Now there is exactly one writer, ``provider_config_service.record_test_verdict``,
fed by the real chat test. The drift guard at the bottom reads that function's
source, so the vocabulary is DISCOVERED here rather than restated — a third word
added to it turns this file red without anyone remembering to edit it.
"""
from __future__ import annotations

import pytest
from arslan.llm import routing
from server.db import session as db_session
from server.db.models import Base, ProviderConfig
from server.services import provider_config_service as svc

# The writer's two words, spelled out for the behavioural cases below. Kept
# honest against record_test_verdict itself by TestTheMappingCannotDriftFromThe
# Producer — this is a convenience, not the source of truth.
OK = "ok"
FAILED = "failed"


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        yield s


class _Row:
    """Minimal stand-in for a ProviderConfig row — _last_health_ok reads one attribute."""

    def __init__(self, last_health):
        self.last_health = last_health


# ---------------------------------------------------------------------------
# _last_health_ok — the tri-state, against the REAL vocabulary
# ---------------------------------------------------------------------------


class TestTheVerdictMapsToTheTriState:
    """`is True` / `is False` / `is None`, never truthiness.

    The distinction between False and None is the entire point of the tri-state:
    ``usable()`` filters on ``healthy is not False``, so a None that degraded to
    False would filter, and a False that degraded to None would not. An
    ``assert not healthy`` here would accept both and discriminate nothing.
    """

    def test_a_passing_chat_test_is_healthy(self):
        assert svc._last_health_ok(_Row(OK)) is True

    def test_a_failing_chat_test_is_not_healthy(self):
        # Unlike the old probe's "reachable_no_list", this carries no ambiguity to
        # fail open on: the exact call a real turn would make was made, and it did
        # not work. select() still keeps the primary regardless, so a transient
        # failure at launch cannot lock anyone out of their own default model.
        assert svc._last_health_ok(_Row(FAILED)) is False

    def test_never_tested_is_unknown_not_dead(self):
        # NULL column. "Never checked" is not "checked and down": collapsing them
        # would make a fresh install with no test history route nowhere. Migration
        # 0043 sets this deliberately when clearing the old vocabulary.
        assert svc._last_health_ok(_Row(None)) is None

    def test_empty_string_is_unknown_not_dead(self):
        assert svc._last_health_ok(_Row("")) is None

    def test_a_retired_word_is_unknown_not_dead(self):
        # A row written by a build that predates migration 0043 (or one the
        # migration missed) must fail OPEN, not read as broken.
        assert svc._last_health_ok(_Row("reachable_models")) is None

    def test_an_unrecognised_state_is_unknown_not_dead(self):
        # Fail-open if a third word ever reaches a build whose mapping predates
        # it. The drift guard below turns that into a red test rather than a
        # silent behaviour change, but the runtime default must still not invent
        # a verdict it does not have.
        assert svc._last_health_ok(_Row("something_new")) is None


# ---------------------------------------------------------------------------
# the projection routing actually consumes
# ---------------------------------------------------------------------------


class TestRoutingSeesTheTestedConfig:
    """The defect measured end to end: tested-and-passing must not be filtered."""

    @pytest.mark.parametrize("state, expected_healthy, expected_usable", [
        (OK, True, True),
        (FAILED, False, False),
        (None, None, True),
    ])
    async def test_persisted_verdict_survives_to_usable(
            self, db, state, expected_healthy, expected_usable):
        db.add(ProviderConfig(label="A", provider="deepseek", model="deepseek-chat",
                              api_key="", is_primary=True, last_health=state))
        await db.commit()

        row = (await svc.list_for_routing(db))[0]

        assert row["healthy"] is expected_healthy
        # key_state is "unset" here (no key), which usable() also filters on — so
        # assert the health half in isolation rather than letting an unrelated
        # filter decide the outcome and look like a pass.
        assert routing.usable({**row, "key_state": "set"}) is expected_usable

    async def test_a_tested_passing_config_is_a_routing_candidate(self, db):
        # 🔴 The headline case of the first defect: this config scored fine, was
        # marked healthy=False, and was filtered out; `or primary` then returned
        # it anyway, so the damage was confined to strategies with >1 candidate.
        db.add(ProviderConfig(label="tested", provider="anthropic", model="m",
                              api_key="", is_primary=False, last_health=OK))
        db.add(ProviderConfig(label="fresh", provider="qwen", model="m2",
                              api_key="", is_primary=True, last_health=None))
        await db.commit()

        rows = [{**r, "key_state": "set"} for r in await svc.list_for_routing(db)]
        candidates = [r["id"] for r in rows if routing.usable(r)]

        assert len(candidates) == 2, (
            "the tested config was dropped from routing for having been tested")


class TestTheRealWriterReachesRouting:
    """No literal from this file: record_test_verdict names the word, routing eats it.

    ``LLMAdapter.chat`` is stubbed one layer BELOW test_connection, so the real
    test path and the real writer decide the vocabulary between them. If that
    vocabulary changes, this breaks without anyone updating a string here.
    """

    async def _verdict_row(self, db, monkeypatch, chat_impl, **row_kw):
        from server.services.llm_test import test_connection

        monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", chat_impl)
        result = await test_connection("deepseek", "deepseek-chat", "", "sk-x")

        row = ProviderConfig(label="A", provider="deepseek", model="deepseek-chat",
                             api_key="", is_primary=True, **row_kw)
        # Exactly what server/api/settings.py does with the result.
        svc.record_test_verdict(row, ok=bool(result["ok"]), detail=result.get("error"))
        db.add(row)
        await db.commit()
        return row

    async def test_a_working_llm_ends_up_usable(self, db, monkeypatch):
        from arslan.models import LLMResponse

        async def _ok(self, system, user, **kwargs):  # noqa: ARG001
            return LLMResponse(content="pong", tool_calls=[], usage={})

        row = await self._verdict_row(db, monkeypatch, _ok)
        assert row.last_health_detail is None

        projected = {**(await svc.list_for_routing(db))[0], "key_state": "set"}
        assert projected["healthy"] is True
        assert routing.usable(projected) is True

    async def test_a_refusing_llm_ends_up_unusable_and_keeps_its_reason(self, db, monkeypatch):
        import httpx

        async def _refuse(self, system, user, **kwargs):  # noqa: ARG001
            request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            body = '{"error":{"message":"Key limit exceeded"}}'
            raise httpx.HTTPStatusError(
                f"403 error: {body}", request=request,
                response=httpx.Response(403, request=request, text=body))

        row = await self._verdict_row(db, monkeypatch, _refuse)

        projected = {**(await svc.list_for_routing(db))[0], "key_state": "set"}
        assert projected["healthy"] is False
        assert routing.usable(projected) is False
        # The reason is persisted, not merely rendered once: a "failed" with no
        # cause is only marginally more useful than a green dot that lies.
        assert row.last_health_detail is not None
        assert "额度上限" in row.last_health_detail


# ---------------------------------------------------------------------------
# the drift guard
# ---------------------------------------------------------------------------


def _words_the_writer_can_persist() -> set[str]:
    """Every literal assigned to ``row.last_health`` in record_test_verdict's source.

    Discovery, not a restatement: a third word added to that function shows up
    here without anyone editing this file, which is the property that makes the
    guard worth having. A hand-kept copy would drift in exactly the way it is
    supposed to catch.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(svc.record_test_verdict))
    words: set[str] = set()
    found_target = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Attribute) and t.attr == "last_health"
                   for t in node.targets):
            continue
        found_target = True
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                words.add(sub.value)
    assert found_target, (
        "record_test_verdict no longer assigns row.last_health directly; this "
        "guard can no longer enumerate the vocabulary by reading the source and "
        "needs rewriting rather than deleting")
    return words


class TestTheMappingCannotDriftFromTheProducer:
    """Ties the reader's keys to the writer's literals, so they cannot part again.

    Neither defect was a typo. Both times two files held independent ideas of the
    same vocabulary with nothing asserting they matched.
    """

    def test_the_guard_can_actually_see_the_writers_words(self):
        # Without this, an AST walk that silently found nothing would make the
        # comparison below vacuous in the direction that matters.
        assert _words_the_writer_can_persist() == {OK, FAILED}

    def test_every_word_the_writer_can_persist_has_an_explicit_mapping(self):
        missing = _words_the_writer_can_persist() - set(svc._HEALTH_OK)
        assert not missing, (
            f"record_test_verdict can persist {sorted(missing)}, which _HEALTH_OK "
            f"does not map. Unmapped words read as None (unknown), so routing "
            f"would treat a newly-added failure state as usable. Decide "
            f"True/False for each and add it.")

    def test_the_mapping_invents_no_word_the_writer_cannot_persist(self):
        extra = set(svc._HEALTH_OK) - _words_the_writer_can_persist()
        assert not extra, (
            f"_HEALTH_OK maps {sorted(extra)}, which record_test_verdict can no "
            f"longer write. Dead keys are how the first defect hid: the mapping "
            f"looked considered while matching nothing the producer emitted.")
