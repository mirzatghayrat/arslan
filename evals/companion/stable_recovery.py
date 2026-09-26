"""M4 host/process acceptance. No model or application starts on import."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from evals.companion import stable_budget as budget
from evals.companion.stable_live import persist

CASE = "S2-M4"
INPUT = {
    "prompt": "Synthetic source: Project Cedar brief, revision 1. Owner Mira; deadline Monday (no calendar date supplied). "
        "Using only this source, write at most three lines to brief.md, cite the source name/revision in the file, "
        "then reopen it with read_file and briefly report the result. Only brief.md is authorized for writing. "
        "Do not invent a calendar date, use accounts, or take external actions. If this task is resumed, "
        "retain the existing file and report from saved progress; do not rewrite completed work.",
    "source": "Synthetic Project Cedar brief, revision 1; owner Mira, deadline Monday, calendar date unspecified.",
    "lifecycle": "Two Python processes; os._exit(73) after host output and checkpoint, followed by storage initialization, recovery and explicit resume",
    "native_ui": "not_run",
    "uncertain_write": "Separate existing deterministic process-recovery-v1 evidence; this run interrupts after a completed write",
}


def freeze():
    if budget.status()["by_case"][CASE]:
        raise RuntimeError("stable_no_automatic_case_repeat")
    persist(budget.EVIDENCE / f"{CASE}-input.json", INPUT)
    persist(budget.EVIDENCE / f"{CASE}-preflight.json", {
        "case": CASE, "status": "ready", "contract_sha256": budget.contract()[1],
        "inputs": [{"path": f"{CASE}-input.json", "sha256": hashlib.sha256(
            (budget.EVIDENCE / f"{CASE}-input.json").read_bytes()).hexdigest()}],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "acceptance": next(c["acceptance"] for c in budget.contract()[0]["cases"] if c["id"] == CASE),
        "quality_status": "not_run", "native_status": "not_run"})


def verified():
    raw = (budget.EVIDENCE / f"{CASE}-preflight.json").read_bytes()
    ready = json.loads(raw)
    if (ready["contract_sha256"] != budget.contract()[1] or ready["status"] != "ready"
            or ready["runner_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or json.loads((budget.EVIDENCE / f"{CASE}-input.json").read_bytes()) != INPUT):
        raise RuntimeError("stable_recovery_preflight_changed")
    return hashlib.sha256(raw).hexdigest()


async def run_phase(phase, profile, evidence, adapter):
    """Same host path for offline doubles and separately authorized real calls."""
    from sqlalchemy import select
    from server.config import settings
    from server.db.models import Setting, TaskAction, TaskAttempt
    from server.db.session import engine, AsyncSessionLocal
    from server.orchestrator import arslan, memory, tool_loop
    from server.registry.file_tools import ReadFileExecutor, WriteFileExecutor
    from server.services import artifact_store, knowledge, personal_context as pc, task_service
    from server.services.storage_boot import initialize
    from server.services.task_repository import repository, TaskError

    assert Path(settings.data_dir).resolve() == profile.resolve()
    assert Path(settings.db_path).resolve() == (profile / "arslan.db").resolve()
    assert phase in {"crash", "resume"}
    evidence.mkdir(parents=True, exist_ok=True)
    persist(evidence / f"{phase}-started.json", {"phase": phase, "pid": os.getpid(),
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    profile.mkdir(parents=True, exist_ok=True)
    await initialize(engine)
    workspace = profile / "workspace"
    workspace.mkdir(exist_ok=True)
    target = workspace / "brief.md"
    production_tools = arslan._arslan_tools
    trace, events = [], []

    async def tools():
        return [t for t in await production_tools() if t["key"] in {"write_file", "read_file", "task_progress"}]

    async def no_roster():
        return ""

    async def no_knowledge(*args, **kwargs):
        return []

    class Restricted:
        def __init__(self, delegate):
            self.delegate, self.key = delegate, delegate.key

        async def execute(self, args):
            result = (await self.delegate.execute(args) if args.get("path") == "brief.md" else
                      {"ok": False, "error": "Outside isolated acceptance path"})
            trace.append({"tool": self.key, "args": args, "result": result})
            return result

    tool_loop._get_adapter = memory._get_adapter = lambda: adapter
    arslan._arslan_tools, arslan._team_roster, knowledge.retrieve_scoped = tools, no_roster, no_knowledge
    for delegate in (ReadFileExecutor(), WriteFileExecutor()):
        tool_loop.EXECUTORS[delegate.key] = Restricted(delegate)

    async def confirm_write(tool, path):
        # Resume never grants a new write; the completed-action journal also
        # remains active. This does not pretend to test native approval UI.
        return phase == "crash" and tool == "write_file" and path == "brief.md"

    def artifact_checks():
        records = []
        for path in artifact_store.root().glob("*.manifest.json"):
            item = json.loads(path.read_bytes())
            if item["title"] == "brief.md":
                metadata, data = artifact_store.read_owned(item["run_id"], item["filename"])
                records.append({"metadata": metadata, "matches_workspace": target.is_file() and data == target.read_bytes()})
        return records

    async def snapshot(answer):
        async with repository() as repo:
            row = await repo.get(CASE)
            checkpoint = await repo.latest_checkpoint(CASE)
            attempts = (await repo.db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == CASE))).all()
            actions = (await repo.db.scalars(select(TaskAction).where(TaskAction.task_id == CASE))).all()
            return {"phase": row.phase, "pause_reason": row.pause_reason, "version": row.version,
                "budget": row.budget, "checkpoint": checkpoint, "attempts": len(attempts),
                "actions": [{"tool": a.tool_key, "status": a.status} for a in actions],
                "answer": answer, "events": events, "trace": trace, "artifacts": artifact_checks(),
                "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
                "quality_status": "not_run", "native_status": "not_run"}

    if phase == "crash":
        async with AsyncSessionLocal() as db:
            db.add_all([Setting(key="workspace_dir", value=str(workspace)), Setting(key="default_read_enabled", value="false")])
            await db.commit()
        await memory.add_message(CASE, "user", INPUT["prompt"])

        async def interrupted(conversation, message, emit):
            answer = await arslan._handle_answer(conversation, message, emit, confirm_workspace_write=confirm_write)
            # Preserve actual product progress, not invented counters/refs.
            await task_service.current().checkpoint("acceptance_process_exit")
            record = await snapshot(answer)
            if target.is_file():
                info = target.stat()
                record["file"] = {"text": target.read_text(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "inode": info.st_ino, "mtime_ns": info.st_mtime_ns}
            persist(evidence / "before-crash.json", record)
            assert target.is_file() and record["artifacts"] and all(a["matches_workspace"] for a in record["artifacts"])
            assert any(t["tool"] == "read_file" and t["result"].get("ok") for t in trace)
            assert record["phase"] == "running" and record["checkpoint"]["progress"]["evidence"]
            os._exit(73)

        context = pc.TaskMemoryContext(task_id=CASE, run_id="initial", conversation_id=CASE, no_learning=True)
        with pc.bind(context):
            await task_service.run_turn(interrupted, CASE, INPUT["prompt"], events.append)
        raise AssertionError("expected real process exit")

    before = json.loads((evidence / "before-crash.json").read_bytes())
    assert await task_service.recover_interrupted() == 1
    assert await task_service.recover_interrupted() == 0
    recovered = await snapshot(None)
    persist(evidence / "recovered-no-resume.json", recovered)
    assert recovered["phase"] == "waiting_user" and recovered["pause_reason"] == "process_interrupted"
    assert recovered["budget"] == before["budget"] and recovered["attempts"] == 1
    async with repository() as repo:
        try:
            await repo.start(CASE, recovered["version"])
        except TaskError as error:
            assert "explicit_resume" in str(error)
        else:
            raise AssertionError("implicit resume allowed")
    answer = await task_service.resume_turn(CASE, recovered["version"], CASE, events.append,
                                          confirm_workspace_write=confirm_write)
    final = await snapshot(answer)
    info = target.stat()
    final["file_unchanged"] = (hashlib.sha256(target.read_bytes()).hexdigest() == before["file"]["sha256"]
        and info.st_ino == before["file"]["inode"] and info.st_mtime_ns == before["file"]["mtime_ns"])
    persist(evidence / "after-resume.json", final)
    assert final["file_unchanged"] and all(a["matches_workspace"] for a in final["artifacts"])
    assert final["budget"]["id"] == before["budget"]["id"]
    assert final["budget"]["used"]["model_requests"] > before["budget"]["used"]["model_requests"]
    assert final["attempts"] == 2 and final["phase"] == "waiting_user"
    assert final["pause_reason"] == "acceptance_review_required"
    assert sum(a["tool"] == "write_file" and a["status"] == "succeeded" for a in final["actions"]) == 1
    assert not any(t["tool"] == "write_file" for t in trace)
    await engine.dispose()


if __name__ == "__main__":
    import argparse
    import asyncio
    import httpx
    from evals.companion.stable_primary import pricing_snapshot, primary_adapter
    from evals.companion.stable_live import StableAdapter
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "crash", "resume"))
    parser.add_argument("--primary-home", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
        print("M4 inputs and runner frozen; no model calls")
    else:
        digest = verified()
        if args.phase == "crash" and budget.status()["by_case"][CASE]:
            raise RuntimeError("stable_no_automatic_case_repeat")
        if not args.primary_home or os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5":
            raise RuntimeError("stable_explicit_primary_authorization_required")
        profile = budget.EVIDENCE / "M4-profile-v1"
        assert Path(os.environ["ARSLAN_DATA_DIR"]).resolve() == profile.resolve()
        original_send = httpx.AsyncClient.send

        async def restricted_send(client, request, **kwargs):
            if request.method != "POST" or str(request.url) not in {
                    "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/v1/chat/completions"}:
                raise RuntimeError("stable_unapproved_network_request")
            return await original_send(client, request, **kwargs)

        httpx.AsyncClient.send = restricted_send
        pricing = pricing_snapshot(budget.EVIDENCE / os.environ["ARSLAN_STABLE_PRICING"])
        adapter = StableAdapter(primary_adapter(args.primary_home / "Library/Application Support/Arslan",
            args.primary_home / ".arslan/secret_key", pricing), CASE, pricing, digest)
        asyncio.run(run_phase(args.phase, profile, budget.EVIDENCE / "M4-process-v1", adapter))
