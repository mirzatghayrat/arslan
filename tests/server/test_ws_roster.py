"""Tests for T4: roster_update frame builder + roster_invite/roster_kick WS handlers + on-connect roster."""
import pytest

from server.db.models import Spawn
from server.ws import protocol
from tests.server.conftest import build_ws_client


# ---------------------------------------------------------------------------
# Unit test: roster_update frame builder
# ---------------------------------------------------------------------------

def test_roster_update_frame():
    f = protocol.roster_update([{"spawn_id": 4, "spawn_name": "x", "joined_via": "invited", "status": "idle"}])
    assert f["type"] == "roster_update"
    assert f["members"][0]["spawn_id"] == 4


def test_roster_update_frame_empty():
    f = protocol.roster_update([])
    assert f == {"type": "roster_update", "members": []}


# ---------------------------------------------------------------------------
# Fixture: mirrors staged_client from test_ws_staged.py exactly
# ---------------------------------------------------------------------------

@pytest.fixture
def staged_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            s.add(
                Spawn(
                    id=4,
                    name="领英智囊",
                    domain_category="social-media",
                    capabilities=["content-generation"],
                    system_prompt="You are a LinkedIn advisor.",
                )
            )
            await s.commit()

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="staged.db")


# ---------------------------------------------------------------------------
# Integration tests: on-connect roster, invite, kick, bad invite
# ---------------------------------------------------------------------------

def test_on_connect_sends_roster(staged_client):
    """On connect: after history frame, server sends roster_update with members==[]."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        history = ws.receive_json()
        assert history["type"] == "history"
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert roster["members"] == []


def test_roster_invite_adds_member(staged_client):
    """roster_invite with valid spawn_id → roster_event(joined) then roster_update with that member."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert len(frame["members"]) == 1
        assert frame["members"][0]["spawn_id"] == 4


def test_roster_kick_removes_member(staged_client):
    """roster_kick after invite → roster_event(left) then roster_update with members==[]."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        ws.receive_json()  # roster_update after invite
        ws.send_json({"type": "roster_kick", "spawn_id": 4})
        ws.receive_json()  # roster_event "left"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert frame["members"] == []


def test_roster_invite_bad_spawn_id_error(staged_client):
    """roster_invite with spawn_id=None → error INVALID_INPUT, socket stays open."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": None})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "INVALID_INPUT"
        # Socket still open — confirm by sending a valid invite
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert frame["members"][0]["spawn_id"] == 4


def test_roster_invite_emits_roster_event(staged_client):
    """roster_invite for a new spawn → roster_event(joined) then roster_update."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        event = ws.receive_json()
        assert event["type"] == "roster_event"
        assert event["action"] == "joined"
        assert event["spawn_id"] == 4
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert len(roster["members"]) == 1


def test_roster_invite_idempotent_no_second_event(staged_client):
    """Re-inviting a spawn already in the roster does NOT emit a second roster_event."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        # First invite — should get roster_event + roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        first_event = ws.receive_json()
        assert first_event["type"] == "roster_event"
        assert first_event["action"] == "joined"
        ws.receive_json()  # roster_update
        # Second invite (already a member) — should get ONLY roster_update, no roster_event
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        second = ws.receive_json()
        assert second["type"] == "roster_update", (
            "expected roster_update only on idempotent re-invite, got: " + second["type"]
        )


def test_roster_kick_emits_roster_event(staged_client):
    """roster_kick after invite → roster_event(left) then roster_update with empty members."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        ws.receive_json()  # roster_update
        ws.send_json({"type": "roster_kick", "spawn_id": 4})
        event = ws.receive_json()
        assert event["type"] == "roster_event"
        assert event["action"] == "left"
        assert event["spawn_id"] == 4
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert roster["members"] == []


# ---------------------------------------------------------------------------
# Inline invite Accept / Dismiss: roster_invite with a pending `inviting` phase
# dispatches the parked task; dismiss_invite clears it (no dispatch).
# ---------------------------------------------------------------------------

def test_roster_invite_with_pending_dispatches_parked_task(staged_client, monkeypatch):
    """Accept (execute-mode task): a pending `inviting` phase whose spawn_id matches the
    invite → the parked task is dispatched via the shared `dispatch_routed` path with
    needs_proposal=False, not just a bare join."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import phase_service

    dispatched = []

    async def _fake_dispatch_routed(conversation_id, spawn_id, task_brief, needs_proposal, emit, **kw):
        dispatched.append({"conversation_id": conversation_id, "spawn_id": spawn_id,
                           "task_brief": task_brief, "needs_proposal": needs_proposal,
                           "user_message": kw.get("user_message")})
        emit({"type": "stream_end", "message_id": 0})

    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake_dispatch_routed)

    # Park a pending invite for spawn 4 (execute-mode: needs_proposal not set).
    async def _park():
        await phase_service.set_inviting(
            "main", 4, task_brief="draft a post", user_message="help me on linkedin")
    staged_client.portal.call(_park)

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "stream_end":
                break

    assert len(dispatched) == 1
    assert dispatched[0]["spawn_id"] == 4
    assert dispatched[0]["task_brief"] == "draft a post"
    assert dispatched[0]["user_message"] == "help me on linkedin"
    assert dispatched[0]["needs_proposal"] is False
    # The inviting phase is cleared on accept.
    assert staged_client.portal.call(phase_service.get_pending_invite, "main") is None


def test_roster_invite_accept_propose_mode_dispatches_in_propose_mode(staged_client, monkeypatch):
    """Accept (propose-mode task): a parked invite carrying needs_proposal=True dispatches
    via `dispatch_routed` with needs_proposal=True, so the spawn responds in propose mode
    (proposing phase) exactly as a roster-member route would have."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import phase_service

    dispatched = []

    async def _fake_dispatch_routed(conversation_id, spawn_id, task_brief, needs_proposal, emit, **kw):
        dispatched.append({"spawn_id": spawn_id, "needs_proposal": needs_proposal})
        emit({"type": "stream_end", "message_id": 0})

    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake_dispatch_routed)

    async def _park():
        await phase_service.set_inviting(
            "main", 4, task_brief="optimize linkedin", user_message="帮我优化",
            needs_proposal=True)
    staged_client.portal.call(_park)

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "stream_end":
                break

    assert len(dispatched) == 1
    assert dispatched[0]["spawn_id"] == 4
    assert dispatched[0]["needs_proposal"] is True


def test_roster_invite_without_pending_just_joins(staged_client, monkeypatch):
    """A manual Ledger invite (no pending `inviting` phase) must NOT dispatch — only join."""
    from server.orchestrator import arslan as arslan_mod

    dispatched = []

    async def _fake_dispatch_routed(*args, **kw):  # pragma: no cover - asserts NOT called
        dispatched.append(args)

    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake_dispatch_routed)

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        event = ws.receive_json()
        assert event["type"] == "roster_event"
        assert event["action"] == "joined"
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert len(roster["members"]) == 1

    assert dispatched == [], "a manual invite must not dispatch"


def test_dismiss_invite_clears_pending(staged_client):
    """dismiss_invite clears a pending `inviting` phase so no dispatch happens."""
    from server.services import phase_service

    async def _park():
        await phase_service.set_inviting(
            "main", 4, task_brief="draft a post", user_message="help")
    staged_client.portal.call(_park)
    assert staged_client.portal.call(phase_service.get_pending_invite, "main") is not None

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "dismiss_invite"})
        # No frame is sent back for dismiss; confirm the socket is still alive
        # by following with a valid invite.
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        ws.receive_json()  # roster_update

    assert staged_client.portal.call(phase_service.get_pending_invite, "main") is None


# ---------------------------------------------------------------------------
# BUG2: Accept must never be silent — an invite/staffing-card accept whose park
# is gone (cleared / clobbered / parked for another spawn) joins AND explains
# via a joined_no_pending roster_event. Ledger invites (no origin) are untouched.
# ---------------------------------------------------------------------------

@pytest.fixture
def two_spawn_client(tmp_path, monkeypatch, portal):
    """staged_client plus a SECOND real spawn: roster_service.join does not validate
    spawn existence, so the park-mismatch case needs a real spawn 5 — a ghost id
    would make the test pass vacuously (spawn_name would just be null)."""
    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(id=4, name="领英智囊", domain_category="social-media",
                        capabilities=["content-generation"],
                        system_prompt="You are a LinkedIn advisor."))
            s.add(Spawn(id=5, name="数据研析", domain_category="analytics",
                        capabilities=["charting"], system_prompt="You chart."))
            await s.commit()

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="bug2.db")


def test_card_accept_without_park_joins_and_notices(two_spawn_client):
    """BUG2 death line: the card promised a consequence; with the park gone the
    accept must join AND explain — never silently just-join."""
    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4, "origin": "invite_card"})
        notice = ws.receive_json()
        assert notice["type"] == "roster_event"
        # The notice already says "joined" — the plain joined event is suppressed for
        # card accepts so the chat renders ONE line, not two stacked ones.
        assert notice["action"] == "joined_no_pending"
        assert notice["spawn_id"] == 4 and notice["spawn_name"] == "领英智囊"
        assert ws.receive_json()["type"] == "roster_update"


def test_ledger_accept_without_origin_unchanged(two_spawn_client):
    """No origin (Ledger pull / legacy client) → exact pre-fix frames, no notice."""
    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        assert ws.receive_json()["action"] == "joined"
        assert ws.receive_json()["type"] == "roster_update"  # and nothing in between


def test_card_accept_after_stale_clear_notices(two_spawn_client):
    """Stale: the park died via the Bug-B non-confirm clear (mechanism pinned in
    test_delegation_advance; arslan.py:477 is literally phase_service.clear) —
    reproduced via phase_service.clear. The card accept must explain."""
    from server.services import phase_service

    async def _park_then_clear():
        await phase_service.set_inviting("main", 4, task_brief="t", user_message="u")
        await phase_service.clear("main")
    two_spawn_client.portal.call(_park_then_clear)

    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "roster_invite", "spawn_id": 4, "origin": "invite_card"})
        assert ws.receive_json()["action"] == "joined_no_pending"


def test_card_accept_for_other_spawn_keeps_park_and_notices(two_spawn_client, monkeypatch):
    """park for spawn 4; a (stale) card accept of spawn 5 must not dispatch, must
    not clear 4's park, and must explain."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import phase_service

    dispatched = []

    async def _fake(*a, **k):  # pragma: no cover - asserts NOT called
        dispatched.append(a)
    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake)

    async def _park():
        await phase_service.set_inviting("main", 4, task_brief="t", user_message="u")
    two_spawn_client.portal.call(_park)

    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "roster_invite", "spawn_id": 5, "origin": "invite_card"})
        notice = ws.receive_json()
        assert notice["action"] == "joined_no_pending"
        assert notice["spawn_name"] == "数据研析"
        assert ws.receive_json()["type"] == "roster_update"

    assert dispatched == []
    pending = two_spawn_client.portal.call(phase_service.get_pending_invite, "main")
    assert pending is not None and pending["spawn_id"] == 4


def test_card_accept_already_member_still_notices(two_spawn_client):
    """Already a member → no joined event (idempotence pinned elsewhere), but the
    honest notice must STILL fire — it explains the missing dispatch, not membership."""
    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # joined
        ws.receive_json()  # roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4, "origin": "invite_card"})
        notice = ws.receive_json()
        assert notice["type"] == "roster_event"
        assert notice["action"] == "joined_no_pending"
        assert ws.receive_json()["type"] == "roster_update"


def test_card_accept_with_matching_park_dispatches_and_never_notices(two_spawn_client, monkeypatch):
    """Production frame shape (origin present) on the park-HIT path: the parked task
    dispatches and the honest no-pending notice must NOT fire — it would contradict
    the dispatch that just happened."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import phase_service

    dispatched, frames = [], []

    async def _fake_dispatch_routed(conversation_id, spawn_id, task_brief, needs_proposal, emit, **kw):
        dispatched.append(spawn_id)
        emit({"type": "stream_end", "message_id": 0})
    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake_dispatch_routed)

    async def _park():
        await phase_service.set_inviting("main", 4, task_brief="t", user_message="u")
    two_spawn_client.portal.call(_park)

    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4, "origin": "invite_card"})
        for _ in range(10):
            f = ws.receive_json()
            frames.append(f)
            if f.get("type") == "stream_end":
                break

    assert dispatched == [4]
    assert not any(f.get("action") == "joined_no_pending" for f in frames), (
        "a card accept that HIT its park must never also claim nothing was queued")


def test_card_accept_with_answered_park_recruits_and_never_notices(two_spawn_client, monkeypatch):
    """Same for the cell-6 recruiting park (answered=True): enroll-only + the
    'recruited' note, never the no-pending notice."""
    from server.orchestrator import arslan as arslan_mod
    from server.services import phase_service

    dispatched, frames = [], []

    async def _fake(*a, **k):  # pragma: no cover - asserts NOT called
        dispatched.append(a)
    monkeypatch.setattr(arslan_mod, "dispatch_routed", _fake)

    async def _park():
        await phase_service.set_inviting("main", 4, task_brief="t", user_message="u",
                                         answered=True)
    two_spawn_client.portal.call(_park)

    with two_spawn_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "roster_invite", "spawn_id": 4, "origin": "invite_card"})
        for _ in range(6):
            frames.append(ws.receive_json())
            if frames[-1].get("type") == "roster_update":
                break

    assert dispatched == []
    assert any(f.get("action") == "recruited" for f in frames), "recruit note expected"
    assert not any(f.get("action") == "joined_no_pending" for f in frames)
