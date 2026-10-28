"""S3b: the routes for undoing a turn's conversation, with or without its files (card S3).

- `GET /runs/{id}/checkpoint` says whether the conversation can be undone (`conversation`, or `reason`),
  how many messages and later turns go and how many facts, also for a turn that changed no file.
- `POST …/restore {what: "conversation"}` takes it back; "both" checks the files, then the conversation,
  and changes nothing when either refuses; then puts the files back and takes the conversation back.
- Settings say when the working folder is on another volume (its changes can't be undone).
"""
import pytest
from sqlalchemy import select

from server import config
from server.db.models import ArslanMessage, ArslanSummary, Run
from server.orchestrator import memory
from server.services import checkpoints

CID = "s3b-api"


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    # What a save holds is tested here, not free space. CI's /tmp is a small tmpfs that
    # fills as the suite runs; below MIN_FREE every save in this file would be skipped as
    # low_disk. The low-disk case has its own test in test_s3a_checkpoint_save.py.
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


async def _turn(client, text, *, reply=True) -> int:
    await memory.add_message(CID, "user", text)
    async with client.db_maker() as db:
        run = Run(conversation_id=CID, spawn_name="Arslan", user_message=text, status="done")
        db.add(run)
        await db.flush()
        if reply:
            db.add(ArslanMessage(conversation_id=CID, role="arslan", content="reply to " + text, run_id=run.id))
        await db.commit()
        return run.id


async def _changed_files(run_id, ws):
    await checkpoints.ensure(run_id, [ws])
    (ws / "notes.md").write_text("after")
    await checkpoints.finish(run_id)


async def _ids(client) -> list[int]:
    async with client.db_maker() as db:
        return [m.id for m in (await db.execute(
            select(ArslanMessage).where(ArslanMessage.conversation_id == CID))).scalars()]


async def _left(client) -> list[str]:
    async with client.db_maker() as db:
        return [m.content for m in (await db.execute(
            select(ArslanMessage).where(ArslanMessage.conversation_id == CID).order_by(ArslanMessage.id))).scalars()]


async def _restore(client, run_id, what, last=None):
    """As the sheet does: the conversation is taken back only up to the newest message the box showed."""
    if what != "files" and last is None:
        last = (await client.get(f"/api/v1/runs/{run_id}/checkpoint")).json().get("last_message_id") or 0
    return await client.post(f"/api/v1/runs/{run_id}/checkpoint/restore",
                             json={"what": what, **({"last_message_id": last} if what != "files" else {})})


async def test_the_checkpoint_says_whether_the_conversation_can_be_undone(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _turn(client, "three")
    body = (await client.get(f"/api/v1/runs/{second}/checkpoint")).json()
    assert body["exists"] is False                               # it changed no file
    assert (body["conversation"], body["reason"], body["messages_after"], body["later_turns"], body["facts"]) == (
        True, None, 4, 1, 0)
    assert body["last_message_id"] == max((await _ids(client)))
    card = await _turn(client, "a choice card", reply=False)
    assert (await client.get(f"/api/v1/runs/{card}/checkpoint")).json() == {
        "exists": False, "conversation": False, "reason": "none"}


async def test_undo_the_conversation_then_a_second_time_is_refused(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    resp = await _restore(client, second, "conversation")
    assert resp.status_code == 200 and resp.json()["conversation"]["messages"] == 2
    history = resp.json()["conversation"]["history"]                 # the window shows it at once
    assert [(m["role"], m["content"]) for m in history] == [("user", "one"), ("arslan", "reply to one")]
    assert await _left(client) == ["one", "reply to one"]
    again = await _restore(client, second, "conversation")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already"
    card = await _turn(client, "a choice card", reply=False)
    assert (await _restore(client, card, "conversation")).status_code == 404


async def test_both_puts_the_files_back_and_takes_the_conversation_back(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)
    resp = await _restore(client, second, "both")
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"]["runs"][0]["restored"] == ["notes.md"] and body["conversation"]["messages"] == 2
    assert [m["content"] for m in body["conversation"]["history"]] == ["one", "reply to one"]
    assert (ws / "notes.md").read_text() == "before" and await _left(client) == ["one", "reply to one"]


async def test_both_changes_nothing_when_the_conversation_refuses(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)
    async with client.db_maker() as db:
        db.add(ArslanSummary(conversation_id=CID, summary="s", up_to_message_id=10_000))
        await db.commit()
    resp = await _restore(client, second, "both")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "summarised"
    assert (ws / "notes.md").read_text() == "after" and len(await _left(client)) == 4


async def test_both_changes_nothing_when_the_files_refuse(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    going = await _turn(client, "three")
    await _changed_files(second, ws)
    await checkpoints.ensure(going, [ws])                        # a run still changing the folder
    resp = await _restore(client, second, "both")
    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "running", "runs": [going]}
    assert (ws / "notes.md").read_text() == "after" and len(await _left(client)) == 6
    async with client.db_maker() as db:                          # both refuse: the files' reason is given
        db.add(ArslanSummary(conversation_id=CID, summary="s", up_to_message_id=10_000))
        await db.commit()
    resp = await _restore(client, second, "both")
    assert resp.json()["detail"] == {"code": "running", "runs": [going]}


async def test_both_keeps_the_conversation_when_putting_the_files_back_fails_after_the_checks(client, ws, monkeypatch):
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)

    async def refused(run_id):
        raise checkpoints.Refused("running", [999])
    monkeypatch.setattr(checkpoints, "restore_files", refused)
    resp = await _restore(client, second, "both")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "running"
    assert len(await _left(client)) == 4


async def test_both_without_saved_files_is_a_404_and_changes_nothing(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    resp = await _restore(client, second, "both")
    assert resp.status_code == 404 and len(await _left(client)) == 4


async def test_settings_say_when_the_working_folder_is_on_another_volume(client, tmp_path, monkeypatch):
    assert (await client.get("/api/v1/settings")).json()["workspace_other_volume"] is False
    monkeypatch.setattr(checkpoints, "_same_volume", lambda a, b: False)
    assert (await client.get("/api/v1/settings")).json()["workspace_other_volume"] is True


# ── ⓪Plan's review of #329 ───────────────────────────────────────────────────────────────────────────

async def test_taking_a_conversation_back_needs_the_range_the_box_showed(client, ws):
    await _turn(client, "one")
    second = await _turn(client, "two")
    resp = await client.post(f"/api/v1/runs/{second}/checkpoint/restore", json={"what": "conversation"})
    assert resp.status_code == 422 and len(await _left(client)) == 4


async def test_a_turn_that_arrived_after_the_box_opened_is_refused(client, ws):
    """🟠1 at the routes: the box showed two messages; one more turn arrived before the click."""
    await _turn(client, "one")
    second = await _turn(client, "two")
    shown = (await client.get(f"/api/v1/runs/{second}/checkpoint")).json()["last_message_id"]
    await _turn(client, "sent from the phone meanwhile")
    resp = await _restore(client, second, "conversation", last=shown)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "changed" and len(await _left(client)) == 6


async def test_both_keeps_the_conversation_when_a_file_could_not_be_put_back(client, ws, monkeypatch):
    """🟠4 (the reviewer's API probe): a file that stayed changed keeps the turn, so the files can be retried."""
    (ws / "plan.md").write_text("before")
    await _turn(client, "one")
    second = await _turn(client, "two")
    await checkpoints.ensure(second, [ws])
    (ws / "notes.md").write_text("after")
    (ws / "plan.md").write_text("after")
    await checkpoints.finish(second)
    real = checkpoints._put_back

    def flaky(root, rel, src, saved):
        if rel == "plan.md":
            raise OSError("disk said no")
        return real(root, rel, src, saved)
    monkeypatch.setattr(checkpoints, "_put_back", flaky)
    resp = await _restore(client, second, "both")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "files_failed"
    assert resp.json()["detail"]["files"]["runs"][0]["failed"] == ["plan.md"]
    assert len(await _left(client)) == 4
    monkeypatch.setattr(checkpoints, "_put_back", real)
    retry = await _restore(client, second, "files")
    assert retry.status_code == 200 and "plan.md" in retry.json()["runs"][0]["restored"]


async def test_a_conversation_that_fails_after_the_files_went_back_is_reported_with_them(client, ws, monkeypatch):
    """🟡13: the files went back, then a turn arrived (a scheduled fire takes no turn lock): reported as such."""
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)
    real = checkpoints.restore_files

    async def then_a_fire(run_id):
        out = await real(run_id)
        await _turn(client, "a scheduled fire meanwhile")
        return out
    monkeypatch.setattr(checkpoints, "restore_files", then_a_fire)
    resp = await _restore(client, second, "both")
    detail = resp.json()["detail"]
    assert resp.status_code == 409 and detail["code"] == "conversation_failed" and detail["reason"] == "changed"
    assert detail["files"]["runs"][0]["restored"] == ["notes.md"] and len(await _left(client)) == 6


async def test_reading_settings_never_creates_the_workspace(client, tmp_path, monkeypatch):
    """🟡10: Settings used to recreate a deleted ~/Arslan just by being opened."""
    gone = tmp_path / "Arslan-deleted"
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(gone))
    assert (await client.get("/api/v1/settings")).json()["workspace_other_volume"] is False
    assert not gone.exists()


async def test_a_run_that_starts_while_the_files_go_back_stops_the_conversation(client, ws, monkeypatch):
    """🟠1: the busy checks run again after the files (a scheduled fire takes no turn lock)."""
    from server.services import run_registry
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)
    real = checkpoints.restore_files

    async def then_a_run(run_id):
        out = await real(run_id)
        monkeypatch.setattr(run_registry, "active_for", lambda cid: [999] if cid == CID else [])
        return out
    monkeypatch.setattr(checkpoints, "restore_files", then_a_run)
    resp = await _restore(client, second, "both")
    detail = resp.json()["detail"]
    assert resp.status_code == 409 and (detail["code"], detail["reason"]) == ("conversation_failed", "running")
    assert len(await _left(client)) == 4


async def test_a_failure_taking_the_conversation_back_is_reported_with_the_files(client, ws, monkeypatch):
    from server.services.memory_repository import MemoryRepository
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)

    async def broken(self, *args):
        raise RuntimeError("database went away")
    monkeypatch.setattr(MemoryRepository, "forget_turns", broken)
    resp = await _restore(client, second, "both")
    detail = resp.json()["detail"]
    assert resp.status_code == 409 and (detail["code"], detail["reason"]) == ("conversation_failed", "error")
    assert detail["files"]["runs"][0]["restored"] == ["notes.md"] and len(await _left(client)) == 4


async def test_a_git_folder_that_could_not_go_back_keeps_the_conversation_too(client, ws, monkeypatch):
    await _turn(client, "one")
    second = await _turn(client, "two")
    await _changed_files(second, ws)

    async def git_failed(run_id):
        return {"run_id": run_id, "later": [], "runs": [{"run_id": run_id, "restored": ["notes.md"], "trashed": [],
                "user_changed": [], "failed": [], "not_saved": [], "git": "failed"}]}
    monkeypatch.setattr(checkpoints, "restore_files", git_failed)
    resp = await _restore(client, second, "both")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "files_failed" and len(await _left(client)) == 4
