"""Opt-in actual stable host calls. Passing asserts execution, NOT quality/UI."""
import hashlib
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
from server.db.models import ArslanMessage
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

    @task_context.scoped_turn
    async def turn(conversation_id, user_message):
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, events.append)

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
        "quality_status": "not_run", "native_status": "not_run"})
    assert isinstance(result, str) and result.strip()
    assert not any(event.get("type") == "error" for event in events)
    assert persisted
