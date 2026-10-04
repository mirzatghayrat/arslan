"""status.snapshot for the phone's home screen (mobile-bridge-protocol §5.3): the island's
state as the mascot, the jobs still running, the cards waiting."""
import re
from pathlib import Path

import pytest

import server.api.phone as phone
from server.services import background_jobs, desktop_status
from server.services.background_jobs import Job

NOW = 1_790_000_000.0


@pytest.fixture(autouse=True)
def _clean():
    desktop_status._reset_for_tests()
    background_jobs._jobs.clear()
    yield
    desktop_status._reset_for_tests()
    background_jobs._jobs.clear()


def _active(tool, started=0):
    return {"started_at": started, "step": {"tool": tool} if tool else None}


def _event(kind, outcome=None, age=5):
    return {"kind": kind, "outcome": outcome, "at": NOW - age}


@pytest.mark.parametrize("feed, mascot", [
    ({"awaiting": 1, "active": [_active("web_search")]}, "approval"),
    ({"awaiting": 0, "active": [_active("web_search")]}, "searching"),
    ({"awaiting": 0, "active": [_active("browser_click")]}, "searching"),
    ({"awaiting": 0, "active": [_active("write_file")]}, "working"),
    ({"awaiting": 0, "active": [_active(None)]}, "working"),
    ({"awaiting": 0, "active": [_active("recall", started=1), _active("run_command", started=2)]}, "working"),
    ({"awaiting": 0, "active": [_active("run_command", started=1), _active("web_extract", started=2)]}, "searching"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "ok")]}, "done"),
    ({"awaiting": 0, "active": [], "events": [_event("scheduled_finished", "error")]}, "stopped"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "needs_review")]}, "stopped"),
    ({"awaiting": 0, "active": [], "events": [_event("scheduled_paused")]}, "stopped"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "cancelled")]}, "idle"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "ok", age=61)]}, "idle"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "error"), _event("approval_needed"),
                                              _event("lesson_learned", age=1)]}, "stopped"),
    ({"awaiting": 0, "active": [], "events": [_event("turn_finished", "ok", age=30),
                                              _event("turn_finished", "error", age=10)]}, "stopped"),
    ({"awaiting": 0, "active": [], "events": []}, "idle"),
])
def test_the_mascot_follows_the_island(feed, mascot):
    assert phone.phone_mascot(feed, NOW) == mascot


def test_the_search_tools_are_the_islands():
    source = (Path(__file__).resolve().parents[2] / "web/src/island/islandMachine.ts").read_text()
    names = re.search(r"const SEARCH_TOOLS = new Set\(\[([^\]]*)\]\)", source).group(1)
    assert set(re.findall(r"'([^']+)'", names)) == phone.SEARCH_TOOLS
    assert "tool.startsWith('browser_')" in source


async def test_the_snapshot_has_the_running_jobs_and_the_waiting_cards(client):
    criteria = [{"id": "c1", "description": "Files sorted"}, {"id": "answer-delivered", "description": "x"}]
    running = Job("j1", "trip", "Tidy downloads", criteria, phase="running", step="Sorting", started_at=2)
    queued = Job("j0", "trip", "Plan", [], started_at=1)
    finished = Job("j2", "trip", "Old", [], phase="finished", outcome="done")
    background_jobs._jobs.update({"j1": running, "j0": queued, "j2": finished})
    with desktop_status.working("trip", title="Tidy downloads", kind="job"):
        desktop_status.note_step("web_search", {"query": "x"})
        with desktop_status.awaiting_approval("trip"):
            got = (await client.get("/api/v1/phone/status")).json()
        after = (await client.get("/api/v1/phone/status")).json()
    assert got["presence"] == "online" and got["high_risk_mac_only"] is False
    assert (got["mascot"], got["waiting_approvals"]) == ("approval", 1)
    assert (after["mascot"], after["waiting_approvals"]) == ("searching", 0)
    assert [j["job_id"] for j in got["jobs"]] == ["j0", "j1"], "unfinished only, oldest first"
    assert got["jobs"][1] == running.frame()
    assert set(got) == {"presence", "mascot", "jobs", "waiting_approvals", "high_risk_mac_only", "activity"}, \
        "device_name and last_seen are the Bridge's to add"
    assert len(got["activity"]["hours"]) == 24 and got["activity"]["waiting"] == 1
