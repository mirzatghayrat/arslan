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















# ---------------------------------------------------------------------------
# Inline invite Accept / Dismiss: roster_invite with a pending `inviting` phase
# dispatches the parked task; dismiss_invite clears it (no dispatch).
# ---------------------------------------------------------------------------









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














