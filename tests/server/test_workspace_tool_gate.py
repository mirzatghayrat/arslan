"""Which file tools Arslan is OFFERED (spec 2026-08-20 P1 §1.3, §3 判据 1).

No workspace → the file tools are not in the tool list AT ALL, rather than
present-and-erroring: a tool the model can see is a tool it will try, and a
capability that advertises itself then refuses is the self-knowledge defect
this project already paid for once.

P1a scope: only the T0 read-only trio is offered. The T1 writers exist as
executors but stay out of the tool list until their session-grant gate ships
(execute-closed: no gate, no execution surface).
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting

T0 = {"read_file", "list_dir", "search_files"}
T1 = {"write_file", "edit_file"}


async def _wire(tmp_path, monkeypatch, *, workspace: str | None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'gate.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    if workspace is not None:
        async with m() as s:
            s.add(Setting(key="workspace_dir", value=workspace))
            await s.commit()
    return engine


@pytest_asyncio.fixture
async def keys_without_workspace(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, workspace=None)
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


@pytest_asyncio.fixture
async def keys_with_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    engine = await _wire(tmp_path, monkeypatch, workspace=str(ws))
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


async def test_no_workspace_no_file_tools(keys_without_workspace):
    assert not (T0 | T1) & keys_without_workspace
    assert "web_search" in keys_without_workspace          # unrelated tools unaffected


async def test_a_workspace_pointing_nowhere_reads_as_unset(tmp_path, monkeypatch):
    """A stored path whose directory is gone (moved, unmounted, deleted) must
    read as unset — offering tools that cannot resolve anything is the same
    advertise-then-refuse defect as offering them with no workspace at all."""
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path / "does-not-exist"))
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert not (T0 | T1) & keys
    await engine.dispose()


async def test_a_workspace_pointing_at_a_file_reads_as_unset(tmp_path, monkeypatch):
    f = tmp_path / "not-a-dir.txt"
    f.write_text("x")
    engine = await _wire(tmp_path, monkeypatch, workspace=str(f))
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert not (T0 | T1) & keys
    await engine.dispose()


async def test_workspace_offers_the_readonly_trio(keys_with_workspace):
    assert T0 <= keys_with_workspace


async def test_writers_stay_out_until_their_gate_ships(keys_with_workspace):
    """P1a boundary, stated as a test so P1b has to change it deliberately."""
    assert not T1 & keys_with_workspace


async def test_offered_file_tools_have_descriptions(keys_with_workspace):
    from server.orchestrator.arslan import _arslan_tools
    tools = {t["key"]: t for t in await _arslan_tools()}
    for key in T0:
        assert tools[key].get("description"), key


# ── T2 whitelist extension (spec §1.4) ─────────────────────────────────────
READONLY_ADDITIONS = {"ls", "cat", "head", "tail", "wc", "grep", "find", "rg",
                      "file", "stat", "du", "df", "which", "uname", "date"}


def test_readonly_commands_are_whitelisted():
    from server.services import command_policy
    assert READONLY_ADDITIONS <= command_policy.ALLOWED_BINARIES


def test_dangerous_binaries_stay_out():
    """Interpreters and network fetchers would make the tiering meaningless."""
    from server.services import command_policy
    for banned in ("rm", "mv", "cp", "chmod", "curl", "wget", "ssh", "scp",
                   "python", "python3", "node", "sh", "bash", "zsh", "osascript"):
        assert banned not in command_policy.ALLOWED_BINARIES, banned


def test_every_whitelisted_binary_has_a_risk_grade():
    """Derived from the whitelist, never hand-enumerated (the SLOT_KEYS rule):
    a binary added without a grade must not silently inherit someone else's."""
    from server.services import command_policy
    for binary in command_policy.ALLOWED_BINARIES:
        grade = command_policy.classify(binary, [])
        assert grade in ("LOW", "MEDIUM", "HIGH"), binary


def test_readonly_additions_grade_low():
    from server.services import command_policy
    for binary in READONLY_ADDITIONS:
        assert command_policy.classify(binary, ["whatever"]) == "LOW", binary


def test_unknown_binary_still_fails_safe_high():
    from server.services import command_policy
    assert command_policy.classify("mkfs", []) == "HIGH"


def test_readonly_additions_still_pass_the_hard_deny_scan():
    from server.services import command_policy
    ok = command_policy.validate("grep", ["-rn", "needle", "."])
    assert ok["ok"] is True
    # …and the metacharacter scan still bites on the new binaries
    bad = command_policy.validate("grep", ["needle", ";", "rm -rf /"])
    assert bad["ok"] is False
