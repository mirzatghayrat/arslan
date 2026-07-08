import pytest
from server.mcp import session as sess


class _FakeTool:
    def __init__(self, name, desc, schema): self.name, self.description, self.inputSchema = name, desc, schema


class _FakeListResult:
    def __init__(self, tools): self.tools = tools


class _FakeText:
    def __init__(self, text): self.type, self.text = "text", text


class _FakeCallResult:
    def __init__(self, content, isError=False): self.content, self.isError = content, isError


class _FakeSession:
    def __init__(self):
        self.closed_calls = 0
        self.calls = []
    async def list_tools(self): return _FakeListResult([_FakeTool("read_file", "Read a file", {"type": "object"})])
    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return _FakeCallResult([_FakeText("hello")])


class _FakeStack:
    def __init__(self): self.closed = False
    async def aclose(self): self.closed = True


def _server(sid=1): return {"id": sid, "command": "x", "args": [], "env": {}}


async def test_get_session_lazy_and_cached(monkeypatch):
    mgr = sess.MCPSessionManager()
    opened = []
    async def fake_open(server):
        opened.append(server["id"])
        return _FakeSession(), _FakeStack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    s1 = await mgr.get_session(_server(1))
    s2 = await mgr.get_session(_server(1))
    assert s1 is s2 and opened == [1]          # opened once, cached


async def test_list_and_call_use_session(monkeypatch):
    mgr = sess.MCPSessionManager()
    fake = _FakeSession()
    async def fake_open(server): return fake, _FakeStack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    lst = await mgr.list_tools(_server())
    assert lst.tools[0].name == "read_file"
    res = await mgr.call_tool(_server(), "read_file", {"path": "/a"})
    assert fake.calls == [("read_file", {"path": "/a"})]
    assert res.content[0].text == "hello"


async def test_call_failure_drops_cached_session(monkeypatch):
    mgr = sess.MCPSessionManager()
    stacks = []
    class _BoomSession(_FakeSession):
        async def call_tool(self, name, arguments): raise RuntimeError("pipe broke")
    async def fake_open(server):
        st = _FakeStack()
        stacks.append(st)
        return _BoomSession(), st
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    with pytest.raises(RuntimeError):
        await mgr.call_tool(_server(5), "x", {})
    assert stacks[0].closed is True             # dropped on failure
    assert 5 not in mgr._sessions               # cache cleared → next call relaunches


async def test_aclose_all(monkeypatch):
    mgr = sess.MCPSessionManager()
    st = _FakeStack()
    async def fake_open(server): return _FakeSession(), st
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    await mgr.get_session(_server(9))
    await mgr.aclose_all()
    assert st.closed is True and mgr._sessions == {}
