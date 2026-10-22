"""S1b (U14 b): a run with nobody to ask runs its commands in Arslan's own folder (card S1, ⓪Plan Q7).

A scheduled run binds no card surface. Since #308 its commands always run inside the sandbox (outside it
needs an OK nobody can give), and the sandbox lets a command write in its working folder, temporary and
cache folders. Before S1b that working folder was the one the user chose, so a scheduled run could
change the user's own files with no one watching. Now, with nobody to ask, it is ~/Arslan, whatever the
user chose; a turn with someone to ask keeps the user's folder.
"""
import pytest

from server.db import session as db_session
from server.db.models import Setting
from server.registry.executors import RunCommandExecutor
from server.services import permissions, terminal_exec


@pytest.fixture
def folders(execution_db, tmp_path, monkeypatch):
    own = tmp_path / "Arslan"
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(own))
    ran = []

    async def run(command, *, cwd, sandbox=False, **kw):
        ran.append((str(cwd), sandbox))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(cwd), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", run)
    return own, chosen, ran


async def _choose(folder):
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="workspace_dir", value=str(folder)))
        await db.commit()


async def _ask(frame):
    raise AssertionError("no card in this test")


async def test_with_nobody_to_ask_commands_run_in_arslans_own_folder(folders):
    own, chosen, ran = folders
    await _choose(chosen)
    out = await RunCommandExecutor().execute({"command": "ls"})
    assert out["ok"] is True and ran == [(str(own.resolve()), True)] and own.is_dir()


async def test_with_someone_to_ask_the_chosen_folder_stays(folders):
    own, chosen, ran = folders
    await _choose(chosen)
    with permissions.asking_with(_ask):
        await RunCommandExecutor().execute({"command": "ls"})
    assert ran == [(str(chosen.resolve()), True)]


async def test_a_scheduled_runs_checkpoint_is_of_arslans_own_folder(folders, tmp_path, monkeypatch):
    """With S3a's checkpoints: the run's first command saves the folder it works in, ~/Arslan, never the
    user's chosen folder it no longer touches."""
    from server import config
    from server.services import checkpoints, execution_context
    own, chosen, ran = folders
    await _choose(chosen)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    checkpoints._reset_for_tests()
    with execution_context.bind_run(51):
        await RunCommandExecutor().execute({"command": "ls"})
    [root] = checkpoints.manifest(51)["roots"]
    assert root["path"] == str(own.resolve())
    checkpoints._reset_for_tests()
