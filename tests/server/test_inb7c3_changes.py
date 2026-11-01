"""INB7-c3 (v0.1.64): what the picked run changed, for the inspector's 「改动」. GET /runs/{id}/changes reads only that run's
checkpoint manifest (⓪Plan's review of PR 629: no conversation-wide scan) and says which state it is in: running, finishing,
kept, none (nothing to list), expired (the copy is gone) or not_saved (the folder could not be saved)."""
from __future__ import annotations

import json

import pytest

from server import config
from server.db.models import Run, RunStep
from server.services import checkpoints


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    monkeypatch.setattr(checkpoints, "_free_bytes", lambda path: 2 * checkpoints.MIN_FREE)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("before")
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


async def _run(client, status="recorded", conversation_id="chat-7", wrote=False) -> int:
    async with client.db_maker() as db:
        run = Run(conversation_id=conversation_id, spawn_name="Arslan", user_message="x", status=status, kind="host", task_tokens=0)
        db.add(run)
        await db.flush()
        if wrote:
            db.add(RunStep(run_id=run.id, seq=0, kind="tool_call", ref={"tool": "write_file", "ok": True}, detail={}))
        await db.commit()
        return run.id


async def _changes(client, run_id):
    return (await client.get(f"/api/v1/runs/{run_id}/changes")).json()


def _manifest_edit(run_id, **fields):
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    data.update(fields)
    path.write_text(json.dumps(data))


async def test_the_steps_read_names_the_runs_conversation(client):
    run_id = await _run(client)
    assert (await client.get(f"/api/v1/runs/{run_id}/process")).json()["conversation_id"] == "chat-7"


async def test_a_kept_run_lists_its_paths_and_whether_it_was_undone(client, ws):
    run_id = await _run(client)
    await checkpoints.ensure(run_id, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "plan.md").write_text("new")
    await checkpoints.finish(run_id)
    body = await _changes(client, run_id)
    assert (body["state"], body["undone"], body["conversation_id"]) == ("kept", False, "chat-7")
    assert sorted((p["path"], p["kind"]) for p in body["paths"]) == [("notes.md", "edited"), ("plan.md", "made")]
    _manifest_edit(run_id, restored_at="2026-11-01T10:00:00")
    assert (await _changes(client, run_id))["undone"] is True


async def test_a_running_run_and_one_still_being_saved(client, ws):
    running = await _run(client, status="recording")
    assert (await _changes(client, running))["state"] == "running"
    ended = await _run(client)
    await checkpoints.ensure(ended, [ws])                       # ended, but finish has not recorded how it left the folder
    (ws / "notes.md").write_text("after")
    assert (await _changes(client, ended))["state"] == "finishing"


async def test_none_when_the_run_changed_nothing(client, ws):
    quiet = await _run(client)                                   # never wrote: no checkpoint was ever made
    assert await _changes(client, quiet) == {"state": "none", "undone": False, "paths": [], "conversation_id": "chat-7"}
    looked = await _run(client)
    await checkpoints.ensure(looked, [ws])                       # saved the folder, then changed nothing
    await checkpoints.finish(looked)
    assert (await _changes(client, looked))["state"] == "none"


async def test_expired_when_a_run_that_wrote_has_no_copy_left(client, ws):
    gone = await _run(client, wrote=True)                        # KEEP_S or the quota removed its copy
    assert (await _changes(client, gone))["state"] == "expired"
    earlier = await _run(client, wrote=True)
    await checkpoints.ensure(earlier, [ws])
    await checkpoints.finish(earlier)
    _manifest_edit(earlier, created_at=0)                        # an earlier run's copy under the same id is not this run's
    assert (await _changes(client, earlier))["state"] == "expired"


async def test_not_saved_when_no_folder_could_be_saved(client, ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "_same_volume", lambda a, b: False)
    run_id = await _run(client)
    await checkpoints.ensure(run_id, [ws])
    await checkpoints.finish(run_id)
    assert (await _changes(client, run_id))["state"] == "not_saved"


async def test_an_unknown_run_is_404(client):
    assert (await client.get("/api/v1/runs/999999/changes")).status_code == 404
