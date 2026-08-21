"""The remote-execution gate (spec P3b §2.4, 裁决③).

Three things are being pinned, and only the first is shared with run_command:

  1. No confirm callback means no remote command. Same fail-closed shape as the
     other three gates.
  2. The refusal happens BEFORE anything touches the network. An unattended turn
     has no socket and therefore no callback, so a scheduled task must not even
     scan a host key on its way to being told no.
  3. Remote takes none of local's shortcuts — not the session allow-list, not
     ask_risky's LOW exemption, not "remember this one".
"""
import pytest

from server.orchestrator import tool_loop
from server.ws import arslan as ws_arslan
from server.ws import protocol
from server.registry import ssh_tools
from server.services import command_policy, ssh_exec

ARGS = {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]}


async def _resolve():
    return [{"key": "ssh_run", "description": "remote"},
            {"key": "ssh_probe", "description": "probe"}]


class _Stub:
    def __init__(self, log):
        self.log = log

    async def execute(self, args):
        self.log.append(args)
        return {"ok": True, "stdout": "ran"}


async def _dispatch(args, *, confirm=None):
    return await tool_loop._dispatch_tool(
        "ssh_run", args, "{}", resolve_tools=_resolve, emit=lambda e: None,
        tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=confirm)


@pytest.fixture(autouse=True)
def _clean_staging():
    ssh_exec.clear_staged()
    yield
    ssh_exec.clear_staged()


@pytest.fixture
def probe_succeeds(monkeypatch):
    """A host that answers, without touching a real network."""
    calls = []

    async def _probe(host):
        calls.append(host)
        return {"ok": True, "host": host, "keys": [f"{host} ssh-ed25519 AAAAKEY"],
                "fingerprints": ["256 SHA256:abc123 (ED25519)"]}

    monkeypatch.setattr(ssh_exec, "probe", _probe)
    return calls


async def test_refused_without_a_confirm_callback(monkeypatch, probe_succeeds):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub(log))
    r = await _dispatch(ARGS, confirm=None)
    assert r["ok"] is False
    assert "confirmation" in r["error"]
    assert log == []
    assert probe_succeeds == [], (
        "an unattended turn must be refused before it reaches out to the host")


async def test_declined_command_does_not_leave_the_host_approved(monkeypatch, probe_succeeds):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub(log))

    async def _deny(command, argv, **_kw):
        return False

    r = await _dispatch(ARGS, confirm=_deny)
    assert r["ok"] is False and "declined" in r["error"]
    assert log == []
    assert ssh_exec.take("192.168.1.8") is None, (
        "a declined command must not leave a staged key for the next call to consume")


async def test_approval_stages_the_scanned_key_for_exactly_one_run(monkeypatch, probe_succeeds):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub(log))
    seen = {}

    async def _allow(command, argv, **kw):
        seen.update(kw)
        seen["command"] = command
        seen["argv"] = list(argv)
        return True

    r = await _dispatch(ARGS, confirm=_allow)
    assert r["ok"] is True and log == [ARGS]
    # The card was told which machine and which key, not just which command.
    assert seen["remote_host"] == "someone@192.168.1.8"
    assert seen["fingerprints"] == ["256 SHA256:abc123 (ED25519)"]
    assert seen["command"] == "git" and seen["argv"] == ["status"]
    # The key the card showed is the key the run will pin to, and only once.
    assert ssh_exec.take("192.168.1.8") == ["192.168.1.8 ssh-ed25519 AAAAKEY"]
    assert ssh_exec.take("192.168.1.8") is None


async def test_a_command_we_would_refuse_is_never_put_on_a_card(monkeypatch, probe_succeeds):
    """Asking about something that cannot run teaches people the dialog is noise."""
    asked = []

    async def _allow(command, argv, **_kw):
        asked.append(command)
        return True

    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub([]))
    r = await _dispatch({**ARGS, "command": "curl", "argv": ["http://x"]}, confirm=_allow)
    assert r["ok"] is False
    assert asked == []
    assert probe_succeeds == [], "and it must not scan the host either"


async def test_an_unreachable_host_is_refused_rather_than_asked_about(monkeypatch):
    async def _probe(host):
        return {"ok": False, "error": "no SSH service answered on 192.168.1.8:22"}

    monkeypatch.setattr(ssh_exec, "probe", _probe)
    asked = []

    async def _allow(command, argv, **_kw):
        asked.append(command)
        return True

    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub([]))
    r = await _dispatch(ARGS, confirm=_allow)
    assert r["ok"] is False and "no SSH service" in r["error"]
    assert asked == [], "a card that cannot show a fingerprint cannot be answered honestly"


async def test_prepare_refuses_a_missing_username(probe_succeeds):
    r = await ssh_tools.prepare_confirmation({**ARGS, "user": ""})
    assert r["ok"] is False and "username" in r["error"]
    assert probe_succeeds == []


# ── the local whitelist was not quietly widened ────────────────────────────────

def test_ssh_is_still_refused_as_a_local_command():
    """Regression pin. P3b adds remote reach on its own road; if ssh ever appears
    in the local binary whitelist, `run_command` becomes arbitrary code execution
    and the entire LOW/MEDIUM/HIGH tiering stops meaning anything."""
    assert "ssh" not in command_policy.ALLOWED_BINARIES
    assert command_policy.validate("ssh", ["host", "ls"])["ok"] is False
    for binary in ("scp", "sftp", "curl", "wget"):
        assert command_policy.validate(binary, [])["ok"] is False, binary


# ── remote takes none of local's shortcuts (裁决③) ─────────────────────────────

def test_a_read_only_command_is_LOW_here_and_HIGH_over_there():
    """The same argv, graded differently by where it runs. `git status` is the
    honest test case: it is the command a user is most likely to think is
    harmless, and on someone else's machine we cannot know that."""
    assert ws_arslan.effective_risk(None, "git", ["status"]) == "LOW"
    assert ws_arslan.effective_risk("me@192.168.1.8", "git", ["status"]) == "HIGH"


def test_ask_risky_does_not_exempt_a_remote_read_only_command():
    local = dict(in_session_allow=False, policy="ask_risky", risk="LOW")
    assert ws_arslan.may_skip_card(None, **local) is True
    assert ws_arslan.may_skip_card("me@192.168.1.8", **local) is False


def test_the_session_allow_list_does_not_reach_across_the_network():
    both = dict(in_session_allow=True, policy="ask_all", risk="LOW")
    assert ws_arslan.may_skip_card(None, **both) is True
    assert ws_arslan.may_skip_card("me@192.168.1.8", **both) is False


def test_ask_all_still_shows_a_card_locally():
    assert ws_arslan.may_skip_card(
        None, in_session_allow=False, policy="ask_all", risk="LOW") is False


@pytest.mark.parametrize("risk", ["LOW", "MEDIUM", "HIGH"])
def test_dont_ask_again_is_never_honoured_for_a_remote_command(risk):
    """A remembered remote command would be a node that executes without a gate —
    exactly what the C4 ruling declined to build."""
    assert ws_arslan.may_remember("me@192.168.1.8", risk=risk, remember=True) is False


def test_dont_ask_again_still_works_locally_below_HIGH():
    assert ws_arslan.may_remember(None, risk="LOW", remember=True) is True
    assert ws_arslan.may_remember(None, risk="MEDIUM", remember=True) is True
    assert ws_arslan.may_remember(None, risk="HIGH", remember=True) is False
    assert ws_arslan.may_remember(None, risk="LOW", remember=False) is False


def test_the_card_frame_says_which_machine_and_which_key():
    local = protocol.propose_run_command("c1", "git", ["status"], reason="risk: LOW")
    assert "remote_host" not in local, "a local card must not imply another machine"

    remote = protocol.propose_run_command(
        "c2", "git", ["status"], reason="risk: HIGH",
        remote_host="me@192.168.1.8", fingerprints=["256 SHA256:abc (ED25519)"])
    assert remote["remote_host"] == "me@192.168.1.8"
    assert remote["fingerprints"] == ["256 SHA256:abc (ED25519)"]
