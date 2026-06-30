"""Task B5: propose_invite confirmation frame (no auto-join).

Arslan PROPOSES bringing an existing, not-yet-in-roster spawn into the
conversation rather than silently auto-joining. The frontend renders a
confirmation card; on confirm it sends the EXISTING `roster_invite` frame,
which joins exactly that one spawn. So this task only adds the proposal seam:
emit `propose_invite{spawn_id, reason}` and join NOTHING.
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.orchestrator import arslan
from server.ws import protocol


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'invite.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(
                Spawn(
                    id=7,
                    name="seo-auditor",
                    domain_category="marketing",
                    domain_subcategory="seo",
                    capabilities=["seo-audit"],
                    persona_role="audits sites for SEO issues",
                    system_prompt="You are an SEO analyst.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_propose_invite_frame_shape():
    f = protocol.propose_invite(spawn_id=12, reason="best fit for the SEO subtask")
    assert f == {"type": "propose_invite", "spawn_id": 12, "reason": "best fit for the SEO subtask"}


def test_propose_invite_helper_emits_and_does_not_join(monkeypatch):
    """The orchestrator helper emits a propose_invite frame and never joins the roster."""
    joined: list = []

    async def _fake_join(*args, **kwargs):  # pragma: no cover - asserts it's NOT called
        joined.append((args, kwargs))
        return True

    async def _fake_get_spawn_name(spawn_id):
        return "Mermer"

    monkeypatch.setattr(arslan.roster_service, "join", _fake_join)
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", _fake_get_spawn_name)

    frames: list = []

    async def _run():
        await arslan.propose_invite(
            "conv-1", spawn_id=7, reason="best fit for the SEO subtask", emit=frames.append
        )

    anyio.run(_run)

    assert {"type": "propose_invite", "spawn_id": 7, "reason": "best fit for the SEO subtask"} in frames
    assert joined == [], "propose step must NOT join the roster"


# ---------------------------------------------------------------------------
# Inline roster-invite flow: route → propose (no dispatch) when spawn not in roster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_to_non_roster_spawn_proposes_invite_no_dispatch(maker, monkeypatch):
    """Router routes to a spawn that is NOT in the conversation roster → emit
    propose_invite + persist a pending `inviting` phase, and DO NOT dispatch."""
    from server.orchestrator import router
    from server.services import phase_service

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    events = []
    await arslan.handle_user_message("main", "audit my site", events.append)

    invite = next((e for e in events if e.get("type") == "propose_invite"), None)
    assert invite is not None, "expected a propose_invite frame"
    assert invite["spawn_id"] == 7
    # capability summary comes from the spawn's persona_role
    assert invite["reason"] == "audits sites for SEO issues"
    assert dispatched == [], "must NOT dispatch — the invite awaits user confirmation"

    pending = await phase_service.get_pending_invite("main")
    assert pending == {
        "spawn_id": 7, "task_brief": "audit keywords", "user_message": "audit my site",
        "needs_proposal": False,
    }


@pytest.mark.asyncio
async def test_route_to_non_roster_spawn_propose_mode_still_proposes_invite(maker, monkeypatch):
    """Regression (ordering bug): a route to a non-roster spawn whose task triggers
    the staged `needs_proposal` (propose-before-execute) branch must STILL emit
    propose_invite + NOT dispatch. The invite gates first contact regardless of the
    eventual dispatch mode; `needs_proposal` is parked for the accept handler."""
    from server.orchestrator import router
    from server.services import phase_service

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="route", spawn_id=7, task_brief="optimize linkedin", needs_proposal=True
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    events = []
    await arslan.handle_user_message("main", "帮我优化我的 LinkedIn", events.append)

    assert any(e.get("type") == "propose_invite" for e in events), "expected a propose_invite frame"
    # The propose-mode 'proposal' frame must NOT fire before acceptance.
    assert not any(e.get("type") == "proposal" for e in events), "no proposal frame before accept"
    assert dispatched == [], "must NOT dispatch in propose-mode before the invite is accepted"

    pending = await phase_service.get_pending_invite("main")
    assert pending == {
        "spawn_id": 7, "task_brief": "optimize linkedin",
        "user_message": "帮我优化我的 LinkedIn", "needs_proposal": True,
    }


@pytest.mark.asyncio
async def test_route_to_roster_member_dispatches_directly_no_invite(maker, monkeypatch):
    """Router routes to a spawn ALREADY in the roster → dispatch directly, no card."""
    from server.orchestrator import router
    from server.services import roster_service

    await roster_service.join("main", 7, via="invited")

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    events = []
    await arslan.handle_user_message("main", "audit my site", events.append)

    assert not any(e.get("type") == "propose_invite" for e in events), "no card for a roster member"
    assert len(dispatched) == 1, "a roster member dispatches directly"


@pytest.mark.asyncio
async def test_invite_capability_summary_falls_back_to_capability(maker, monkeypatch):
    """When a spawn has no persona_role, the invite summary falls back to its
    first capability."""
    from server.orchestrator import router
    from server.services import spawn_service

    # Drop persona_role so the fallback path is exercised.
    async with maker() as s:
        spawn = await s.get(Spawn, 7)
        spawn.persona_role = None
        await s.commit()

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="x")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan, "_dispatch_spawn", lambda *a, **k: _noop())

    events = []
    await arslan.handle_user_message("main", "audit my site", events.append)
    invite = next(e for e in events if e.get("type") == "propose_invite")
    assert invite["reason"] == "seo-audit"


async def _noop():
    return None
