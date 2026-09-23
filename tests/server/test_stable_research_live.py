"""Opt-in research real host/tools; execution is not semantic acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest
from sqlalchemy import select

from arslan.companion.research import admitted_sources
from evals.companion import stable_budget as budget, stable_research as research
from evals.companion.stable_live import StableAdapter, persist
from evals.companion.stable_primary import primary_adapter, pricing_snapshot
from server.db.models import ArslanMessage, Setting
from server.orchestrator import arslan, memory, tool_loop
from server.registry import net_pin
from server.registry.executors import WebExtractExecutor
from server.registry.file_tools import ReadFileExecutor, WriteFileExecutor
from server.services import artifact_store, knowledge, task_context

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5",
                              reason="independent stable paid-call grant requires explicit opt-in")


@pytest.mark.parametrize("case", research.CASES)
async def test_stable_research_host(case, execution_db, monkeypatch, tmp_path):
    if (budget.EVIDENCE / f"{case}-result.json").exists() or budget.status()["by_case"][case]:
        raise RuntimeError("stable_no_automatic_case_repeat")
    value = research.verified(case)
    ready = json.loads((budget.EVIDENCE / f"{case}-preflight.json").read_bytes())
    urls = ready["urls"]
    hashes = {url: item["sha256"] for url, item in zip(urls, ready["inputs"], strict=True)}
    pricing = pricing_snapshot(budget.EVIDENCE / os.environ["ARSLAN_STABLE_PRICING"])
    production_tools = arslan._arslan_tools
    original_send, original_get = httpx.AsyncClient.send, net_pin.pinned_get
    fetched, transport, trace, events = set(), [], [], []

    async def restricted_send(client, request, **kwargs):
        model = request.method == "POST" and str(request.url) in {
            "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/v1/chat/completions"}
        public = (request.method == "GET" and request.url.scheme == "https"
                  and (request.headers.get("host"), request.url.path) in {
                      (httpx.URL(url).host, httpx.URL(url).path) for url in urls}
                  and not request.url.query and "authorization" not in request.headers)
        if not model and not public:
            raise RuntimeError("stable_unapproved_network_request")
        return await original_send(client, request, **kwargs)

    async def verified_get(url):
        if url not in hashes or url in fetched:
            raise RuntimeError("stable_unapproved_or_repeated_public_read")
        fetched.add(url)
        response = await original_get(url)
        digest = hashlib.sha256(response.content).hexdigest()
        transport.append({"url": url, "sha256": digest, "bytes": len(response.content),
                          "matches_frozen_input": digest == hashes[url],
                          "address_pinning_delegated_to_proxy": net_pin._pinning_disabled_by_proxy(url)})
        if digest != hashes[url]:
            raise RuntimeError("stable_public_body_changed")
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", restricted_send)
    monkeypatch.setattr(net_pin, "pinned_get", verified_get)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "isolated-data"))
    adapter = StableAdapter(primary_adapter(Path.home() / "Library/Application Support/Arslan",
        Path.home() / ".arslan/secret_key", pricing), case, pricing, value["preflight_sha256"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(memory, "_get_adapter", lambda: adapter)

    async def tools():
        return [tool for tool in await production_tools() if tool["key"] in {"web_extract", "write_file", "read_file"}]

    async def no_roster():
        return ""

    async def no_knowledge(*args, **kwargs):
        return []

    class RestrictedTool:
        def __init__(self, delegate):
            self.delegate, self.key = delegate, delegate.key

        async def execute(self, args):
            allowed = args.get("url") in urls if self.key == "web_extract" else args.get("path") == "comparison.md"
            result = await self.delegate.execute(args) if allowed else {"ok": False, "error": "Outside isolated acceptance scope"}
            trace.append({"tool": self.key, "args": args, "result": result})
            return result

    monkeypatch.setattr(arslan, "_arslan_tools", tools)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(knowledge, "retrieve_scoped", no_knowledge)
    for delegate in (WebExtractExecutor(), ReadFileExecutor(), WriteFileExecutor()):
        monkeypatch.setitem(tool_loop.EXECUTORS, delegate.key, RestrictedTool(delegate))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with execution_db() as db:
        db.add_all([Setting(key="workspace_dir", value=str(workspace)), Setting(key="default_read_enabled", value="false")])
        await db.commit()

    async def confirm_write(tool, path):
        return tool == "write_file" and path == "comparison.md"

    @task_context.scoped_turn
    async def turn(conversation_id, user_message):
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, events.append,
                                          confirm_workspace_write=confirm_write)

    result = await turn(case, value["prompt"])
    async with execution_db() as db:
        answers = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == case, ArslanMessage.role == "arslan"))).all()
    persist(budget.EVIDENCE / f"{case}-result.json", {"case": case, "answer": result, "events": events,
        "persisted_in_isolated_db": any(answer.content == result for answer in answers),
        "preflight_sha256": value["preflight_sha256"], "runner_plan": value,
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
        "quality_status": "not_run", "native_status": "not_run", "tool_trace": trace, "transport": transport})
    assert result and not any(event.get("type") == "error" for event in events)
    sources = admitted_sources(trace)
    assert {source.url for source, _ in sources.values()} == set(urls)
    assert all(not source.truncated for source, _ in sources.values())
    target = workspace / "comparison.md"
    assert target.is_file() and not target.is_symlink()
    data = target.read_bytes()
    with (budget.EVIDENCE / f"{case}-comparison.md").open("xb") as handle:
        handle.write(data)
    manifests = []
    for path in artifact_store.root().glob("*.manifest.json"):
        item = json.loads(path.read_bytes())
        if item["title"] == "comparison.md":
            metadata, stored = artifact_store.read_owned(item["run_id"], item["filename"])
            manifests.append({"metadata": metadata, "bytes_match_workspace": stored == data})
    checks = {"links_saved": all(url in data.decode() for url in urls),
              "readback_succeeded": any(item["tool"] == "read_file" and item["result"].get("ok") for item in trace),
              "artifact_reopened": any(item["bytes_match_workspace"] for item in manifests)}
    persist(budget.EVIDENCE / f"{case}-artifact-review.json", {"sha256": hashlib.sha256(data).hexdigest(),
        "checks": checks, "manifests": manifests, "semantic_review": "not_run", "native_open": "not_run"})
    assert all(checks.values()), checks
