"""Enrolled machines (spec P3c).

The ruling this file exists to hold in place: enrolment saves re-verifying a
fingerprint and NOTHING else. Every command on an enrolled machine still asks.
The switch that would remove that gate is the one the user declined, because it
completes the shape both arXiv analyses of OpenClaw describe — a persistent
node plus unattended execution.

The other half is the pin. Enrolment without pinning would be trust-on-first-use
happening silently forever; with it, a machine that no longer presents the
enrolled key is refused rather than offered as a card to click through.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting, SshAudit
from server.orchestrator import tool_loop
from server.registry import ssh_tools
from server.services import ssh_exec, ssh_nodes

KEY_A = "192.168.1.8 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
KEY_B = "192.168.1.8 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
FP_A = "256 SHA256:aaaa (ED25519)"
FP_B = "256 SHA256:bbbb (ED25519)"


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'nodes.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(Setting(key="ssh_enabled", value="true"))
        await s.commit()
    yield m
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_staging():
    ssh_exec.clear_staged()
    yield
    ssh_exec.clear_staged()


async def _enroll(maker, *, name="studio", keys=(KEY_A,), fps=(FP_A,)):
    async with maker() as s:
        return await ssh_nodes.enroll(s, name=name, host="192.168.1.8", username="someone",
                                      host_keys=list(keys), fingerprints=list(fps))


# ── the pin ────────────────────────────────────────────────────────────────────

async def test_the_same_machine_still_matches(maker):
    node = await _enroll(maker)
    assert ssh_nodes.key_matches(node, [KEY_A]) is True


async def test_a_different_key_does_not_match(maker):
    node = await _enroll(maker)
    assert ssh_nodes.key_matches(node, [KEY_B]) is False


async def test_the_order_keys_arrive_in_does_not_decide_the_answer(maker):
    """ssh-keyscan does not promise an order. A comparison that depended on one
    would fire the changed-key warning at random, and a warning that cries wolf
    is worse than no warning — people learn to re-enrol past it, which is exactly
    the click-through this pin exists to prevent."""
    rsa = "192.168.1.8 ssh-rsa AAAAB3NzaC1yc2EAAAA"
    node = await _enroll(maker, keys=(KEY_A, rsa))
    assert ssh_nodes.key_matches(node, [rsa, KEY_A]) is True
    assert ssh_nodes.key_matches(node, [rsa]) is True


async def test_extra_key_types_do_not_break_the_match(maker):
    """A host answering with more types than were captured at enrolment is the
    same host; requiring set equality would fail on an ordinary sshd config
    change."""
    node = await _enroll(maker)
    assert ssh_nodes.key_matches(node, [KEY_A, "192.168.1.8 ssh-rsa AAAAB3Nz"]) is True


async def test_no_keys_at_all_is_not_a_match(maker):
    node = await _enroll(maker)
    assert ssh_nodes.key_matches(node, []) is False


# ── what enrolment changes, and what it must not ───────────────────────────────

async def test_an_enrolled_machine_still_produces_a_card(maker, monkeypatch):
    """The ruling, as a test. If this ever passes without asking, the product has
    become the thing we said we would not build."""
    await _enroll(maker)

    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY_A], "fingerprints": [FP_A]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)

    asked = []

    async def _confirm(command, argv, **kw):
        asked.append(kw)
        return True

    class _Stub:
        async def execute(self, args):
            return {"ok": True}

    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", _Stub())
    r = await tool_loop._dispatch_tool(
        "ssh_run", {"host": "192.168.1.8", "user": "someone", "command": "git",
                    "argv": ["status"]},
        "{}", resolve_tools=lambda: _one_tool(), emit=lambda e: None, tool_timeout_s=5,
        tool_trace=[], convo=[], confirm_command=_confirm)
    assert r["ok"] is True
    assert len(asked) == 1, "an enrolled machine must still ask, every time"
    assert "studio" in asked[0]["remote_host"], (
        "the card should call the machine what the user calls it")
    assert "192.168.1.8" in asked[0]["remote_host"], (
        "and still show the address, so the name cannot quietly point elsewhere")


async def _one_tool():
    return [{"key": "ssh_run", "description": "remote"}]


async def test_enrolment_carries_the_name_onto_the_card(maker, monkeypatch):
    await _enroll(maker, name="studio")

    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY_A], "fingerprints": [FP_A]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)

    prep = await ssh_tools.prepare_confirmation(
        {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]})
    assert prep["ok"] is True
    assert prep["node_name"] == "studio"


async def test_an_unenrolled_host_has_no_name(maker, monkeypatch):
    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY_A], "fingerprints": [FP_A]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)
    prep = await ssh_tools.prepare_confirmation(
        {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]})
    assert prep["ok"] is True and prep["node_name"] is None


async def test_a_changed_host_key_is_refused_not_offered(maker, monkeypatch):
    """Not a card. The whole reason to pin a key is to produce this one signal,
    and putting an approve button beside it turns the warning into a formality."""
    await _enroll(maker, name="studio")

    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY_B], "fingerprints": [FP_B]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)

    asked = []

    async def _confirm(command, argv, **kw):
        asked.append(kw)
        return True

    class _Stub:
        def __init__(self):
            self.ran = False

        async def execute(self, args):
            self.ran = True
            return {"ok": True}

    stub = _Stub()
    monkeypatch.setitem(tool_loop.EXECUTORS, "ssh_run", stub)
    r = await tool_loop._dispatch_tool(
        "ssh_run", {"host": "192.168.1.8", "user": "someone", "command": "git",
                    "argv": ["status"]},
        "{}", resolve_tools=lambda: _one_tool(), emit=lambda e: None, tool_timeout_s=5,
        tool_trace=[], convo=[], confirm_command=_confirm)
    assert r["ok"] is False
    assert "CHANGED" in r["error"]
    assert asked == [], "a changed key must never reach a confirmation card"
    assert stub.ran is False
    assert ssh_exec.take("192.168.1.8") is None, "and nothing may be staged"


# ── revocation ─────────────────────────────────────────────────────────────────

async def test_revoking_removes_the_machine(maker):
    node = await _enroll(maker)
    async with maker() as s:
        assert await ssh_nodes.revoke(s, node.id) is True
    async with maker() as s:
        assert await ssh_nodes.list_nodes(s) == []


async def test_revoking_keeps_the_ssh_identity(maker, monkeypatch):
    """The identity is one keypair shared by every machine. Deleting it to revoke
    one would break all the others, and the user would find out by having things
    silently stop working."""
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")
    from server.services import ssh_keys
    node = await _enroll(maker)
    async with maker() as s:
        public = await ssh_keys.ensure_keypair(s)
        await ssh_nodes.revoke(s, node.id)
    async with maker() as s:
        assert await ssh_keys.public_key(s) == public


async def test_revoking_keeps_the_history_of_what_was_run(maker):
    """node_id is not a foreign key precisely so this holds: forgetting a machine
    must not erase the record of what was done to it."""
    node = await _enroll(maker)
    async with maker() as s:
        await ssh_nodes.record(s, host="192.168.1.8", username="someone",
                               command="git", argv=["status"],
                               result={"ok": True, "exit_code": 0}, node=node)
        await ssh_nodes.revoke(s, node.id)
    async with maker() as s:
        rows = await ssh_nodes.recent(s)
    assert len(rows) == 1
    assert rows[0].node_name == "studio" and rows[0].host == "192.168.1.8"


# ── the audit ──────────────────────────────────────────────────────────────────

async def test_a_failed_remote_command_is_recorded_too(maker):
    """An audit that only holds successes answers a question nobody asked."""
    async with maker() as s:
        await ssh_nodes.record(s, host="192.168.1.8", username="someone",
                               command="git", argv=["status"],
                               result={"ok": False, "exit_code": 128,
                                       "error": "permission denied"})
    async with maker() as s:
        rows = await ssh_nodes.recent(s)
    assert len(rows) == 1
    assert rows[0].ok is False and rows[0].exit_code == 128
    assert "permission denied" in rows[0].error


async def test_the_audit_row_holds_the_arguments_not_just_the_binary(maker):
    async with maker() as s:
        await ssh_nodes.record(s, host="192.168.1.8", username="someone",
                               command="git", argv=["push", "--force"],
                               result={"ok": True, "exit_code": 0})
        rows = await ssh_nodes.recent(s)
    assert "--force" in rows[0].command, (
        "'git' alone would not tell anyone what happened on that machine")


async def test_running_a_command_writes_an_audit_row(maker, monkeypatch):
    """Through the real executor, not by calling record() directly — the point is
    that the write happens on the path a command actually takes."""
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")
    from server.services import ssh_keys
    async with maker() as s:
        await ssh_keys.ensure_keypair(s)

    async def _run(host, user, command, argv, *, private_pem, **kw):
        return {"ok": True, "exit_code": 0, "stdout": "clean", "host": host}
    monkeypatch.setattr(ssh_exec, "run", _run)

    from server.registry.executors import EXECUTORS
    r = await EXECUTORS["ssh_run"].execute(
        {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]})
    assert r["ok"] is True
    async with maker() as s:
        rows = await ssh_nodes.recent(s)
    assert len(rows) == 1 and rows[0].host == "192.168.1.8"


async def test_a_refused_command_is_recorded_rather_than_lost(maker, monkeypatch):
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")
    from server.services import ssh_keys
    async with maker() as s:
        await ssh_keys.ensure_keypair(s)

    async def _run(host, user, command, argv, *, private_pem, **kw):
        return {"ok": False, "error": "no confirmed host key for 192.168.1.8"}
    monkeypatch.setattr(ssh_exec, "run", _run)

    from server.registry.executors import EXECUTORS
    await EXECUTORS["ssh_run"].execute(
        {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]})
    async with maker() as s:
        rows = await ssh_nodes.recent(s)
    assert len(rows) == 1 and rows[0].ok is False


async def test_the_audit_is_not_the_turn_journal(maker):
    """Why this table exists at all. `ssh_run` is an Arslan-level tool and the
    answer path produces no Run row, so the tool trace it leaves behind lives in
    an in-memory journal that is dropped when the turn ends. Durability is the
    feature; a fresh session must still be able to read what happened."""
    async with maker() as s:
        await ssh_nodes.record(s, host="192.168.1.8", username="someone",
                               command="rm-nothing", result={"ok": True, "exit_code": 0})
    # A completely new session object — nothing in-process is carrying this.
    async with maker() as s2:
        rows = (await s2.execute(__import__("sqlalchemy").select(SshAudit))).scalars().all()
    assert len(rows) == 1


async def test_an_enrolled_machine_is_pinned_to_the_key_it_was_enrolled_with(maker, monkeypatch):
    """The subtle one. A host that presents the enrolled key AND an extra key
    passes the match — correctly, since sshd configs change. But what ssh is then
    pinned to must be the ENROLLED key, not the live set: staging what the host
    just offered would hand ssh a key nobody ever approved, and the pin would be
    doing nothing.
    """
    await _enroll(maker, name="studio", keys=(KEY_A,), fps=(FP_A,))
    rogue = "192.168.1.8 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"

    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY_A, rogue],
                "fingerprints": [FP_A, "256 SHA256:cccc (ED25519)"]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)

    prep = await ssh_tools.prepare_confirmation(
        {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]})
    assert prep["ok"] is True
    staged = ssh_exec.take("192.168.1.8")
    assert staged == [KEY_A], f"ssh must be pinned to the enrolled key only, got {staged}"
    assert rogue not in (staged or [])
