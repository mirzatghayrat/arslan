"""#733 item 14 (v0.1.64): off means off. `run_python` never runs a script of a skill the user switched off, alone
on the Capabilities page or with its plugin's group, and runs it again once it is switched back on. The switches are
the real ones (`capability_list.switch`); on a Mac the scripts run in the real sandbox profile under seatbelt.

The refusal comes before the sandbox, so the tests that only check it run on every platform; the ones that also
need the script to run are macOS-only (Linux run_python refuses every script, P0-1)."""
import sys

import pytest
from sqlalchemy.exc import OperationalError

from server import config
from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.registry.executors import RunPythonExecutor
from server.services import capability_list, code_sandbox

pytestmark = pytest.mark.asyncio

_SKIP_WITHOUT_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin" or not code_sandbox.backend_available(),
    reason="runs the script in the real sandbox (macOS seatbelt); Linux run_python refuses every script")

PLUGIN = "plugin-src-1"
ALONE, PART = "csv-tidy", "plug-notes"           # a skill on its own, and one of the plugin's
SWITCH = {ALONE: f"skill:{ALONE}", PART: f"plugin:{PLUGIN}"}


def _pack(key: str, **extra) -> SkillPack:
    return SkillPack(key=key, name=key.replace("-", " ").title(), category="imported", description="d", tier="safe",
                     status="registered", body="## Trigger\nx", **extra)


@pytest.fixture
async def scripts(execution_db, monkeypatch, tmp_path):
    """Both skills installed, each with an entry script that imports a sibling. Returns the code each run handed
    to the sandbox: the real `run_python` still runs it, the list only shows whether it was reached."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    for key in (ALONE, PART):
        folder = tmp_path / "data" / "skill_scripts" / key
        folder.mkdir(parents=True)
        (folder / "helper.py").write_text(f"WORD = {key!r}\n")
        (folder / "main.py").write_text("from helper import WORD\nprint('RAN-' + WORD)\n")
    async with execution_db() as db:
        db.add(CapabilitySource(id=PLUGIN, kind="plugin", name="Plug", candidate_id="github:x/plug", runtime="plugin",
                                needs={}, grants={}, state="installed"))
        db.add_all([_pack(ALONE), _pack(PART, source_id=PLUGIN)])
        await db.commit()
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test-env"))
    reached: list[str] = []
    real = code_sandbox.run_python

    async def counted(code, **kwargs):
        reached.append(code)
        return await real(code, **kwargs)

    monkeypatch.setattr(code_sandbox, "run_python", counted)
    return reached


async def _run(key: str) -> dict:
    return await RunPythonExecutor().execute({"skill_script": f"{key}/main.py"})


def _refused(out: dict, key: str) -> None:
    """A plain result the model can act on: the skill is off. Nothing ran, so no output and no raw error."""
    assert out["ok"] is False and out["external"] is False, out
    assert out["error"].startswith(f"skill switched off by the user: {key}."), out
    assert not {"stdout", "stderr", "exit_code"} & out.keys(), out


@pytest.mark.parametrize("key", [ALONE, PART])
async def test_a_switched_off_skills_script_never_reaches_the_sandbox(scripts, key, monkeypatch):
    def unread(ref):
        raise AssertionError(f"an off skill's files were read: {ref}")

    monkeypatch.setattr(RunPythonExecutor, "_load_skill_script", staticmethod(unread))   # refused before any read
    await capability_list.switch(SWITCH[key], False)
    _refused(await _run(key), key)
    # The loader strips the ref, so the switch is read by the same key: spaces round it don't get past.
    _refused(await RunPythonExecutor().execute({"skill_script": f"  {key}/main.py \n"}), key)
    assert scripts == []


async def test_a_plugin_switched_off_holds_its_skill_and_leaves_another_skill_alone(scripts, monkeypatch):
    """The group's switch reaches its own skill only; a skill on its own keeps running (the sandbox stubbed here,
    so this one runs on every platform)."""
    async def ran(code, **kwargs):
        return {"ok": True, "stdout": "RAN", "files": [], "sandboxed": True, "network_isolated": True}

    monkeypatch.setattr(code_sandbox, "run_python", ran)
    await capability_list.switch(SWITCH[PART], False)
    _refused(await _run(PART), PART)
    assert (await _run(ALONE))["ok"] is True


async def test_a_failed_switch_lookup_runs_nothing_and_reads_no_file(scripts, monkeypatch):
    """Fail closed: when the skill's row can't be read, the error surfaces and no script is read or run."""
    class _BrokenSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            raise OperationalError("SELECT skill_packs", {}, Exception("database is locked"))

    def unread(ref):
        raise AssertionError(f"a script was read although the switch could not be: {ref}")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", _BrokenSession)
    monkeypatch.setattr(RunPythonExecutor, "_load_skill_script", staticmethod(unread))
    with pytest.raises(OperationalError):
        await _run(ALONE)
    assert scripts == []


async def test_a_link_to_another_skills_files_is_refused_and_a_plain_script_still_runs(scripts, tmp_path,
                                                                                      monkeypatch):
    """An off skill's code isn't reached under another key through a link: neither a folder linking to its folder
    (under a key with a row of its own: a key with none is refused before any file is read) nor a file in an on
    skill's folder linking to its script, run directly or beside the script that runs. Each refusal names the link.
    The plain script runs once the link beside it is gone."""
    handed: list[tuple[str, dict]] = []

    async def ran(code, *, extra_files=None, read_only_files=None):
        handed.append((code, extra_files))
        return {"ok": True, "stdout": "RAN", "files": [], "sandboxed": True, "network_isolated": True}

    monkeypatch.setattr(code_sandbox, "run_python", ran)
    await capability_list.switch(SWITCH[ALONE], False)
    async with db_session.AsyncSessionLocal() as db:
        db.add(_pack("alias"))
        await db.commit()
    root = tmp_path / "data" / "skill_scripts"
    (root / "alias").symlink_to(root / ALONE, target_is_directory=True)
    (root / PART / "via.py").symlink_to(root / ALONE / "main.py")
    linked = "is a link (a symlink), so Arslan won't run or read it"
    for ref, error in (("alias/main.py", f"skill folder {linked}: alias"),
                       (f"{PART}/via.py", f"skill file {linked}: {PART}/via.py"),
                       (f"{PART}/main.py", f"skill file {linked}: {PART}/via.py")):
        out = await RunPythonExecutor().execute({"skill_script": ref})
        assert out == {"ok": False, "external": False, "error": error}, out
    assert handed == []

    (root / PART / "via.py").unlink()
    assert (await _run(PART))["ok"] is True
    assert handed == [((root / PART / "main.py").read_text(), {"helper.py": f"WORD = {PART!r}\n"})]


@pytest.mark.macos               # selection for the macOS job, alongside the skip, never instead of it
@_SKIP_WITHOUT_SEATBELT
@pytest.mark.parametrize("key", [ALONE, PART])
async def test_on_runs_off_does_not_and_back_on_runs_again(scripts, key, tmp_path):
    on = await _run(key)
    assert on["ok"] is True and on["sandboxed"] is True and f"RAN-{key}" in on["stdout"], on
    assert len(scripts) == 1

    await capability_list.switch(SWITCH[key], False)
    _refused(await _run(key), key)
    assert len(scripts) == 1                                           # the sandbox was never reached
    # Nor does code of the model's own read the off skill's files: the sandbox never granted the scripts folder.
    entry = tmp_path / "data" / "skill_scripts" / key / "main.py"
    peek = await RunPythonExecutor().execute({"code": (
        "try:\n"
        f"    print('READ=' + open({str(entry)!r}).read())\n"
        "except OSError as e:\n"
        "    print('DENIED=' + type(e).__name__)\n")})
    assert peek["ok"] is True and "DENIED=PermissionError" in peek["stdout"] and "READ=" not in peek["stdout"], peek

    await capability_list.switch(SWITCH[key], True)
    again = await _run(key)
    assert again["ok"] is True and f"RAN-{key}" in again["stdout"], again
