"""WB1-3 (v0.1.64, card docs/plans/0164/WB1-workbench.md): `GET /conversations/{id}/changes`, what each turn
of a conversation changed in the user's folders, for Overview's Changes. Read only; built from the S3
checkpoint manifests, so it covers exactly the turns an undo can still take back."""
import json
from datetime import timedelta

import pytest

from server import config
from server.db.models import ArslanMessage, Run
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
    (work / "old.txt").write_text("old")
    (work / ".git").mkdir()
    (work / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


async def _seed(client, conversation_id="c1") -> int:
    async with client.db_maker() as db:
        run = Run(conversation_id=conversation_id, spawn_name="Arslan", user_message="x", status="done")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def _turn(client, ws, change, conversation_id="c1") -> int:
    run_id = await _seed(client, conversation_id)
    await checkpoints.ensure(run_id, [ws])
    change()
    await checkpoints.finish(run_id)
    return run_id


def _manifest_edit(run_id, **fields):
    path = checkpoints.root_dir() / str(run_id) / "manifest.json"
    data = json.loads(path.read_text())
    for key, value in fields.items():
        data[key] = value(data[key]) if callable(value) else value
    path.write_text(json.dumps(data))


async def _changes(client, conversation_id="c1"):
    return await client.get(f"/api/v1/conversations/{conversation_id}/changes")


async def test_each_turn_lists_its_paths_and_what_happened_to_them_newest_first(client, ws):
    def first():
        (ws / "notes.md").write_text("after")
        (ws / "new.txt").write_text("new")
        (ws / "old.txt").unlink()
        (ws / ".git" / "HEAD").write_text("ref: refs/heads/other\n")     # .git goes back whole: not listed
    a = await _turn(client, ws, first)
    b = await _turn(client, ws, lambda: (ws / "new.txt").write_text("newer!"))
    body = (await _changes(client)).json()
    assert [t["run_id"] for t in body["turns"]] == [b, a]
    assert body["turns"][1]["paths"] == [
        {"folder": str(ws), "path": "new.txt", "kind": "made"},
        {"folder": str(ws), "path": "notes.md", "kind": "edited"},
        {"folder": str(ws), "path": "old.txt", "kind": "deleted"}]
    assert body["turns"][0]["paths"] == [{"folder": str(ws), "path": "new.txt", "kind": "edited"}]
    assert body["turns"][0]["undone"] is False and body["turns"][0]["at"]


async def test_a_turn_that_changed_nothing_is_not_listed(client, ws):
    await _turn(client, ws, lambda: None)
    assert (await _changes(client)).json() == {"turns": []}


async def test_an_undone_turn_says_so(client, ws):
    run_id = await _turn(client, ws, lambda: (ws / "notes.md").write_text("after"))
    _manifest_edit(run_id, restored_at=1.0)
    [turn] = (await _changes(client)).json()["turns"]
    assert turn["undone"] is True


async def test_only_this_conversations_turns_and_404_for_one_never_seen(client, ws):
    mine = await _turn(client, ws, lambda: (ws / "notes.md").write_text("mine"))
    other = await _turn(client, ws, lambda: (ws / "notes.md").write_text("theirs"), conversation_id="c2")
    assert [t["run_id"] for t in (await _changes(client)).json()["turns"]] == [mine]
    assert [t["run_id"] for t in (await _changes(client, "c2")).json()["turns"]] == [other]
    missing = await _changes(client, "never-seen")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "conversation_not_found"


async def test_a_conversation_with_messages_but_no_runs_has_no_changes(client, ws):
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id="c3", role="user", content="hi"))
        await db.commit()
    assert (await _changes(client, "c3")).json() == {"turns": []}


async def test_expired_swept_and_older_copies_are_not_listed(client, ws, monkeypatch):
    monkeypatch.setattr(checkpoints, "_tidy", lambda newest: None)               # no sweep runs meanwhile
    expired = await _turn(client, ws, lambda: (ws / "notes.md").write_text("one"))
    age = checkpoints.KEEP_S + 60                                              # past its age; not swept yet
    _manifest_edit(expired, created_at=lambda t: t - age)
    async with client.db_maker() as db:                                        # the run as old as its copy
        run = await db.get(Run, expired)
        run.started_at -= timedelta(seconds=age)
        await db.commit()
    swept = await _turn(client, ws, lambda: (ws / "notes.md").write_text("two"))
    (checkpoints.root_dir() / str(swept) / "manifest.json").unlink()           # the quota sweep took it
    earlier = await _turn(client, ws, lambda: (ws / "notes.md").write_text("three"))
    _manifest_edit(earlier, created_at=lambda t: t - 3600)                     # a copy older than its run
    kept = await _turn(client, ws, lambda: (ws / "notes.md").write_text("four"))
    assert [t["run_id"] for t in (await _changes(client)).json()["turns"]] == [kept]
