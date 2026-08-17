"""PB-1: dynamic proxy resolution chain for MCP stdio children.

Chain (first hit wins): server.env explicit > backend os.environ > macOS scutil --proxy > none.
"""
import subprocess

from server.mcp import proxy_resolve
from server.mcp import session as sess

_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")

# Real `scutil --proxy` output captured 2026-07-09 on the dev host (proxy on 127.0.0.1:7899).
REAL_SCUTIL_OUTPUT = """<dictionary> {
  ExceptionsList : <array> {
    0 : 192.168.0.0/16
    1 : 10.0.0.0/8
    2 : 172.16.0.0/12
    3 : 127.0.0.1
    4 : localhost
    5 : *.local
    6 : timestamp.apple.com
    7 : sequoia.apple.com
    8 : seed-sequoia.siri.apple.com
  }
  ExcludeSimpleHostnames : 0
  HTTPEnable : 1
  HTTPPort : 7899
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7899
  HTTPSProxy : 127.0.0.1
  ProxyAutoConfigEnable : 0
  SOCKSEnable : 1
  SOCKSPort : 7899
  SOCKSProxy : 127.0.0.1
}
"""

DISABLED_SCUTIL_OUTPUT = """<dictionary> {
  HTTPEnable : 0
  HTTPSEnable : 0
  ProxyAutoConfigEnable : 0
}
"""


def _clear_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- chain order

def test_server_env_short_circuits(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", lambda: {"HTTPS_PROXY": "http://x:1"})
    additions, source = proxy_resolve.resolve_proxy({"HTTPS_PROXY": "http://127.0.0.1:9999"})
    assert (additions, source) == ({}, "server_env")


def test_server_env_lowercase_recognized(monkeypatch):
    _clear_env(monkeypatch)
    additions, source = proxy_resolve.resolve_proxy({"https_proxy": "http://127.0.0.1:9999"})
    assert (additions, source) == ({}, "server_env")


def test_os_environ_hit(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", lambda: {"HTTPS_PROXY": "http://x:1"})
    additions, source = proxy_resolve.resolve_proxy({})
    assert (additions, source) == ({}, "os_environ")   # inheritance via **os.environ carries it


def test_os_environ_lowercase_hit(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:8888")
    additions, source = proxy_resolve.resolve_proxy({})
    assert (additions, source) == ({}, "os_environ")


def test_scutil_hit(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(
        proxy_resolve, "_scutil_proxy",
        lambda: {"HTTPS_PROXY": "http://127.0.0.1:7899", "HTTP_PROXY": "http://127.0.0.1:7899"},
    )
    additions, source = proxy_resolve.resolve_proxy({})
    assert source == "scutil"
    assert additions == {"HTTPS_PROXY": "http://127.0.0.1:7899", "HTTP_PROXY": "http://127.0.0.1:7899"}


def test_none_when_nothing_found(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", lambda: {})
    assert proxy_resolve.resolve_proxy({}) == ({}, "none")


# ---------------------------------------------------------------- scutil parser

def test_parse_real_scutil_output():
    assert proxy_resolve._parse_scutil(REAL_SCUTIL_OUTPUT) == {
        "HTTP_PROXY": "http://127.0.0.1:7899",
        "HTTPS_PROXY": "http://127.0.0.1:7899",
    }


def test_parse_disabled_scutil_output():
    assert proxy_resolve._parse_scutil(DISABLED_SCUTIL_OUTPUT) == {}


def test_scutil_timeout_fails_open(monkeypatch):
    _clear_env(monkeypatch)
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="scutil", timeout=2.0)
    monkeypatch.setattr(proxy_resolve.subprocess, "run", boom)
    assert proxy_resolve._scutil_proxy() == {}
    assert proxy_resolve.resolve_proxy({}) == ({}, "none")


def test_scutil_missing_fails_open(monkeypatch):
    _clear_env(monkeypatch)
    def boom(*a, **kw):
        raise FileNotFoundError("scutil")
    monkeypatch.setattr(proxy_resolve.subprocess, "run", boom)
    assert proxy_resolve.resolve_proxy({}) == ({}, "none")


# ---------------------------------------------------------------- session wiring

class _AsyncCM:
    def __init__(self, value): self._v = value
    async def __aenter__(self): return self._v
    async def __aexit__(self, *a): return False


class _FakeClient:
    def __init__(self, read, write): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def initialize(self): pass


async def test_stdio_env_injects_scutil_proxy(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(
        proxy_resolve, "_scutil_proxy",
        lambda: {"HTTPS_PROXY": "http://127.0.0.1:7899", "HTTP_PROXY": "http://127.0.0.1:7899"},
    )
    captured = {}

    class _Params:
        def __init__(self, command, args, env):
            captured["env"] = env

    monkeypatch.setattr("mcp.StdioServerParameters", _Params)
    monkeypatch.setattr("mcp.client.stdio.stdio_client", lambda params: _AsyncCM(("r", "w")))
    monkeypatch.setattr("mcp.ClientSession", _FakeClient)

    mgr = sess.MCPSessionManager()
    server = {"id": 7, "label": "fetch", "command": "uvx", "args": ["mcp-server-fetch"], "env": {}}
    await mgr.get_session(server)
    assert captured["env"]["HTTPS_PROXY"] == "http://127.0.0.1:7899"
    assert captured["env"]["HTTP_PROXY"] == "http://127.0.0.1:7899"
    assert mgr.proxy_source(7) == "scutil"
    await mgr.aclose_all()


async def test_stdio_server_env_stays_highest_precedence(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", lambda: {"HTTPS_PROXY": "http://x:1"})
    captured = {}

    class _Params:
        def __init__(self, command, args, env):
            captured["env"] = env

    monkeypatch.setattr("mcp.StdioServerParameters", _Params)
    monkeypatch.setattr("mcp.client.stdio.stdio_client", lambda params: _AsyncCM(("r", "w")))
    monkeypatch.setattr("mcp.ClientSession", _FakeClient)

    mgr = sess.MCPSessionManager()
    monkeypatch.setattr("server.mcp.spawn_env.login_shell_path", lambda: "")
    # An explicit path skips PATH resolution (spawn_env passthrough contract).
    server = {"id": 8, "command": "/opt/fake/x", "args": [], "env": {"HTTPS_PROXY": "http://127.0.0.1:5555"}}
    await mgr.get_session(server)
    assert captured["env"]["HTTPS_PROXY"] == "http://127.0.0.1:5555"   # explicit config wins
    assert mgr.proxy_source(8) == "server_env"
    await mgr.aclose_all()


def test_proxy_source_unknown_server():
    assert sess.MCPSessionManager().proxy_source(999) is None
