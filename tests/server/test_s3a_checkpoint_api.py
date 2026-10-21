"""S3a: how much the checkpoints keep, how long, and the two routes (card S3).

- **Quota:** what all checkpoints hold apart from the originals (a clone shares blocks until its
  original changes; a plain copy holds them all) stays under QUOTA_BYTES; the oldest go first.
- **Age:** a checkpoint older than KEEP_S goes, checked at most once an hour.
- A run still going is never removed, whatever its age or size.
- `GET /runs/{id}/checkpoint`: whether there is one, counts, what was not saved and why, overlapping
  runs, the later runs an undo would undo first, and when it expires. A copy older than its run
  (a database made anew) is not that run's.
- `POST /runs/{id}/checkpoint/restore {what: "files"}` puts files back; "conversation" and "both"
  arrive in S3b (409 `not_yet`); a refusal says why (409) and a missing checkpoint is a 404.
"""
import json
import types
from datetime import datetime, timedelta

import pytest

from server import config
from server.db.models import Run
from server.services import checkpoints


@pytest.fixture
def ws(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("before")
    (work / "node_modules").mkdir()
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


async def _run(run_id, ws, text):
    await checkpoints.ensure(run_id, [ws])
    (ws / "notes.md").write_text(text)
    await checkpoints.finish(run_id)


def _backdate(run_id, seconds):
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    data["created_at"] -= seconds
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("method", ["as on this machine", "plain copy"])
async def test_over_the_quota_the_oldest_go_first(ws, monkeypatch, method):
    if method == "plain copy":                                   # what Linux and non-APFS volumes do
        monkeypatch.setattr(checkpoints, "sys", types.SimpleNamespace(platform="linux"))
    await _run(1, ws, "first!")
    await _run(2, ws, "second")
    monkeypatch.setattr(checkpoints, "QUOTA_BYTES", 10)          # each holds ≥ 6 bytes of its own
    await _run(3, ws, "third!")
    assert checkpoints.manifest(1) is None and checkpoints.manifest(2) is None
    assert checkpoints.manifest(3) is not None


async def test_a_run_still_going_and_the_newest_are_never_removed(ws, monkeypatch):
    await checkpoints.ensure(4, [ws])                            # going on
    _backdate(4, checkpoints.KEEP_S + 60)
    monkeypatch.setattr(checkpoints, "QUOTA_BYTES", 0)
    await _run(5, ws, "five")
    assert checkpoints.manifest(4) is not None and checkpoints.manifest(5) is not None


async def test_old_ones_go_but_the_age_is_checked_at_most_hourly(ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "TIDY_EVERY_S", 0)
    await _run(6, ws, "six")
    _backdate(6, checkpoints.KEEP_S + 60)
    await _run(7, ws, "seven")                                   # checks the age: 6 goes
    assert checkpoints.manifest(6) is None
    monkeypatch.setattr(checkpoints, "TIDY_EVERY_S", 3600)
    _backdate(7, checkpoints.KEEP_S + 60)
    await _run(8, ws, "eight")                                   # checked a moment ago: not again yet
    assert checkpoints.manifest(7) is not None


async def _seed(client, **kw) -> int:
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Arslan", user_message="x", status="done", **kw)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def test_the_checkpoint_says_what_was_saved_and_what_was_not(client, ws):
    run_id = await _seed(client)
    await checkpoints.ensure(run_id, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "new.txt").write_text("new")
    await checkpoints.finish(run_id)
    body = (await client.get(f"/api/v1/runs/{run_id}/checkpoint")).json()
    assert body["exists"] is True and body["changed"] == 1 and body["created"] == 1
    assert body["excluded"] == ["node_modules"] and body["skipped"] == [] and body["later"] == []
    assert body["conversation"] is False and body["restored_at"] is None and body["running"] is False
    assert body["expires_at"] > datetime.utcnow().isoformat()


async def test_no_checkpoint_and_a_copy_older_than_its_run(client, ws):
    run_id = await _seed(client)
    assert (await client.get(f"/api/v1/runs/{run_id}/checkpoint")).json()["exists"] is False
    await checkpoints.ensure(run_id, [ws])
    await checkpoints.finish(run_id)
    _backdate(run_id, 3600)                                      # saved an hour before this run began
    assert (await client.get(f"/api/v1/runs/{run_id}/checkpoint")).json()["exists"] is False
    assert (await client.get("/api/v1/runs/99999/checkpoint")).status_code == 404


async def test_restore_files_and_what_is_not_there_yet(client, ws):
    run_id = await _seed(client)
    await _run(run_id, ws, "after")
    for what in ("conversation", "both"):
        resp = await client.post(f"/api/v1/runs/{run_id}/checkpoint/restore", json={"what": what})
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "not_yet"
    resp = await client.post(f"/api/v1/runs/{run_id}/checkpoint/restore", json={"what": "files"})
    assert resp.status_code == 200 and resp.json()["runs"][0]["restored"] == ["notes.md"]
    assert (ws / "notes.md").read_text() == "before"
    again = await client.post(f"/api/v1/runs/{run_id}/checkpoint/restore", json={"what": "files"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already"


async def test_a_restore_while_a_run_changes_the_folder_is_refused_with_the_runs(client, ws):
    first = await _seed(client)
    going = await _seed(client)
    await _run(first, ws, "after")
    await checkpoints.ensure(going, [ws])
    resp = await client.post(f"/api/v1/runs/{first}/checkpoint/restore", json={"what": "files"})
    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "running", "runs": [going]}
    none = await client.post(f"/api/v1/runs/{going + 100}/checkpoint/restore", json={"what": "files"})
    assert none.status_code == 404


async def test_the_copy_must_be_younger_than_the_run_for_a_restore_too(client, ws):
    run_id = await _seed(client, started_at=datetime.utcnow() + timedelta(hours=1))
    await _run(run_id, ws, "after")
    resp = await client.post(f"/api/v1/runs/{run_id}/checkpoint/restore", json={"what": "files"})
    assert resp.status_code == 404 and (ws / "notes.md").read_text() == "after"
