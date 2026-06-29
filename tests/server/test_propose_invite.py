"""Task B5: propose_invite confirmation frame (no auto-join).

Arslan PROPOSES bringing an existing, not-yet-in-roster spawn into the
conversation rather than silently auto-joining. The frontend renders a
confirmation card; on confirm it sends the EXISTING `roster_invite` frame,
which joins exactly that one spawn. So this task only adds the proposal seam:
emit `propose_invite{spawn_id, reason}` and join NOTHING.
"""
import anyio
import pytest

from server.orchestrator import arslan
from server.ws import protocol


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
