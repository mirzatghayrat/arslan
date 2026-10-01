"""Tests for T6 gate-side additions: proposal frame builder + confirm_direction handler."""
import pytest

from server.db.models import Spawn
from server.ws import protocol
from tests.server.conftest import build_ws_client


# ---------------------------------------------------------------------------
# Unit test: proposal frame builder
# ---------------------------------------------------------------------------

def test_proposal_frame():
    f = protocol.proposal(4, "领英智囊")
    assert f == {"type": "proposal", "spawn_id": 4, "spawn_name": "领英智囊"}


def test_proposal_frame_none_name():
    f = protocol.proposal(99, None)
    assert f == {"type": "proposal", "spawn_id": 99, "spawn_name": None}


# ---------------------------------------------------------------------------
# Integration test: confirm_direction WS handler
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




