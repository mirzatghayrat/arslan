"""Real child-process exit, synthetic repository boundary; not native/live M4.

No provider is called. Budget increments below are deliberately synthetic.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_PROCESS") != "1",
                              reason="explicit isolated process recovery rehearsal")

CHILD = r'''
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

def audit(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
        raise RuntimeError("network_forbidden_in_process_rehearsal")
sys.addaudithook(audit)

from sqlalchemy import select
from arslan.companion.contracts import ResourceRef, TaskSpec
from arslan.execution_budget import Budget
from server.config import settings
from server.db.models import TaskAction, TaskAttempt
from server.db.session import engine
from server.services.storage_boot import initialize
from server.services.task_repository import Progress, TaskError, repository

profile = Path(os.environ["ARSLAN_DATA_DIR"])
assert Path(settings.data_dir).resolve() == profile.resolve()
assert Path(settings.db_path).resolve() == (profile / "arslan.db").resolve()
profile.mkdir(parents=True, exist_ok=True)
artifact = profile / "synthetic-report.md"
content = "# Cedar\nOwner: Mira. Deadline: Monday (date unspecified).\nSource: isolated synthetic brief.\n"
ref = ResourceRef(id="synthetic-report", kind="artifact", revision=1,
                  sha256=hashlib.sha256(content.encode()).hexdigest())
identity = "stable-process-recovery"
arguments = {"path": str(artifact), "content": content}
mode, operation = sys.argv[1:]

async def refused(operation, code):
    try:
        await operation
    except TaskError as exc:
        assert code in str(exc), str(exc)
    else:
        raise AssertionError("missing refusal: " + code)

async def main():
    await initialize(engine)
    if operation == "crash":
        spec = TaskSpec.model_validate({
            "id": identity, "scope": {"kind": "task", "owner_id": "local", "task_id": identity},
            "instruction": "Retain the synthetic Cedar brief for explicit review", "locale": "en",
            "acceptance": [{"id": "review", "description": "Human review required",
                            "evaluator": "human", "critical": True}],
        })
        async with repository() as repo:
            created = await repo.create(spec, "synthetic-conversation")
            started = await repo.start(identity, created["version"])
        attempt = started["state"]["run_id"]
        budget = Budget.from_snapshot(started["budget"])
        budget.model_request(100)  # Counter only: no model/provider invocation.
        budget.tool()
        budget.tokens = 42
        budget.reserve_artifact(len(content.encode()))
        async with repository() as repo:
            await repo.checkpoint(identity, attempt, budget.snapshot(), Progress())
            action = await repo.prepare_action(identity, attempt, tool_key="save_file",
                                               arguments=arguments, effect="local_write")
            await repo.action_started(identity, attempt, action["id"])
        with artifact.open("x") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode == "completed":
            async with repository() as repo:
                await repo.action_finished(identity, attempt, action["id"], status="succeeded", evidence=(ref,))
                await repo.checkpoint(identity, attempt, budget.snapshot(),
                                      Progress(completed_steps=("report-saved",), artifacts=(ref,)))
        # Real interpreter exit after committed SQL/file writes, no cleanup.
        os._exit(73)

    before = artifact.stat()
    assert artifact.read_text() == content
    async with repository() as repo:
        row = await repo.get(identity)
        assert row.phase == "running"
        original = row.budget
        assert original["used"]["model_requests"] == 1
        assert await repo.recover_interrupted() == 1
    async with repository() as repo:
        assert await repo.recover_interrupted() == 0
        row = await repo.get(identity)
        assert row.phase == "waiting_user" and row.pause_reason == "process_interrupted"
        assert row.budget == original
        assert len((await repo.db.execute(select(TaskAttempt))).scalars().all()) == 1
        checkpoint = await repo.latest_checkpoint(identity)
        if mode == "completed":
            assert checkpoint["progress"]["completed_steps"] == ["report-saved"]
            assert checkpoint["progress"]["artifacts"] == [ref.model_dump(mode="json")]
        await refused(repo.start(identity, row.version), "explicit_resume")
    if mode == "uncertain":
        async with repository() as repo:
            row = await repo.get(identity)
            await refused(repo.start(identity, row.version, explicit_resume=True), "reconciliation_required")
            action = await repo.db.scalar(select(TaskAction))
            assert action.status == "uncertain"
            await refused(repo.reconcile_action(identity, action.id, expected_version=action.version,
                                                applied=True, evidence=()), "evidence_required")
            # Trusted harness read-back, not a model claiming its own success.
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == ref.sha256
            await repo.reconcile_action(identity, action.id, expected_version=action.version,
                                        applied=True, evidence=(ref,))
    async with repository() as repo:
        row = await repo.get(identity)
        resumed = await repo.start(identity, row.version, explicit_resume=True)
        assert resumed["budget"]["id"] == original["id"]
        assert resumed["budget"]["used"]["model_requests"] == 1
        assert resumed["budget"]["used"]["tool_calls"] == 1
        assert resumed["budget"]["used"]["tokens"] == 42
        assert resumed["budget"]["used"]["artifact_bytes"] == len(content.encode())
        assert len((await repo.db.execute(select(TaskAttempt))).scalars().all()) == 2
        attempt = resumed["state"]["run_id"]
        await refused(repo.prepare_action(identity, attempt, tool_key="save_file", arguments=arguments,
                                          effect="local_write"), "already_completed")
        budget = Budget.from_snapshot(resumed["budget"])
        budget.model_request(100)  # Another synthetic counter increment only.
        await repo.checkpoint(identity, attempt, budget.snapshot(),
                              Progress(completed_steps=("report-saved",), artifacts=(ref,)))
        final = await repo.finish(identity, attempt, phase="waiting_user", reason="acceptance_review_required")
        assert final["budget"]["used"]["model_requests"] == 2
        assert final["budget"]["id"] == original["id"]
    after = artifact.stat()
    assert (before.st_ino, before.st_mtime_ns, before.st_size) == (after.st_ino, after.st_mtime_ns, after.st_size)
    assert artifact.read_text() == content
    await engine.dispose()
    return {"mode": mode, "phase": final["state"]["phase"], "budget_id": original["id"],
            "synthetic_model_counter_before": 1, "synthetic_model_counter_after": 2,
            "actual_provider_calls": 0, "artifact_sha256": ref.sha256,
            "checks": ["explicit_resume", "boot_does_not_run", "file_unchanged", "same_budget",
                       "no_repeated_write", "review_not_success"], "native_ui": False}

print(json.dumps(asyncio.run(main())))
'''


@pytest.mark.parametrize("mode", ["completed", "uncertain"])
def test_real_process_exit_requires_explicit_recovery(tmp_path, mode):
    profile = tmp_path / "profile"
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
        "ARSLAN_DATA_DIR": str(profile), "ARSLAN_DB_PATH": str(profile / "arslan.db"),
        "ARSLAN_SECRET_KEY": "stable-process-synthetic-only", "ARSLAN_SECRET_KEY_FILE": "",
        "ARSLAN_ENV": "prod", "ARSLAN_LIVE_LLM": "0", "PYTHONDONTWRITEBYTECODE": "1",
    }
    results = []
    for operation, expected in (("crash", 73), ("recover", 0)):
        child = subprocess.run([sys.executable, "-c", CHILD, mode, operation], cwd=ROOT,
                               env=environment, text=True, capture_output=True, timeout=45)
        assert child.returncode == expected, child.stdout + child.stderr
        results.append({"operation": operation, "exit_code": child.returncode})
    evidence = json.loads(child.stdout.strip().splitlines()[-1])
    evidence["processes"] = results
    evidence["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    evidence["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    evidence["boundary"] = "Synthetic repository process rehearsal; not live-model M4, task-service, native UI or signed app acceptance"
    destination = os.environ.get("ARSLAN_STABLE_PROCESS_EVIDENCE")
    if destination:
        output = Path(destination)
        output.mkdir(parents=True, exist_ok=True)
        with (output / f"{mode}.json").open("x") as handle:
            json.dump(evidence, handle, indent=2)
            handle.write("\n")
