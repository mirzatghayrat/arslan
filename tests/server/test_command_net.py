"""Task 8: host-side network-command orchestration — pre-flight gates + proxy + sandboxed run,
with the real token confined to the proxy (never the sandbox env)."""
import pytest

from server.services import command_net


async def _aw(v):
    return v


@pytest.mark.asyncio
async def test_refuses_non_allowlisted_host(monkeypatch):
    monkeypatch.setattr(command_net, "_git_remotes", lambda ws: _aw({}))
    monkeypatch.setattr(command_net, "_current_branch", lambda ws: _aw("main"))
    started = []
    monkeypatch.setattr(command_net.command_proxy, "start_proxy", lambda **k: started.append(k) or _aw(None))
    out = await command_net.run_network_command("git", ["clone", "https://evil.com/x.git"])
    assert out["ok"] is False and "白名单" in out["error"]
    assert not started  # refused before any proxy spun up


@pytest.mark.asyncio
async def test_refuses_push_to_other_branch(monkeypatch):
    monkeypatch.setattr(command_net, "_git_remotes", lambda ws: _aw({"origin": "https://github.com/me/r.git"}))
    monkeypatch.setattr(command_net, "_current_branch", lambda ws: _aw("main"))
    started = []
    monkeypatch.setattr(command_net.command_proxy, "start_proxy", lambda **k: started.append(k) or _aw(None))
    out = await command_net.run_network_command("git", ["push", "origin", "other"])
    assert out["ok"] is False and "当前分支" in out["error"]
    assert not started


@pytest.mark.asyncio
async def test_spins_proxy_and_confines_token(monkeypatch, tmp_path):
    monkeypatch.setattr(command_net, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(command_net, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(command_net, "_git_remotes", lambda ws: _aw({"origin": "https://github.com/me/r.git"}))
    monkeypatch.setattr(command_net, "_current_branch", lambda ws: _aw("main"))
    monkeypatch.setattr(command_net, "_github_token", lambda: _aw("REALTOKEN"))

    class _Proxy:
        port = 5555

        async def close(self):
            pass

    seen = {}

    async def _fake_start(**k):
        seen["start"] = k
        return _Proxy()

    async def _fake_run(command, argv, **kw):
        seen["run"] = kw
        return {"ok": True, "stdout": "refs"}

    monkeypatch.setattr(command_net.command_proxy, "start_proxy", _fake_start)
    monkeypatch.setattr(command_net.command_sandbox, "run_command", _fake_run)

    out = await command_net.run_network_command("git", ["push"])
    assert out["ok"] is True
    # proxy seeded with the repo's remote host + the REAL token
    assert seen["start"]["inject_token"] == "REALTOKEN"
    assert "github.com" in seen["start"]["allow_hosts"]
    # run_command got proxy_port + workspace cwd + proxy env; the REAL token is NOT in the sandbox env
    assert seen["run"]["proxy_port"] == 5555
    assert seen["run"]["cwd"] == str(tmp_path)
    assert seen["run"]["extra_env"]["HTTPS_PROXY"] == "http://127.0.0.1:5555"
    assert "REALTOKEN" not in str(seen["run"]["extra_env"])
