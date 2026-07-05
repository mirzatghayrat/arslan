"""Task 7: per-command seatbelt network profile + real cwd + proxy env for network git/gh."""
import pytest

from server.services import code_sandbox, command_sandbox


def test_net_profile_syntax():
    p = code_sandbox.net_profile(4321)
    assert "(deny network*)" in p
    # empirically-verified working seatbelt form (literal IP:port is REJECTED by sandbox-exec)
    assert '(allow network-outbound (remote tcp "localhost:4321"))' in p


def test_seatbelt_wrapper_uses_custom_profile():
    w = code_sandbox._seatbelt_wrapper(profile="CUSTOM")
    if w is None:
        pytest.skip("no seatbelt (non-macOS)")
    assert w == ["/usr/bin/sandbox-exec", "-p", "CUSTOM"]
    # default (no profile) still denies ALL network, no proxy hole
    default = code_sandbox._seatbelt_wrapper()
    assert "(deny network*)" in default[2] and "remote tcp" not in default[2]


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return b"out", b""


@pytest.mark.asyncio
async def test_run_command_network_path(monkeypatch, tmp_path):
    if code_sandbox._seatbelt_wrapper() is None:
        pytest.skip("no seatbelt")
    seen = {}

    async def _fake_exec(*cmd, cwd=None, env=None, **kw):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return _FakeProc()

    monkeypatch.setattr(command_sandbox.asyncio, "create_subprocess_exec", _fake_exec)
    out = await command_sandbox.run_command(
        "git", ["push"], proxy_port=4321, cwd=str(tmp_path),
        extra_env={"HTTPS_PROXY": "http://localhost:4321", "GIT_SSL_CAINFO": "/x/ca.crt"})
    assert out["ok"] is True
    # net profile (only localhost:4321) is in the seatbelt wrapper
    assert any(isinstance(a, str) and 'remote tcp "localhost:4321"' in a for a in seen["cmd"])
    # runs in the REAL repo, not the ephemeral tmp
    assert seen["cwd"] == str(tmp_path)
    # proxy + CA env injected; HOME still scrubbed (no ~/.ssh / ~/.gitconfig access)
    assert seen["env"]["HTTPS_PROXY"] == "http://localhost:4321"
    assert seen["env"]["GIT_SSL_CAINFO"] == "/x/ca.crt"
    assert seen["env"]["HOME"] != str(tmp_path)  # HOME is the scrubbed tmp, not the repo


@pytest.mark.asyncio
async def test_run_command_local_path_unchanged(monkeypatch):
    if code_sandbox._seatbelt_wrapper() is None:
        pytest.skip("no seatbelt")
    seen = {}

    async def _fake_exec(*cmd, cwd=None, env=None, **kw):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return _FakeProc()

    monkeypatch.setattr(command_sandbox.asyncio, "create_subprocess_exec", _fake_exec)
    await command_sandbox.run_command("git", ["status"])
    # default deny-all-network profile, no proxy allowance, ephemeral cwd, no proxy env
    assert any(isinstance(a, str) and "(deny network*)" in a and "remote tcp" not in a
               for a in seen["cmd"])
    assert seen["cwd"] == seen["env"]["HOME"]  # ephemeral tmp is both cwd and HOME
    assert "HTTPS_PROXY" not in seen["env"]
