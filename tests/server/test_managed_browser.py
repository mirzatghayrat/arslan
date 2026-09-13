import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from server.api import browser as api
from server.services import managed_browser as browser, run_registry


async def test_preview_only_static_operations_renderer_sandbox_on(monkeypatch, tmp_path):
    import mcp
    import mcp.client.stdio
    calls, launched = [], []
    monkeypatch.setattr(browser, "status", lambda: {"ready": True})
    monkeypatch.setattr(browser, "runtime_root", lambda: tmp_path)
    (tmp_path / ".ready.json").write_text(json.dumps({"browser": "/fake/pinned-browser"}))
    monkeypatch.setattr(browser.spawn_env, "resolve_command", lambda name: "/fake/" + name)

    @asynccontextmanager
    async def transport(params):
        launched.append(params)
        cfg = json.loads(Path(params.args[params.args.index("--config") + 1]).read_text())
        options = cfg["browser"]["contextOptions"]
        assert options["javaScriptEnabled"] is False
        assert options["acceptDownloads"] is False and options["ignoreHTTPSErrors"] is False
        yield None, None

    class Client:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def initialize(self): pass
        async def call_tool(self, name, args):
            calls.append(name)
            if "filename" in args:
                Path(args["filename"]).write_text("Untrusted page text")
            return SimpleNamespace(isError=False)

    monkeypatch.setattr(mcp.client.stdio, "stdio_client", transport)
    monkeypatch.setattr(mcp, "ClientSession", Client)
    result = await browser.preview("https://example.com")
    assert result["scripts"] == "disabled" and result["text"] == "Untrusted page text"
    assert calls == ["browser_navigate", "browser_snapshot", "browser_take_screenshot"]
    args = launched[0].args
    assert "--sandbox" in args and "--no-sandbox" not in args
    assert "--isolated" in args and "--ignore-https-errors" not in args
    assert "ARSLAN_SECRET_KEY" not in launched[0].env
    assert "--storage-state" not in args and "--extension" not in args


async def test_visit_durable_idempotent_not_scored(execution_db, monkeypatch):
    from server.services import run_recorder
    scored = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", scored.append)
    monkeypatch.setattr(browser, "status", lambda: {"ready": True})

    async def preview(url):
        return {"url": url, "text": "synthetic snapshot", "blocked_connections": 0}

    monkeypatch.setattr(browser, "preview", preview)
    request = api.Visit(url="https://example.com", request_key="same-browser-request")
    first = await api.start_visit(request)
    await asyncio.gather(*list(api._tasks))
    assert first == await api.start_visit(request)
    saved = await api.get_visit(first["run_id"])
    assert saved["status"] == "completed" and saved["result"]["text"] == "synthetic snapshot"
    assert not scored
    with pytest.raises(HTTPException) as error:
        await api.start_visit(api.Visit(url="https://other.example", request_key=request.request_key))
    assert error.value.status_code == 409


async def test_visit_cancel_stops_browser_and_records_cancelled(execution_db, monkeypatch):
    monkeypatch.setattr(browser, "status", lambda: {"ready": True})
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def preview(url):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(browser, "preview", preview)
    reply = await api.start_visit(api.Visit(url="https://example.com", request_key="cancel-browser-request"))
    await entered.wait()
    assert run_registry.cancel(reply["run_id"])
    await asyncio.gather(*list(api._tasks))
    assert stopped.is_set()
    assert (await api.get_visit(reply["run_id"]))["status"] == "cancelled"


async def test_visit_failure_is_not_success(execution_db, monkeypatch):
    monkeypatch.setattr(browser, "status", lambda: {"ready": True})

    async def preview(url):
        raise RuntimeError("TLS certificate rejected")

    monkeypatch.setattr(browser, "preview", preview)
    reply = await api.start_visit(api.Visit(url="https://example.com", request_key="failed-browser-request"))
    await asyncio.gather(*list(api._tasks))
    saved = await api.get_visit(reply["run_id"])
    assert saved["status"] == "failed" and saved["result"] is None


def test_browser_manifest_exact_and_integrity_locked():
    manifest = json.loads((browser.manifests() / "package.json").read_text())
    lock = json.loads((browser.manifests() / "package-lock.json").read_text())
    assert manifest["dependencies"] == {"@playwright/mcp": browser.VERSION}
    assert all(item.get("integrity", "").startswith("sha512-")
               for path, item in lock["packages"].items() if path)
