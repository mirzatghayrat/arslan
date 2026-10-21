"""S3a: where a run's first change saves its folder, and where its end is recorded (card S3).

- write_file saves before it creates any folder, so folders the run made are known to be new.
- edit_file saves only once the edit is accepted: a refused edit changes nothing and saves nothing.
- run_command saves before the command runs.
- A file written under a left-out folder (node_modules, …) is saved on its own just before its first write.
- A save that fails never stops the change: the run goes on, without an undo for it.
- host_run records how the run left its folder when it ends: normally, cancelled or with an error.
"""
import asyncio
import hashlib

import pytest

from server import config
from server.registry import file_tools
from server.registry.executors import RunCommandExecutor
from server.services import checkpoints, execution_context, host_run, terminal_exec
from tests.server.test_file_tools import ws  # noqa: F401 — the workspace fixture


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    checkpoints._reset_for_tests()
    yield
    checkpoints._reset_for_tests()


async def test_write_file_saves_before_it_makes_folders(ws):  # noqa: F811
    with execution_context.bind_run(21):
        out = await file_tools.WriteFileExecutor().execute({"path": "deep/new/file.md", "content": "x"})
    assert out["ok"] is True
    clone = checkpoints.clone_of(21, ws)
    assert (clone / "notes.md").read_text() == "hello world\nsecond line\n" and not (clone / "deep").exists()
    await checkpoints.finish(21)
    left = checkpoints.manifest(21)["roots"][0]["finished"]
    assert left["deep/new/file.md"]["saved"] is None


async def test_a_refused_edit_saves_nothing_and_an_accepted_one_saves_first(ws):  # noqa: F811
    with execution_context.bind_run(22):
        refused = await file_tools.EditFileExecutor().execute({"path": "notes.md", "old_string": "absent",
                                                              "new_string": "x"})
    assert refused["ok"] is False and checkpoints.manifest(22) is None
    with execution_context.bind_run(22):
        out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "old_string": "second line",
                                                          "new_string": "SECOND"})
    assert out["ok"] is True
    assert (checkpoints.clone_of(22, ws) / "notes.md").read_text() == "hello world\nsecond line\n"


async def test_run_command_saves_before_the_command_runs(ws, monkeypatch):  # noqa: F811
    saved_first = []

    async def run(command, *, cwd, **kw):
        saved_first.append(checkpoints.manifest(23) is not None)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(cwd), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", run)
    with execution_context.bind_run(23):
        await RunCommandExecutor().execute({"command": "ls"})
    assert saved_first == [True]


async def test_a_file_written_under_a_left_out_folder_is_saved_on_its_own(ws):  # noqa: F811
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "lib.js").write_text("old")
    with execution_context.bind_run(24):
        edited = await file_tools.EditFileExecutor().execute({"path": "node_modules/lib.js", "old_string": "old",
                                                             "new_string": "new"})
        made = await file_tools.WriteFileExecutor().execute({"path": "node_modules/made.js", "content": "m"})
    assert edited["ok"] is True and made["ok"] is True
    clone = checkpoints.clone_of(24, ws)
    assert (clone / "node_modules" / "lib.js").read_text() == "old"
    assert not (clone / "node_modules" / "made.js").exists()
    await checkpoints.finish(24)
    left = checkpoints.manifest(24)["roots"][0]["finished"]
    assert left["node_modules/lib.js"]["saved"] == hashlib.sha256(b"old").hexdigest()
    assert left["node_modules/made.js"]["saved"] is None and left["node_modules/made.js"]["now"] is not None


async def test_a_later_write_in_the_same_run_never_saves_over_the_first_copy(ws):  # noqa: F811
    with execution_context.bind_run(26):
        await file_tools.WriteFileExecutor().execute({"path": "notes.md", "content": "one"})
        await file_tools.WriteFileExecutor().execute({"path": "notes.md", "content": "two"})
    assert (checkpoints.clone_of(26, ws) / "notes.md").read_text() == "hello world\nsecond line\n"
    [root] = checkpoints.manifest(26)["roots"]
    assert root["written"] == [] and root["failed"] == []     # only files in left-out folders are listed


async def test_a_save_that_fails_never_stops_the_write(ws, monkeypatch):  # noqa: F811
    def broken(*args):
        raise OSError("no space left")
    monkeypatch.setattr(checkpoints, "_ensure_sync", broken)
    with execution_context.bind_run(25):
        out = await file_tools.WriteFileExecutor().execute({"path": "a.md", "content": "x"})
    assert out["ok"] is True and (ws / "a.md").read_text() == "x"


@pytest.mark.parametrize("ending", ["done", "error", "cancel"])
async def test_the_run_records_its_end_however_it_ends(execution_db, monkeypatch, ending):
    finished = []

    async def finish(run_id):
        finished.append(run_id)
    monkeypatch.setattr(checkpoints, "finish", finish)

    async def body(emit):
        if ending == "error":
            raise RuntimeError("boom")
        if ending == "cancel":
            raise asyncio.CancelledError
        return "ok"
    try:
        await host_run.execute("conv-s3", "x", lambda e: None, body)
    except (RuntimeError, asyncio.CancelledError):
        pass
    assert len(finished) == 1 and isinstance(finished[0], int)
