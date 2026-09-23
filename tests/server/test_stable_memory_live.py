"""Opt-in real host memory cases on fresh synthetic databases, never real chat."""
import hashlib
import os
from pathlib import Path
import subprocess

import httpx
import pytest
from sqlalchemy import select

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from evals.companion import stable_budget as budget
from evals.companion.stable_live import StableAdapter, persist
from evals.companion.stable_memory import CASES, verified
from evals.companion.stable_primary import primary_adapter, pricing_snapshot
from server.db.models import ArslanMessage, ConversationContext, Project
from server.orchestrator import arslan, memory, tool_loop
from server.services import knowledge, task_context
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository

pytestmark = pytest.mark.skipif(
    os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5",
    reason="independent stable paid-call grant requires explicit opt-in")


@pytest.mark.parametrize("case_id", CASES)
async def test_stable_memory_host(case_id, execution_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "isolated-data"))
    inputs, digest = verified(case_id)
    if budget.status()["by_case"][case_id] or (budget.EVIDENCE / f"{case_id}-result.json").exists():
        raise RuntimeError("stable_no_automatic_case_repeat")
    pricing = pricing_snapshot(budget.EVIDENCE / os.environ["ARSLAN_STABLE_PRICING"])
    original_send = httpx.AsyncClient.send

    async def restricted_send(client, request, **kwargs):
        if request.method != "POST" or str(request.url) not in {
            "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/v1/chat/completions"}:
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
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    if case_id == "S2-M1":
        async with execution_db() as db:
            db.add_all([Project(**project) for project in inputs["projects"]])
            await db.commit()
        async with repository() as repo:
            entry = await repo.create(MemoryWrite(content=inputs["entry"],
                scope=MemoryScope(kind="project", id="project-a"), use_policy="cloud_allowed"), MemoryActor(origin="user"))
    else:
        async with repository() as repo:
            entry = await repo.create(MemoryWrite(content=inputs["entry"], scope=MemoryScope(kind="global"),
                use_policy="cloud_allowed"), MemoryActor(origin="extractor", cloud_memory_allowed=True))
        assert entry["status"] == "proposed"
    states = [entry]

    @task_context.scoped_turn
    async def turn(conversation_id, user_message, emit):
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, emit)

    records = []
    for index, item in enumerate(inputs["turns"]):
        if case_id == "S2-M2" and index == 1:
            async with repository() as repo:
                corrected = await repo.revise(entry["id"], entry["version"], MemoryWrite(content=inputs["correction"],
                    scope=MemoryScope(kind="global"), use_policy="cloud_allowed"), MemoryActor(origin="user"))
            states.append(corrected)
        async with execution_db() as db:
            db.add(ConversationContext(id=item["conversation"], project_id=item["project"], cloud_memory_allowed=True))
            await db.commit()
        events = []
        answer = await turn(item["conversation"], item["prompt"], events.append)
        async with execution_db() as db:
            stored = (await db.scalars(select(ArslanMessage).where(
                ArslanMessage.conversation_id == item["conversation"], ArslanMessage.role == "arslan"))).all()
        record = {"conversation": item["conversation"], "answer": answer, "events": events,
                  "persisted": any(row.content == answer for row in stored), "quality_status": "not_run"}
        persist(budget.EVIDENCE / f"{item['conversation']}-turn.json", record)
        records.append(record)
        assert record["persisted"] and isinstance(answer, str) and answer.strip()
        assert not any(event.get("type") == "error" for event in events)
    persist(budget.EVIDENCE / f"{case_id}-result.json", {"case": case_id, "turns": records,
        "memory_states": states, "preflight_sha256": digest,
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quality_status": "not_run", "native_status": "not_run"})
