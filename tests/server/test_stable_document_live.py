"""Opt-in actual stable host calls. Passing asserts execution, NOT quality/UI."""
import hashlib
import csv
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest
from sqlalchemy import select

from evals.companion import stable_budget as budget
from evals.companion.stable_documents import DOCUMENT_CASES, verified_preflight
from evals.companion.stable_live import StableAdapter, persist
from evals.companion.stable_primary import primary_adapter, pricing_snapshot
from server.db.models import ArslanMessage, Setting
from server.orchestrator import arslan, memory, tool_loop
from server.services import ingest, knowledge, task_context

pytestmark = pytest.mark.skipif(
    os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5",
    reason="independent stable paid-call grant requires explicit opt-in")


@pytest.mark.parametrize("case_id", DOCUMENT_CASES)
async def test_stable_document_host(case_id, execution_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "isolated-data"))
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    ready, digest = verified_preflight(case_id)
    record_path = budget.EVIDENCE / f"{case_id}-result.json"
    if record_path.exists() or budget.status()["by_case"][case_id]:
        raise RuntimeError("stable_no_automatic_case_repeat")
    pricing = pricing_snapshot(budget.EVIDENCE / os.environ["ARSLAN_STABLE_PRICING"])
    # Lock out accidental external tools/secondary providers. One allowed POST
    # goes through the durable StableAdapter; all other HTTP is a harness error.
    original_send = httpx.AsyncClient.send

    async def restricted_send(client, request, **kwargs):
        if (request.method != "POST" or str(request.url) not in {
                "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/v1/chat/completions"}):
            raise RuntimeError("stable_unapproved_network_request")
        return await original_send(client, request, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", restricted_send)
    adapter = StableAdapter(primary_adapter(Path.home() / "Library/Application Support/Arslan",
        Path.home() / ".arslan/secret_key", pricing), case_id, pricing, digest)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(memory, "_get_adapter", lambda: adapter)

    async def no_tools():
        return []

    async def no_roster():
        return ""

    async def no_knowledge(*args, **kwargs):
        return []

    monkeypatch.setattr(arslan, "_arslan_tools", no_tools)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(knowledge, "retrieve_scoped", no_knowledge)

    tool_trace = []
    workspace = tmp_path / "workspace"
    if case_id == "S2-D3":
        workspace.mkdir()
        async with execution_db() as db:
            db.add_all([Setting(key="workspace_dir", value=str(workspace)),
                        Setting(key="default_read_enabled", value="false")])
            await db.commit()

        async def file_tools():
            return [{"key": "write_file", "description": "Write the approved totals.csv in the isolated workspace."},
                    {"key": "read_file", "description": "Read totals.csv to verify the saved output."}]

        class RestrictedFile:
            def __init__(self, key, delegate):
                self.key, self.delegate = key, delegate

            async def execute(self, args):
                if args.get("path") != "totals.csv":
                    result = {"ok": False, "error": "Outside the approved synthetic file"}
                else:
                    result = await self.delegate.execute(args)
                tool_trace.append({"tool": self.key, "args": args, "result": result})
                return result

        from server.registry.file_tools import ReadFileExecutor, WriteFileExecutor
        for delegate in (ReadFileExecutor(), WriteFileExecutor()):
            monkeypatch.setitem(tool_loop.EXECUTORS, delegate.key, RestrictedFile(delegate.key, delegate))
        monkeypatch.setattr(arslan, "_arslan_tools", file_tools)

    async def confirm_write(tool, path):
        return case_id == "S2-D3" and tool == "write_file" and path == "totals.csv"

    @task_context.scoped_turn
    async def turn(conversation_id, user_message):
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, events.append,
                                          confirm_workspace_write=confirm_write)

    events = []
    result = await turn(case_id, ready["prompt"])
    async with execution_db() as db:
        answers = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == case_id, ArslanMessage.role == "arslan"))).all()
    persisted = any(message.content == result for message in answers)
    persist(record_path, {"case": case_id, "answer": result, "events": events,
        "persisted_in_isolated_db": persisted, "preflight_sha256": digest,
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quality_status": "not_run", "native_status": "not_run", "tool_trace": tool_trace})
    assert isinstance(result, str) and result.strip()
    assert not any(event.get("type") == "error" for event in events)
    assert persisted
    if case_id == "S2-D3":
        from server.services import artifact_store
        from tests.server.test_stage2_inputs import CASES
        target = workspace / "totals.csv"
        assert target.is_file() and not target.is_symlink()
        data = target.read_bytes()
        with (budget.EVIDENCE / "S2-D3-totals.csv").open("xb") as stream:
            stream.write(data)
        with target.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        manifests = []
        for path in artifact_store.root().glob("*.manifest.json"):
            item = json.loads(path.read_bytes())
            if item["title"] == "totals.csv":
                metadata, stored = artifact_store.read_owned(item["run_id"], item["filename"])
                manifests.append({"metadata": metadata, "bytes_match_workspace": stored == data})
        checks = {"two_currency_rows": len(rows) == 2,
                  "totals_match": {row.get("currency"): row.get("known_total") for row in rows} == CASES[case_id]["expected_totals"],
                  "readback_tool_succeeded": any(item["tool"] == "read_file" and item["result"].get("ok") for item in tool_trace),
                  "artifact_reopened": any(item["bytes_match_workspace"] for item in manifests)}
        persist(budget.EVIDENCE / "S2-D3-artifact-review.json", {"rows": rows, "checks": checks,
            "sha256": hashlib.sha256(data).hexdigest(), "manifests": manifests,
            "semantic_review": "not_run", "native_open": "not_run"})
        assert all(checks.values()), checks
