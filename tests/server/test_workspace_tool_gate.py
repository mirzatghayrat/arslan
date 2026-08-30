"""Which file tools Arslan is OFFERED (spec 2026-08-20 P1 §1.3, §3 判据 1).

Two drivers now (spec 2026-08-24 default-read): the READ trio is offered when
default_read is ON (the shipped default) OR a workspace is set; the WRITERS are
offered only when a workspace is set. "Not offered" still means absent from the
list, never present-and-erroring — a tool the model can see is one it will try.

P1b scope: the T0 trio plus the T1 writers, the latter gated by the session
grant. What is OFFERED still depends on a configured workspace; what is GATED
is tool_loop._WORKSPACE_WRITE_TOOLS. Both lists are pinned here so a writer
cannot quietly become ungated by leaving one of them.
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting

T0 = {"read_file", "list_dir", "search_files"}
T1 = {"write_file", "edit_file"}


async def _wire(tmp_path, monkeypatch, *, workspace: str | None,
                default_read: bool | None = None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'gate.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    # Redirect home so a default-read registration probe never scans the real
    # Desktop (green_roots uses Path.home()).
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr("server.services.workspace_paths._home",
                        lambda: tmp_path / "home")
    async with m() as s:
        if workspace is not None:
            s.add(Setting(key="workspace_dir", value=workspace))
        if default_read is not None:
            s.add(Setting(key="default_read_enabled",
                          value="true" if default_read else "false"))
        await s.commit()
    return engine


@pytest_asyncio.fixture
async def keys_no_ws_read_off(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, workspace=None, default_read=False)
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


@pytest_asyncio.fixture
async def keys_no_ws_read_on(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, workspace=None, default_read=True)
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


async def test_no_workspace_read_off_offers_no_file_tools(keys_no_ws_read_off):
    assert not (T0 | T1) & keys_no_ws_read_off
    assert "web_search" in keys_no_ws_read_off             # unrelated tools unaffected


async def test_no_workspace_read_on_offers_the_read_trio_but_no_writers(keys_no_ws_read_on):
    # The whole feature: a novice with no workspace can still read (green ring),
    # but cannot write until they configure one.
    assert T0 <= keys_no_ws_read_on
    assert not T1 & keys_no_ws_read_on


async def test_a_workspace_pointing_nowhere_reads_as_unset(tmp_path, monkeypatch):
    """A stored path whose directory is gone (moved, unmounted, deleted) must
    read as unset — offering tools that cannot resolve anything is the same
    advertise-then-refuse defect as offering them with no workspace at all."""
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path / "does-not-exist"))
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    # An invalid workspace withholds the WRITERS; reads still come from the green
    # ring (default on), which is the correct split — a broken write target must
    # not be writable, but it does not disable reading.
    assert not T1 & keys
    await engine.dispose()


async def test_a_workspace_pointing_at_a_file_reads_as_unset(tmp_path, monkeypatch):
    f = tmp_path / "not-a-dir.txt"
    f.write_text("x")
    engine = await _wire(tmp_path, monkeypatch, workspace=str(f))
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert not T1 & keys
    await engine.dispose()


async def test_workspace_offers_the_readonly_trio(keys_with_workspace):
    assert T0 <= keys_with_workspace


async def test_writers_are_offered_now_that_the_gate_exists(keys_with_workspace):
    """P1a withheld these until a gate existed; P1b ships the session grant
    (tool_loop._WORKSPACE_WRITE_TOOLS + the WS card), so they come out — the
    deliberate flip that P1a's version of this test demanded."""
    assert T1 <= keys_with_workspace


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


async def test_every_offered_writer_is_gated(keys_with_workspace):
    """The two lists must agree: a tool offered as a writer but missing from
    the gate set would execute unconfirmed — the failure mode this pairing
    exists to make impossible."""
    from server.orchestrator.tool_loop import _WORKSPACE_WRITE_TOOLS
    offered_writers = T1 & keys_with_workspace
    assert offered_writers <= _WORKSPACE_WRITE_TOOLS
    assert _WORKSPACE_WRITE_TOOLS == T1
