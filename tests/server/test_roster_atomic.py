"""Reproduce-first per spec 2.4 (修「邀请连坐」 — invite cascade).

The reported symptom: "pulling one spawn into a conversation causes 3-4 to join."
These tests seed MULTIPLE spawns (so a cascade could manifest) and then invite
exactly ONE, asserting the resulting roster contains exactly that one spawn with
no duplicates — covering both the WS `roster_invite` path and the direct
`roster_service` path.

FINDING: With 4 spawns seeded, inviting one joins exactly one and list_roster has
no duplicate rows. The '邀请连坐' cascade does NOT reproduce in the current backend.
All three join paths (dispatch/create/invite) call the idempotent, single-spawn
`roster_service.join`, and `list_roster` returns one row per (conversation, spawn).
The reported symptom was likely a frontend display issue or fixed in a prior
roster change. These tests stand as permanent regression guards.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from tests.server.conftest import build_ws_client


# ---------------------------------------------------------------------------
# WS fixture: mirrors staged_client from test_ws_roster.py, but seeds 4 spawns
# so a cascade (one invite → multiple joins) could manifest if the bug existed.
# ---------------------------------------------------------------------------

_SEED_SPAWNS = [
    (4, "领英智囊", "social-media"),
    (5, "数据分析师", "analytics"),
    (6, "文案写手", "content"),
    (7, "调研专员", "research"),
]


@pytest.fixture
def staged_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            for sid, name, cat in _SEED_SPAWNS:
                s.add(
                    Spawn(
                        id=sid,
                        name=name,
                        domain_category=cat,
                        capabilities=["content-generation"],
                        system_prompt=f"You are {name}.",
                    )
                )
            await s.commit()

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="staged.db")


# ---------------------------------------------------------------------------
# (A) WS path: invite ONE with several spawns present → roster has exactly [X].
# ---------------------------------------------------------------------------

def test_invite_one_joins_exactly_one(staged_client):
    """With 4 spawns in the system, inviting ONE yields a roster_update containing
    exactly that one spawn — no cascade, no duplicates."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 5})
        ev = ws.receive_json()
        assert ev["type"] == "roster_event"
        assert ev["action"] == "joined"
        assert ev["spawn_id"] == 5
        upd = ws.receive_json()
        assert upd["type"] == "roster_update"
        ids = [m["spawn_id"] for m in upd["members"]]
        assert ids == [5], f"expected exactly [5], got {ids} (cascade?)"
        assert len(ids) == len(set(ids)), f"duplicate members: {ids}"


def test_invite_two_sequential_no_cascade(staged_client):
    """Inviting two spawns one after another adds exactly those two, in join order,
    with no extra members and no duplicates."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)

        ws.send_json({"type": "roster_invite", "spawn_id": 6})
        ws.receive_json()  # roster_event joined
        upd1 = ws.receive_json()
        assert [m["spawn_id"] for m in upd1["members"]] == [6]

        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event joined
        upd2 = ws.receive_json()
        ids = [m["spawn_id"] for m in upd2["members"]]
        assert ids == [6, 4], f"expected join-order [6, 4], got {ids}"
        assert len(ids) == len(set(ids))


def test_reinvite_same_spawn_no_duplicate(staged_client):
    """Re-inviting an already-present spawn (with other spawns available) does NOT
    duplicate it and does NOT pull anyone else in."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)

        ws.send_json({"type": "roster_invite", "spawn_id": 7})
        ws.receive_json()  # roster_event joined
        ws.receive_json()  # roster_update

        # Re-invite same spawn → idempotent: only a roster_update, no new event.
        ws.send_json({"type": "roster_invite", "spawn_id": 7})
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        ids = [m["spawn_id"] for m in frame["members"]]
        assert ids == [7], f"expected [7] after idempotent re-invite, got {ids}"
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# (B) Direct roster_service path: join + list_roster atomicity.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            for sid, name, cat in _SEED_SPAWNS:
                s.add(Spawn(id=sid, name=name, domain_category=cat, capabilities=[], system_prompt="x"))
            await s.commit()

    await _seed()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_join_one_of_many_lists_exactly_one(maker):
    """With 4 spawns present, joining ONE leaves the roster with exactly that one."""
    from server.services import roster_service

    assert await roster_service.join("conv", 5, via="invited") is True
    members = await roster_service.list_roster("conv")
    ids = [m["spawn_id"] for m in members]
    assert ids == [5], f"expected [5], got {ids}"
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_second_join_returns_false_and_no_dup(maker):
    """A second join of the same spawn returns False and the roster stays length 1
    (no duplicate row), regardless of how many other spawns exist."""
    from server.services import roster_service

    assert await roster_service.join("conv", 6, via="routed") is True
    assert await roster_service.join("conv", 6, via="invited") is False
    members = await roster_service.list_roster("conv")
    ids = [m["spawn_id"] for m in members]
    assert ids == [6], f"expected [6] with no duplicate, got {ids}"
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_multiple_joins_distinct_no_dups(maker):
    """Joining several distinct spawns yields exactly those, in joined_at order, with
    no duplicate rows even after re-joining each."""
    from server.services import roster_service

    for sid in (4, 5, 6, 7):
        assert await roster_service.join("conv", sid, via="routed") is True
    # Re-join everyone — all idempotent False, no new rows.
    for sid in (4, 5, 6, 7):
        assert await roster_service.join("conv", sid, via="invited") is False
    members = await roster_service.list_roster("conv")
    ids = [m["spawn_id"] for m in members]
    assert ids == [4, 5, 6, 7], f"expected join-order [4,5,6,7], got {ids}"
    assert len(ids) == len(set(ids))
