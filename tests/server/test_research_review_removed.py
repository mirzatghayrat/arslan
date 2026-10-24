"""C8-2 (v0.1.63): research review is gone; the answer path never imports it.

The review ran after a saved report and only added a note, a stored review file and one extra
model request (C8 card). Its job became a working-method line in K5 ("cite only sources read
this turn; say plainly what you could not find").
"""
import importlib.util
import sys

import pytest

from server.orchestrator import tool_loop
from server.schemas import SettingsOut
from server.services import settings_service
from tests.server import test_agent_status_requests as status_requests
from tests.server import test_k3b_sent_is_final as k3b
from tests.server import test_trajectory_golden as golden


def test_the_module_and_its_setting_are_gone():
    assert importlib.util.find_spec("server.orchestrator.research_review") is None
    assert "research_review_enabled" not in SettingsOut.model_fields


class _WriteWithArtifact:
    """A saved report with a stored snapshot — exactly what the review used to fire on."""

    async def execute(self, args):
        return {"ok": True, "path": args["path"], "bytes": len(args["content"]),
                "artifact": {"run_id": 1, "filename": "run_1_notes.md", "sha256": "0" * 64}}


@pytest.mark.asyncio
async def test_a_saved_report_turn_never_imports_research_review(monkeypatch):
    """The real run_native save turn (two web reads, write_file notes.md with an artifact, the
    answer), with the review switched ON the way the old code read it. Before C8-2 this turn
    imported research_review; now nothing on the path can."""
    async def review_on(session):
        return True
    monkeypatch.setattr(settings_service, "research_review_enabled", review_on, raising=False)
    sys.modules.pop("server.orchestrator.research_review", None)

    adapter = k3b.Native(k3b._turn(), trims=False)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", golden._Extract())
    monkeypatch.setitem(executors.EXECUTORS, "write_file", _WriteWithArtifact())
    frames = []
    result = await tool_loop.run_native(system="SYS", user_content="research then save", history=[],
                                        emit=frames.append, on_chunk=lambda c: None,
                                        resolve_tools=status_requests._resolve)

    assert result["final"] == "Saved notes.md."
    assert "server.orchestrator.research_review" not in sys.modules
    assert not any(f.get("type") == "research_review" for f in frames)
