"""The health vocabulary the PROBE writes must be the vocabulary ROUTING reads.

🔴 THE DEFECT THIS FILE EXISTS FOR. ``_last_health_ok`` tested the persisted
``last_health`` string for membership in ``("ok", "healthy", "true", "1")``. The
only producer — ``server.services.provider_health.probe``, persisted verbatim by
``POST /settings/provider-configs/{id}/health`` — has only ever written
``reachable_models`` | ``reachable_no_list`` | ``unreachable``. Not one producer
value appears in the consumer's tuple, so EVERY probed config mapped to
``healthy=False`` and ``routing.usable()`` filtered it out of the candidate set.
Only never-probed configs (``last_health`` NULL → ``None``) stayed usable: a
config that had been tested and found HEALTHY was the one routing refused.

🔴 WHY IT NEVER LOOKED LIKE AN OUTAGE. ``select()`` ends in ``or primary``, so the
user's primary kept answering. Under any non-``single`` strategy, though, every
config the user had ever tested was silently dropped — the strategy still ran, it
just ran over the never-probed rows.

🔴 WHY THE EXISTING TESTS WERE GREEN. ``test_routing_never_picks_a_dead_config.py``
builds fixtures with ``healthy=True/False/None`` directly. It exercises
``usable()`` thoroughly and ``_last_health_ok`` not at all — the seam where the two
vocabularies meet is precisely the part no test crossed. A test written with
``"ok"``/``"healthy"`` would have passed against the broken code, which is the
whole failure mode; every literal in this file is a REAL one, and
``TestTheRealProbeReachesRouting`` takes its literal from ``probe()`` itself so
that no invented string can make it pass.
"""
from __future__ import annotations

import httpx
import pytest
from arslan.llm import routing
from server.db import session as db_session
from server.db.models import Base, ProviderConfig
from server.services import provider_config_service as svc

# The producer's three states, spelled out. Kept honest against probe() itself by
# TestTheMappingCannotDriftFromTheProducer below — this list is a convenience for
# the behavioural cases, not the source of truth.
REACHABLE_MODELS = "reachable_models"
REACHABLE_NO_LIST = "reachable_no_list"
UNREACHABLE = "unreachable"


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


class TestTheProbedStateMapsToTheTriState:
    """`is True` / `is False` / `is None`, never truthiness.

    The distinction between False and None is the entire point of the tri-state:
    ``usable()`` filters on ``healthy is not False``, so a None that degraded to
    False would filter, and a False that degraded to None would not. An
    ``assert not healthy`` here would accept both and discriminate nothing.
    """

    def test_reachable_models_is_healthy(self):
        assert svc._last_health_ok(_Row(REACHABLE_MODELS)) is True

    def test_reachable_no_list_is_healthy(self):
        # HTTP answered — the provider is up. This state also covers 401 and a
        # provider that simply exposes no /models endpoint, which is why probe()'s
        # own docstring calls it "NOT broken": many gateways gate /models harder
        # than /chat. A bad key is caught by key_state, and a genuinely dead one
        # fails at the provider with a real error — the standing fail-open rule on
        # the propose side.
        assert svc._last_health_ok(_Row(REACHABLE_NO_LIST)) is True

    def test_unreachable_is_not_healthy(self):
        assert svc._last_health_ok(_Row(UNREACHABLE)) is False

    def test_never_probed_is_unknown_not_dead(self):
        # NULL column. "Never checked" is not "checked and down": collapsing them
        # would make a fresh install with no probe history route nowhere.
        assert svc._last_health_ok(_Row(None)) is None

    def test_empty_string_is_unknown_not_dead(self):
        assert svc._last_health_ok(_Row("")) is None

    def test_an_unrecognised_state_is_unknown_not_dead(self):
        # Fail-open if a fourth state ever reaches a build whose mapping predates
        # it. The drift guard below turns that into a red test rather than a
        # silent behaviour change, but the runtime default must still not invent a
        # verdict it does not have.
        assert svc._last_health_ok(_Row("something_new")) is None


# ---------------------------------------------------------------------------
# the projection routing actually consumes
# ---------------------------------------------------------------------------


class TestRoutingSeesTheProbedConfigAsUsable:
    """The defect measured end to end: probed-and-healthy must not be filtered."""

    @pytest.mark.parametrize("state, expected_healthy, expected_usable", [
        (REACHABLE_MODELS, True, True),
        (REACHABLE_NO_LIST, True, True),
        (UNREACHABLE, False, False),
        (None, None, True),
    ])
    async def test_persisted_state_survives_to_usable(
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

    async def test_a_probed_healthy_config_is_a_routing_candidate(self, db):
        # 🔴 The headline case. Before the fix this config scored fine, was marked
        # healthy=False, and was filtered out; `or primary` then returned it anyway,
        # so the observable damage was confined to strategies with >1 candidate.
        db.add(ProviderConfig(label="probed", provider="anthropic", model="m",
                              api_key="", is_primary=False,
                              last_health=REACHABLE_MODELS))
        db.add(ProviderConfig(label="fresh", provider="qwen", model="m2",
                              api_key="", is_primary=True, last_health=None))
        await db.commit()

        rows = [{**r, "key_state": "set"} for r in await svc.list_for_routing(db)]
        candidates = [r["id"] for r in rows if routing.usable(r)]

        assert len(candidates) == 2, (
            "the probed config was dropped from routing for having been tested")


class TestTheRealProbeReachesRouting:
    """No literal from this file: probe() names the state, routing consumes it.

    ``fetch_models`` is stubbed one layer BELOW probe(), so the real probe decides
    the vocabulary. If that vocabulary changes, this test breaks without anyone
    having to remember to update a string here.
    """

    async def _probe_state(self, handler):
        from server.services import provider_health
        return (await provider_health.probe(
            "deepseek", "https://api.deepseek.com", "sk-x",
            transport=httpx.MockTransport(handler)))["state"]

    async def test_a_live_provider_probe_ends_up_usable(self, db):
        state = await self._probe_state(
            lambda r: httpx.Response(200, json={"data": [{"id": "m-1"}]}))

        # Persisted exactly as server/api/settings.py does: row.last_health = state
        db.add(ProviderConfig(label="A", provider="deepseek", model="deepseek-chat",
                              api_key="", is_primary=True, last_health=state))
        await db.commit()

        row = {**(await svc.list_for_routing(db))[0], "key_state": "set"}
        assert row["healthy"] is True
        assert routing.usable(row) is True

    async def test_a_refused_connection_probe_ends_up_unusable(self, db):
        def refuse(request):
            raise httpx.ConnectError("connection refused")

        state = await self._probe_state(refuse)

        db.add(ProviderConfig(label="A", provider="custom", model="m",
                              base_url="http://192.168.1.99:1234/v1",
                              api_key="", is_primary=True, last_health=state))
        await db.commit()

        row = {**(await svc.list_for_routing(db))[0], "key_state": "set"}
        assert row["healthy"] is False
        assert routing.usable(row) is False


# ---------------------------------------------------------------------------
# the drift guard
# ---------------------------------------------------------------------------


def _states_probe_can_return() -> set[str]:
    """Every literal ``"state"`` value in probe()'s source, read out of its AST.

    Discovery, not a restatement: a fourth ``return {"state": ...}`` added to
    probe() shows up here without anyone editing this file, which is the property
    that makes the guard worth having. A hand-kept copy of the list would drift in
    exactly the way it is supposed to catch.
    """
    import ast
    import inspect

    from server.services import provider_health

    tree = ast.parse(inspect.getsource(provider_health.probe))
    states = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "state":
                assert isinstance(value, ast.Constant), (
                    "probe() now builds its state dynamically; this guard can no "
                    "longer enumerate the vocabulary by reading the source and "
                    "needs rewriting rather than deleting")
                states.add(value.value)
    return states


class TestTheMappingCannotDriftFromTheProducer:
    """Ties the consumer's keys to the producer's returns, so they cannot part again.

    The original defect was not a typo, it was two files holding independent ideas
    of the same vocabulary with nothing asserting they matched.
    """

    def test_the_guard_can_actually_see_the_producers_states(self):
        # Without this, an AST walk that silently found nothing would make the
        # comparison below vacuous in the direction that matters.
        assert _states_probe_can_return() == {
            REACHABLE_MODELS, REACHABLE_NO_LIST, UNREACHABLE}

    def test_every_state_the_probe_can_write_has_an_explicit_mapping(self):
        missing = _states_probe_can_return() - set(svc._HEALTH_OK)
        assert not missing, (
            f"provider_health.probe() can persist {sorted(missing)}, which "
            f"_HEALTH_OK does not map. Unmapped states read as None (unknown), so "
            f"routing would treat a newly-added failure state as usable. Decide "
            f"True/False for each and add it.")

    def test_the_mapping_invents_no_state_the_probe_cannot_write(self):
        extra = set(svc._HEALTH_OK) - _states_probe_can_return()
        assert not extra, (
            f"_HEALTH_OK maps {sorted(extra)}, which probe() never writes — either "
            f"a rename landed on one side only, or this is dead vocabulary of the "
            f"kind that caused the original defect.")
