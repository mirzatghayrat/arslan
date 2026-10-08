"""0.1.55 decision 3: the island answers every card except a risky one.

Risky = it deletes, sends, pays, buys, transfers or submits (and anything this rule
does not know). Those show "Open in Arslan"; approving one from the island is refused
by the server, not only hidden by the page. Declining is always allowed.
Frames come from the real protocol builders, so a field rename breaks this test.
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.approvals import router
from server.services import approvals
from server.ws import protocol


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def cmd(text: str, **kw) -> dict:
    return protocol.propose_run_command("c1", text, [], **kw)


@pytest.mark.parametrize("frame, ok", [
    # Harmless or merely changing local things: the island may approve.
    (protocol.propose_workspace_write("w", "~/Arslan", "write", "notes.md"), True),
    (protocol.propose_schedule("s", "Morning brief", "cron: 0 9 * * *"), True),
    (protocol.propose_action("a", "browser_site", "example.com", ""), True),
    (protocol.propose_action("a", "desktop_look", "Notes", ""), True),
    (protocol.propose_action("a", "desktop_app", "Notes", ""), True),
    (protocol.propose_action("a", "mac_shortcut", "Morning", ""), True),
    (cmd("git status"), True),                                  # shown under "ask for everything"
    (cmd("ffmpeg -i a.mov b.mp4"), True),
    (cmd("brew list"), True),
    # Risky: delete, send, publish, reach elsewhere, install, control apps.
    (protocol.propose_action("a", "desktop_risky", "Mail · Send", "click Send"), False),
    (protocol.propose_action("a", "mac_script", "Finder", 'tell application "Finder" to delete file "a.txt"'), False),
    (protocol.propose_action("a", "mac_script", "Mail", 'tell application "Mail" to send theMessage'), False),
    (protocol.propose_action("a", "mac_script", "Finder", 'do shell script "ls"'), False),
    (cmd("rm notes.txt"), False),
    (cmd("ls && rm -r build"), False),                         # the second command decides
    (cmd("git push origin main"), False),
    (cmd("curl -X POST https://example.test/api"), False),
    (cmd("mail -s hi someone@example.test"), False),
    (cmd("osascript -e 'tell app \"Finder\" to get name'"), False),   # could send/delete; read it in Arslan
    (cmd("brew install wget"), False),
    (cmd("ls", remote_host="192.168.1.8"), False),
    (cmd("mv a.txt ~/Desktop/", sandbox="outside", why="move it"), False),
    ({"type": "propose_something_new", "call_id": "n"}, False),
])
def test_what_the_island_may_answer(frame, ok):
    assert approvals.island_may_answer(frame) is ok


def test_a_harmless_applescript_that_only_reads_is_answerable():
    # A false-positive guard: reading a name is not risky.
    frame = protocol.propose_action("a", "mac_script", "Notes", 'tell application "Notes" to get name of every note')
    assert approvals.island_may_answer(frame) is True


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-island-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-island-token"}) as client:
        yield client


async def test_a_risky_card_is_refused_from_the_island_but_declinable_and_approvable_in_arslan(api):
    risky = approvals.open_card("c", protocol.propose_run_command("r1", "rm old.txt", []), broadcast=False)
    safe = approvals.open_card("c", protocol.propose_schedule("s1", "Brief", "every: 3600"), broadcast=False)
    listed = {row["call_id"]: row for row in (await api.get("/api/v1/approvals/pending")).json()}
    assert listed["r1"]["island_ok"] is False and listed["s1"]["island_ok"] is True

    refused = await api.post("/api/v1/approvals/r1/answer", json={"approve": True, "source": "island"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "open_in_arslan"
    assert not risky.future.done()                                  # nothing was decided

    assert (await api.post("/api/v1/approvals/s1/answer", json={"approve": True, "source": "island"})).status_code == 200
    assert safe.future.result()["approved"] is True and safe.future.result()["by"] == "island"

    # Declining a risky card from the island is fine: saying no is always safe.
    assert (await api.post("/api/v1/approvals/r1/answer", json={"approve": False, "source": "island"})).status_code == 200
    assert risky.future.result()["approved"] is False


async def test_the_inbox_inside_arslan_may_approve_a_risky_card(api):
    risky = approvals.open_card("c", protocol.propose_run_command("r2", "rm old.txt", []), broadcast=False)
    assert (await api.post("/api/v1/approvals/r2/answer", json={"approve": True, "source": "inbox"})).status_code == 200
    assert risky.future.result() == {"approved": True, "remember": False, "by": "inbox"}
    await asyncio.sleep(0)


def test_a_running_job_tells_the_island_which_job_to_stop():
    from server.services import desktop_status
    desktop_status._reset_for_tests()
    with desktop_status.working("c", title="Collect postings", kind="job", job_id="job-42"):
        (activity,) = desktop_status.island_feed()["active"]
        assert activity["job_id"] == "job-42" and activity["kind"] == "job"
    with desktop_status.working("c"):
        assert desktop_status.island_feed()["active"][0]["job_id"] is None   # a turn has no job to stop
    desktop_status._reset_for_tests()


def test_the_job_runner_passes_its_id():
    # Source check on purpose: running a real job needs a model; the call site is one line.
    import inspect

    from server.services import background_jobs
    assert "job_id=job.job_id" in inspect.getsource(background_jobs)
