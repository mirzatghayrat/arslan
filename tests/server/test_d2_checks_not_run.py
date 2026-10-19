"""D2 (docs/plans/0162/D2-checks-not-run.md): a check that cannot run no longer parks finished work.

M1B baseline, T1: Arslan saved a helper script (.swift) with write_file, ran it, the reminders were
made and the task's own check passed, yet every run stopped at waiting_user / task_checks_not_run:
the snapshot's type had no parser, and "no parser" was reported as "the check did not run".

Now: common code and config text is decoded as UTF-8 (not structurally parsed); a type with no
parser at all is not_applicable, decided on the host before any sandbox starts. Real failures still
hold the work: a failed decode or parse, a timeout, isolation missing for a type that has a parser.
"""
import pytest

from server.resources import artifact_inspector
from server.resources.artifact_inspector import inspect
from server.services import artifact_validation, code_sandbox, execution_context, task_service
from tests.server.test_job_checks_0159 import _answer_check, disk, home, run_contract  # noqa: F401


async def as_on_a_mac(data, suffix):
    """The isolated parser, as it runs inside macOS' seatbelt (absent on Linux CI)."""
    try:
        return inspect(data, suffix)
    except Exception:
        return {"status": "failed", "code": "artifact_parse_failed"}


# ── the inspector: code and config text is decoded ───────────────────────────────────

@pytest.mark.parametrize("suffix", [".swift", ".sh", ".applescript", ".yaml", ".toml", ".xml", ".log"])
def test_code_and_config_text_is_decoded(suffix):
    assert inspect(b"import EventKit\nlet store = EKEventStore()\n", suffix)["status"] == "passed"


def test_text_that_does_not_decode_still_fails():
    with pytest.raises(UnicodeDecodeError):           # the inspector's entry point reports it as failed
        inspect(b"\xff\xfe\x00 not utf-8 \x9f", ".sh")


def test_xml_is_decoded_not_parsed():
    # No structural parse, so no entity expansion: a DOCTYPE is just text here.
    assert inspect(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', ".xml")["status"] == "passed"


def test_one_list_of_checked_types_and_every_entry_has_a_parser():
    assert artifact_validation.checked_suffixes() == artifact_inspector.CHECKED_SUFFIXES
    for suffix in artifact_inspector.CHECKED_SUFFIXES:
        try:
            routed = inspect(b"x", suffix).get("code") != "artifact_parser_unavailable"
        except Exception:
            routed = True                              # its parser ran and refused the sample
        assert routed, suffix


# ── inspect_bytes: no parser is not_applicable, decided before any sandbox ─────────────

async def test_a_type_with_no_parser_is_not_applicable_without_a_sandbox(monkeypatch):
    def no_sandbox(*args, **kwargs):
        raise AssertionError("a sandbox was started for a type nothing parses")
    monkeypatch.setattr(code_sandbox, "_host_python", no_sandbox)
    monkeypatch.setattr(code_sandbox, "_seatbelt_wrapper", no_sandbox)
    assert await artifact_validation.inspect_bytes(b"\x00\x01\x02", ".bin") == {
        "status": "not_applicable", "code": "artifact_type_not_checked"}


async def test_undecodable_code_text_still_fails_through_inspect_bytes(monkeypatch):
    # A code type must be in the checked list, not just parsed: otherwise a broken .sh is waved through.
    monkeypatch.setattr(artifact_validation, "_inspect_isolated", as_on_a_mac)
    assert (await artifact_validation.inspect_bytes(b"\xff\xfe\x00 not utf-8 \x9f", ".sh"))["status"] == "failed"


async def test_a_known_type_without_isolation_is_still_not_run(monkeypatch):
    monkeypatch.setattr(code_sandbox, "_seatbelt_wrapper", lambda profile: None)
    result = await artifact_validation.inspect_bytes(b"import EventKit\n", ".swift")
    assert result == {"status": "not_run", "code": "artifact_parser_isolation_unavailable"}


# ── the task: finished work is not held by a helper file ─────────────────────────────

async def _saving(path: str, content: str, monkeypatch, tmp_path):
    from server import config
    from server.db.models import Run
    from server.registry.file_tools import WriteFileExecutor
    from server.services.task_repository import repository
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    seen = {}

    async def body(emit):
        runtime = task_service.current()
        async with repository() as repo:
            row = await repo.get(runtime.task_id)
            run = Run(conversation_id=row.conversation_id, user_message="t")
            repo.db.add(run)
            await repo.db.flush()
            run_id = run.id
        await runtime.link_run(run_id)
        with execution_context.bind_run(run_id):
            seen["write"] = await runtime.execute_tool("write_file", {"path": path, "content": content},
                                                       WriteFileExecutor().execute)
        seen["runtime"] = runtime
        return "Added three reminders to the list."
    task = await run_contract([_answer_check()], body)
    return task, seen


async def test_a_saved_helper_script_no_longer_holds_finished_work(execution_db, disk, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(artifact_validation, "_inspect_isolated", as_on_a_mac, raising=False)
    task, seen = await _saving("add_reminders.swift", "import EventKit\n", monkeypatch, tmp_path)
    assert seen["write"].get("artifact")
    assert task.phase == "succeeded", (task.phase, task.pause_reason)


async def test_a_file_type_nothing_parses_does_not_hold_it_either(execution_db, disk, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(artifact_validation, "_inspect_isolated", as_on_a_mac, raising=False)
    task, seen = await _saving("export.bin", "raw", monkeypatch, tmp_path)
    artifacts = (seen["runtime"].validation_report or {}).get("artifacts")
    assert artifacts and all(a["status"] == "not_applicable" for a in artifacts)
    assert task.phase == "succeeded", (task.phase, task.pause_reason)


async def test_a_check_that_really_could_not_run_still_holds_it(execution_db, disk, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(code_sandbox, "_seatbelt_wrapper", lambda profile: None)
    task, _ = await _saving("add_reminders.swift", "import EventKit\n", monkeypatch, tmp_path)
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_checks_not_run")
