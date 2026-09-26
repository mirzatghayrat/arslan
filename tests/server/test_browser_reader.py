import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.browser import router
from server.services import browser_reader as reader


@pytest.fixture(autouse=True)
async def cleanup_sessions():
    await reader.shutdown()
    yield
    await reader.shutdown()


@pytest.mark.parametrize("body", [
    {"action": "click", "x": 5, "y": 5}, {"action": "type", "text": "secret"},
    {"action": "navigate", "url": "file:///etc/passwd"}, {"action": "navigate", "url": "https://user:pass@example.com"},
    {"action": "navigate", "url": "https://example.com", "headers": {"Authorization": "fake"}},
    {"action": "link", "link_id": "link-1"}, {"action": "scroll", "direction": 1000},
    {"action": "refresh", "url": "https://example.com"}, {"action": "evaluate", "script": "read secrets"},
])
def test_only_bounded_navigation_contract(body):
    with pytest.raises(ValueError):
        reader.ReaderAction.model_validate(body)


class FakeProcess:
    pid = 99999999
    returncode = None
    def __init__(self):
        self.lines = asyncio.Queue()
        self.lines.put_nowait(b'{"ready":true}\n')
        self.stdout = self
        self.stdin = self
        self.requests = []
    async def readline(self):
        return await self.lines.get()
    def write(self, data):
        self.requests.append(json.loads(data))
        self.lines.put_nowait(b'{"ok":true,"revision":1,"url":"https://example.com"}\n')
    async def drain(self):
        pass
    def send_signal(self, value):
        self.returncode = 0
    async def wait(self):
        return self.returncode


async def fake_runtime(monkeypatch, tmp_path):
    calls, process = [], FakeProcess()
    async def launch(*args, **kwargs):
        calls.append((args, kwargs))
        return process
    async def descendants(pid):
        return []
    monkeypatch.setattr(reader.managed_browser, "status", lambda: {"ready": True})
    monkeypatch.setattr(reader.managed_browser, "runtime_root", lambda: tmp_path)
    monkeypatch.setattr(reader.managed_browser, "_browser_executable", lambda root: root / "browser")
    monkeypatch.setattr(reader.spawn_env, "resolve_command", lambda name: "/usr/bin/node")
    monkeypatch.setattr(reader.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(reader, "_descendants", descendants)
    return calls, process


async def test_session_uses_scrubbed_env_public_proxy_and_ephemeral_cleanup(monkeypatch, tmp_path):
    calls, process = await fake_runtime(monkeypatch, tmp_path)
    session = await reader.create("conversation", None)
    temp = session.temp.name
    result = await session.act(reader.ReaderAction(action="navigate", url="https://example.com"))
    assert result["conversation_id"] == "conversation" and result["task_id"] is None
    assert set(calls[0][1]["env"]) == {"PATH", "HOME", "TMPDIR"}
    assert calls[0][1]["env"]["HOME"] == temp
    assert calls[0][0][-1].startswith("http://127.0.0.1:")
    assert process.requests == [{"action": "navigate", "url": "https://example.com"}]
    await session.close()
    from pathlib import Path
    assert session.closed and process.returncode == 0 and not Path(temp).exists()
    with pytest.raises(reader.ReaderError, match="session_closed"):
        await session.act(reader.ReaderAction(action="refresh"))


async def test_operation_budget_closes_session(monkeypatch, tmp_path):
    await fake_runtime(monkeypatch, tmp_path)
    session = await reader.create("conversation", None)
    session.operations = 100
    with pytest.raises(reader.ReaderError, match="session_expired"):
        await session.act(reader.ReaderAction(action="refresh"))
    assert session.closed


async def test_close_is_idempotent_under_concurrent_requests(monkeypatch, tmp_path):
    await fake_runtime(monkeypatch, tmp_path)
    session = await reader.create("conversation", None)
    await asyncio.gather(session.close(), session.close())
    assert session.closed and session.proxy is None and session.temp is None


async def test_task_cancellation_closes_only_owned_sessions():
    async def close_one():
        first.closed = True
    first = SimpleNamespace(task_id="task-one", close=close_one, closed=False)
    async def close_two():
        second.closed = True
    second = SimpleNamespace(task_id="task-two", close=close_two, closed=False)
    reader.sessions.update(one=first, two=second)
    await reader.cancel_task("task-one")
    assert first.closed and not second.closed and "one" not in reader.sessions


async def test_api_auth_task_binding_and_no_raw_actions(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-reader-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/browser/sessions", json={"conversation_id": "c"})).status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-reader-token"
        response = await client.post("/api/v1/browser/sessions", json={"conversation_id": "c", "task_id": "other-owner-task"})
        assert response.status_code == 404
        response = await client.post("/api/v1/browser/sessions/missing/actions", json={"action": "type", "text": "secret"})
        assert response.status_code == 422
        response = await client.post("/api/v1/browser/sessions/missing/actions", json={"action": "refresh"})
        assert response.status_code == 404
