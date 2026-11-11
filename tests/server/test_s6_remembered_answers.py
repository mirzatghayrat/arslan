"""S6 (v0.1.64): the "Remembered answers" page's server half.

- The old command rules (`legacy_rule`, and the `terminal_always_allow` list they were copied from) are deleted by
  migration 0092, and nothing writes one again: the Inbox's "Always allow" on an old ledger row refuses a set that
  names one, and a card cannot store one.
- `GET /permissions/grants` lists every "in this conversation" grant with what the page shows for it (`what`, a
  readable `name`, the commander's block for a sub-session), and leaves out a deleted conversation's.
- Taking one back here makes the next same step ask again, through the real tool loop.
"""
from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage, MCPServer, PermissionRule
from server.mcp.discovery import mcp_tool_key
from server.orchestrator import command_gate, tool_loop
from server.services import (approvals, command_confirm, command_sandbox, permission_store, permissions,
                             settings_service, sub_sessions, terminal_exec, terminal_policy)
from tests.server.test_proactive_api import client  # noqa: F401 — the whole app, for the removed route


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    permission_store._reset_for_tests()
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()


@pytest.fixture
async def api(execution_db, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI

    from server import auth
    from server.api.approvals import router as approvals_router
    from server.api.permissions import router
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-s6-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-s6-token"}) as http:
        yield http


class _Asker:
    """A card surface that records every card and answers each by the asking Mac window."""

    def __init__(self, scope="conversation"):
        self.frames: list[dict] = []
        self.scope = scope

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": True, "scope": self.scope, "note": "", "by": "mac", "call_id": frame["call_id"]}


class _Exec:
    key = "run_command"

    def __init__(self):
        self.outside: list[bool] = []

    async def execute(self, args):
        self.outside.append(terminal_exec.OUTSIDE_SANDBOX.get())
        return {"ok": True, "exit_code": 0, "stdout": "done", "stderr": "", "sandbox": "workspace"}


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _run(monkeypatch, command: str, asker: _Asker, cid: str = "c1"):
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Exec())
    with permissions.asking_with(asker):
        return await tool_loop._dispatch_tool(
            "run_command", {"command": command}, "{}", resolve_tools=_resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=command_confirm.Confirmations(cid).command,
            conversation_id=cid)


def _toggles(monkeypatch, *, sandbox: bool, ask_all: bool):
    async def sandbox_on():
        return sandbox

    async def asks_all():
        return ask_all

    async def policy(db):
        return "ask_all" if ask_all else "ask_risky"
    monkeypatch.setattr(command_gate, "_sandbox_enabled", sandbox_on)
    monkeypatch.setattr(command_gate, "_asks_for_everything", asks_all)
    monkeypatch.setattr(settings_service, "shell_confirm_policy", policy)


async def _grants(api) -> list[dict]:
    response = await api.get("/api/v1/permissions/grants")
    assert response.status_code == 200
    return response.json()


# ── migration 0092 ───────────────────────────────────────────────────────────

def _old_database(path):
    from server.db.migrations.versions import _0067_permissions as m0067
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO settings VALUES ('terminal_always_allow', '[\"delete\", \"git-push\"]')")
        conn.exec_driver_sql("INSERT INTO settings VALUES ('language', 'zh')")
        m0067.upgrade_sync(conn)                     # copies the old list as two legacy_rule rows
        conn.exec_driver_sql("INSERT INTO permission_rules (kind, target, label, created_from, created_at, use_count) "
                             "VALUES ('app', 'com.apple.Notes', 'Notes', 'card', '2026-11-01 10:00:00', 3)")
        conn.exec_driver_sql("INSERT INTO permission_grants (conversation_id, task_id, kind, target, call_id, "
                             "created_at) VALUES ('c1', '', 'outside', '*', 'card-1', '2026-11-01 10:00:00')")
    return engine


def test_migration_0092_deletes_the_old_command_rules_and_leaves_the_rest(tmp_path):
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    engine = _old_database(tmp_path / "old.db")
    with engine.begin() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM permission_rules WHERE kind = 'legacy_rule'").scalar() == 2
        m0092.upgrade_sync(conn)
        m0092.upgrade_sync(conn)                     # a re-run finds nothing more to do
        rules = conn.exec_driver_sql("SELECT kind, target, use_count FROM permission_rules").fetchall()
        settings = conn.exec_driver_sql("SELECT key, value FROM settings").fetchall()
        grants = conn.exec_driver_sql("SELECT conversation_id, kind FROM permission_grants").fetchall()
    assert rules == [("app", "com.apple.Notes", 3)]
    assert settings == [("language", "zh")]
    assert grants == [("c1", "outside")]


def test_migration_0092_runs_on_a_database_with_nothing_stored(tmp_path):
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    with engine.begin() as conn:
        m0092.upgrade_sync(conn)
        assert conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_migration_0092_is_in_the_runner():
    from server.db.migrations import runner
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    assert ("0092", m0092.upgrade_sync) in runner.MIGRATIONS


# ── 0092 also deletes the grants no request reads (the user's decision, after #836's review) ──

#: One live grant of every live kind and target form (`permissions.grant_is_live`), as rows: these must survive whole.
LIVE_GRANTS = [
    ("c1", "", "command", "text:git status"), ("c1", "", "command", "unsandboxed:*"), ("c1", "", "outside", "*"),
    ("c1", "", "network", "network:*"), ("c1", "", "schedule", "*"), ("c1", "", "workspace_write", "/Users/x/Projects"),
    ("c1", "", "workspace_write", "*"), ("c1", "", "mcp_tool", "mcp_7__create_issue"),
    ("c1", "", "app", "com.apple.Notes"), ("c1", "", "site", "https://example.com"), ("c1", "", "shortcut", "Daily log"),
    ("sub-1", "", "outside", "*"), ("c2", "turn-1", "app", "com.apple.Notes"),          # a sub-session's; a task's
    # #836 max review: four live shapes pinned. A long MCP tool name is kept hashed (discovery.mcp_tool_key); an app
    # with no bundle id is kept by its name (hands_tools._target); a site may be plain http (a local server).
    ("c1", "", "mcp_tool", mcp_tool_key(7, "create_issue_with_labels_assignees_and_a_long_milestone")),
    ("c1", "", "app", "Notes"), ("c1", "", "site", "http://localhost:8080"),
]
#: One dead grant of each class: an old command target, every once-only kind, the kinds never granted, kinds outside
#: KINDS, and a live kind under a target no request uses.
DEAD_GRANTS = [
    ("c1", "", "command", "rules:git-push"), ("c1", "", "command", "delete|hermes:recursive delete"),
    ("c1", "", "command", ""),
    *[("c1", "", kind, "*") for kind in ("money", "app_risky", "capability", "other_agent", "system", "opaque",
                                         "remote", "takeover")],
    ("c1", "", "remote", "remote:10.0.0.2"),
    *[("c1", "", kind, "*") for kind in ("destructive", "folder", "send", "screen")],
    ("c1", "", "legacy_rule", "git-push"), ("c1", "", "nonsense", "*"),
    ("c1", "", "outside", "/"), ("c1", "", "network", "*"), ("c1", "", "schedule", "daily"),
    ("c1", "", "mcp_tool", "x"), ("c1", "", "app", ""),
]
#: Target forms the frozen copy is checked against, for every kind.
TARGET_FORMS = ["", "*", "/", "daily", "network:*", "network:x", "unsandboxed:*", "unsandboxed:x", "text:", "text:ls",
                "rules:git-push", "delete|hermes:x", "mcp_7__x", "mcp_", "x", "/Users/x/Projects", "com.apple.Notes",
                "https://example.com", "Daily log", "remote:10.0.0.2", "capability:x"]


def _grant_rows(conn):
    return conn.exec_driver_sql("SELECT id, conversation_id, task_id, kind, target, call_id, created_at "
                                "FROM permission_grants ORDER BY id").fetchall()


def _with_grants(path, rows):
    engine = _old_database(path)
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM permission_grants")
        for n, (cid, task, kind, target) in enumerate(rows):
            conn.exec_driver_sql("INSERT INTO permission_grants (conversation_id, task_id, kind, target, call_id, "
                                 "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (cid, task, kind, target, f"card-{n}", f"2026-10-{n % 28 + 1:02d} 10:00:00"))
    return engine


def test_migration_0092_keeps_every_live_grant_untouched(tmp_path):
    """The failure that matters most: a grant a request still reads must survive whole, field by field."""
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    engine = _with_grants(tmp_path / "live.db", LIVE_GRANTS + DEAD_GRANTS)
    with engine.begin() as conn:
        before = _grant_rows(conn)
        m0092.upgrade_sync(conn)
        after = _grant_rows(conn)
        m0092.upgrade_sync(conn)                      # a re-run finds nothing more to do
        assert _grant_rows(conn) == after
    live = [row for row in before if (row[1], row[2], row[3], row[4]) in LIVE_GRANTS]
    assert len(live) == len(LIVE_GRANTS)
    assert after == live


def test_migration_0092_deletes_every_dead_grant(tmp_path):
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    engine = _with_grants(tmp_path / "dead.db", DEAD_GRANTS)
    with engine.begin() as conn:
        assert len(_grant_rows(conn)) == len(DEAD_GRANTS)
        m0092.upgrade_sync(conn)
        assert _grant_rows(conn) == []


def test_the_migrations_frozen_rule_agrees_with_todays_grant_is_live():
    """0092 carries a frozen copy of today's rule (it must not change history when the app's rule changes). A change
    to `permissions.grant_is_live` fails here, loudly: then decide whether 0092's copy is what history was."""
    from server.db.migrations.versions import _0092_remove_legacy_command_rules as m0092
    kinds = sorted(permissions.KINDS | {"legacy_rule", "nonsense", ""})
    for kind in kinds:
        for target in TARGET_FORMS:
            assert m0092._grant_is_live(kind, target) == permissions.grant_is_live(kind, target), (kind, target)
    for _, _, kind, target in LIVE_GRANTS:
        assert permissions.grant_is_live(kind, target), (kind, target)
    for _, _, kind, target in DEAD_GRANTS:
        assert not permissions.grant_is_live(kind, target), (kind, target)


# ── nothing writes a command rule again ──────────────────────────────────────

async def _away_row(always) -> int:
    async with db_session.AsyncSessionLocal() as db:
        row = await permission_store.record(db, kind="command", target="rules:git-push", mode="standard",
                                            decided_by="away", decision="expired", conversation_id="c1",
                                            extra={"always": always})
        await db.commit()
        return row.id


async def _stored_rules() -> set[tuple[str, str]]:
    async with db_session.AsyncSessionLocal() as db:
        return {(r.kind, r.target) for r in (await db.execute(select(PermissionRule))).scalars()}


@pytest.mark.parametrize("always", [
    [["legacy_rule", "git-push", "publishes to a remote"]],                     # what a 0.1.61 card recorded
    [["app", "com.apple.Notes", "Notes"], ["legacy_rule", "delete", "x"]],    # one such entry spoils the set
])
async def test_always_allow_on_an_old_row_no_longer_makes_a_command_rule(api, always):
    """The ledger keeps 90 days: an away row from before S2a-2 still carries a `legacy_rule` set. "Always allow"
    on it stores nothing (fail closed, the whole set), so the rows 0092 deleted never come back."""
    refused_id = await _away_row(always)
    response = await api.post("/api/v1/permissions/rules", json={"refused_id": refused_id})
    assert response.status_code == 409 and response.json()["detail"] == {"code": "no_always"}
    assert await _stored_rules() == set()


async def test_always_allow_on_an_app_row_still_works(api):
    """The control for the case above: a set of kinds a card may store is still allowed."""
    refused_id = await _away_row([["app", "com.apple.Notes", "Notes"]])
    response = await api.post("/api/v1/permissions/rules", json={"refused_id": refused_id})
    assert response.status_code == 200
    assert await _stored_rules() == {("app", "com.apple.Notes")}


async def test_the_not_done_list_says_which_expiry_each_entry_was(api):
    """S4a follow-up 1, wording only: the ledger is unchanged (a never-opened card is `away`, `expired`); the list
    says whether the card never opened or was shown and ran out, so the page can word each."""
    await _away_row([["app", "com.apple.Notes", "Notes"]])
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.record(db, kind="schedule", target="*", mode="standard", decided_by="expired",
                                      decision="expired", conversation_id="c1")
        await permission_store.record(db, kind="site", target="https://example.com", mode="standard",
                                      decided_by="policy", decision="deny", conversation_id="c1")
        await db.commit()
    rows = (await api.get("/api/v1/approvals/refused", params={"conversation_id": "c1"})).json()
    assert {(r["kind"], r["unopened"], r["unattended"]) for r in rows} == {
        ("command", True, False), ("schedule", False, False), ("site", False, True)}


async def test_a_card_cannot_store_a_command_rule(execution_db):
    req = permissions.Request(kind="command", target="rules:git-push", title="Run git push?", always_label="x",
                              remember_as=(("legacy_rule", "git-push"),))
    with pytest.raises(ValueError):
        await permissions.decide(req, permissions.Context(conversation_id="c1"))
    assert await _stored_rules() == set()


# ── taking a grant back asks again, through the real tool loop ───────────────

@pytest.mark.parametrize("sandbox,ask_all,what", [
    (False, False, "unsandboxed"),      # the sandbox is off: layer ③'s card, `unsandboxed:*`
    (True, True, "command"),            # "ask for every command": `text:<command>`
])
async def test_taking_a_grant_back_makes_the_same_command_ask_again(api, monkeypatch, sandbox, ask_all, what):
    _toggles(monkeypatch, sandbox=sandbox, ask_all=ask_all)
    first = _Asker("conversation")
    await _run(monkeypatch, "echo hi", first)
    assert len(first.frames) == 1                            # asked, answered "In this conversation"
    again = _Asker("once")
    await _run(monkeypatch, "echo hi", again)
    assert again.frames == []                                # the grant answers
    [grant] = [g for g in await _grants(api) if g["what"] == what]
    assert grant["conversation_id"] == "c1"
    assert (await api.delete(f"/api/v1/permissions/grants/{grant['id']}")).json() == {"ok": True}
    after = _Asker("once")
    await _run(monkeypatch, "echo hi", after)
    assert len(after.frames) == 1                            # asked again
    assert [g for g in await _grants(api) if g["what"] == what] == []


async def test_taking_an_mcp_tool_grant_back_asks_again(api):
    req = permissions.Request(kind="mcp_tool", target="mcp_7__create_issue", title="Use GitHub's create_issue?")
    ctx = permissions.Context(conversation_id="c1")
    with permissions.asking_with(_Asker("conversation")):
        await permissions.decide(req, ctx)
    again = _Asker("once")
    with permissions.asking_with(again):
        assert (await permissions.decide(req, ctx)).by == "grant"
    [grant] = await _grants(api)
    assert (await api.delete(f"/api/v1/permissions/grants/{grant['id']}")).status_code == 200
    with permissions.asking_with(again):
        assert (await permissions.decide(req, ctx)).by == "user"
    assert len(again.frames) == 1


async def test_an_unknown_id_is_not_found(api):
    assert (await api.delete("/api/v1/permissions/grants/999")).status_code == 404
    assert (await api.delete("/api/v1/permissions/rules/999")).status_code == 404


async def test_the_old_terminal_rules_endpoints_are_gone(client):  # noqa: F811 — the whole app, token-protected
    assert (await client.get("/api/v1/settings/terminal-rules")).status_code == 404
    assert (await client.delete("/api/v1/settings/terminal-rules", params={"rule": "install"})).status_code in (404, 405)
    assert (await client.get("/api/v1/permissions/grants")).status_code == 200      # the app answers otherwise


# ── what the list says ───────────────────────────────────────────────────────

async def _seed_conversations():
    async with db_session.AsyncSessionLocal() as db:
        db.add_all([
            ArslanMessage(conversation_id="c-top", role="user", content="tidy   my\nDownloads"),
            ArslanMessage(conversation_id="c-sub", role="user", content="count the photos"),
            ConversationContext(id="c-sub", kind=sub_sessions.SUB, parent_id="c-top"),
            ConversationContext(id="c-subsub", kind=sub_sessions.SUB, parent_id="c-sub"),
            MCPServer(id=7, label="GitHub", transport="stdio", command="gh-mcp", args=[]),
        ])
        for cid, kind, target in [
            ("c-top", "outside", "*"), ("c-top", "command", "unsandboxed:*"), ("c-top", "command", "text:git status"),
            ("c-top", "network", "network:*"), ("c-top", "workspace_write", "/Users/someone/Projects/notes"),
            ("c-top", "schedule", "*"), ("c-top", "mcp_tool", "mcp_7__create_issue"),
            ("c-top", "mcp_tool", "mcp_8__send"), ("c-top", "site", "https://example.com"),
            ("c-top", "shortcut", "Daily log"), ("c-sub", "outside", "*"), ("c-subsub", "schedule", "*"),
        ]:
            await permission_store.add_grant(db, cid, "", kind, target, call_id="card")
        app = await permission_store.add_grant(db, "c-top", "", "app", "com.apple.Notes", call_id="card-app")
        await permission_store.record(db, kind="app", target="com.apple.Notes", mode="standard", decided_by="user",
                                      decision="allow", scope="conversation", conversation_id="c-top",
                                      grant_id=app.id, extra={"app": "Notes", "bundle_id": "com.apple.Notes"})
        await permission_store.add_grant(db, "c-top", "turn-1", "outside", "*", call_id="task")   # a task's: not listed
        await db.commit()


async def test_every_kind_is_listed_with_what_the_page_shows(api):
    await _seed_conversations()
    listed = await _grants(api)
    assert len(listed) == 13                                  # every conversation grant once; the task's is not one
    shown = {(g["conversation_id"], g["what"], g["name"]) for g in listed}
    assert shown == {
        ("c-top", "outside", ""), ("c-top", "unsandboxed", ""), ("c-top", "command", "git status"),
        ("c-top", "network", ""), ("c-top", "workspace_write", "notes"), ("c-top", "schedule", ""),
        ("c-top", "mcp_tool", "create_issue"), ("c-top", "mcp_tool", "send"), ("c-top", "site", "https://example.com"),
        ("c-top", "shortcut", "Daily log"), ("c-top", "app", "Notes"),
        ("c-sub", "outside", ""), ("c-subsub", "schedule", ""),
    }
    mcp = {g["name"]: g for g in listed if g["what"] == "mcp_tool"}
    assert (mcp["create_issue"]["server"], mcp["create_issue"]["server_gone"]) == ("GitHub", False)
    assert (mcp["send"]["server"], mcp["send"]["server_gone"]) == ("", True)
    assert [g["id"] for g in listed] == sorted((g["id"] for g in listed), reverse=True)     # newest first


async def test_a_sub_sessions_grants_are_under_its_commander(api):
    await _seed_conversations()
    by_conversation = {g["conversation_id"]: g for g in await _grants(api)}
    top, sub, subsub = by_conversation["c-top"], by_conversation["c-sub"], by_conversation["c-subsub"]
    assert (top["sub_session"], top["parent_id"], top["title"]) == (False, "c-top", "tidy my Downloads")
    assert (sub["sub_session"], sub["parent_id"], sub["parent_title"], sub["title"]) == (
        True, "c-top", "tidy my Downloads", "count the photos")
    assert (subsub["sub_session"], subsub["parent_id"]) == (True, "c-top")     # a layer down: still the commander's


async def test_a_deleted_conversations_grants_are_not_listed(api):
    """#799: a deleted conversation's row is a tombstone. Its grants are deleted with it, and one that is left (or
    written after) is not listed; neither is a sub-session's whose commander was deleted."""
    await _seed_conversations()
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "c-live", "", "outside", "*", call_id="card")
        await sub_sessions.tombstone(db, ["c-top"])
        await db.commit()
    assert {g["conversation_id"] for g in await _grants(api)} == {"c-live"}


async def test_a_conversation_whose_delete_began_in_this_process_is_not_listed(api, monkeypatch):
    await _seed_conversations()
    monkeypatch.setattr(sub_sessions, "_deleted", {"c-sub"})
    assert {g["conversation_id"] for g in await _grants(api)} == {"c-top"}


async def test_a_rules_grant_from_0162_is_not_listed_as_a_live_one(api, monkeypatch):
    """#836 review: 0.1.61/0.1.62's rule card offered "In this conversation" (`command` / `rules:<rules>`). Since S2a-2
    that card is this time only, so such a grant answers nothing, and nothing deletes or prunes it: never listed."""
    _toggles(monkeypatch, sandbox=True, ask_all=False)
    command = "git push origin main"
    target = "rules:" + "|".join(sorted(terminal_policy.ask_rules(command)))
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "c1", "", "command", target, call_id="card-0162")
        await db.commit()
    asker = _Asker("once")
    await _run(monkeypatch, command, asker)
    assert len(asker.frames) == 1                    # still asked: the grant answers nothing
    assert await _grants(api) == []


@pytest.mark.parametrize("kind,target", [
    ("command", "rules:git-push"), ("command", "delete|hermes:recursive delete"), ("command", ""),
    ("remote", "remote:10.0.0.2"), ("money", "*"), ("app_risky", "com.apple.Terminal"), ("capability", "skill:x"),
    ("destructive", "mcp_7__drop_table"), ("folder", "/tmp"), ("send", "*"), ("screen", "*"),
    ("legacy_rule", "git-push"), ("outside", "/"), ("network", "*"), ("schedule", "daily"), ("mcp_tool", "x"),
])
async def test_a_grant_no_request_reads_is_never_listed(api, kind, target):
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "c1", "", kind, target, call_id="old")
        await permission_store.add_grant(db, "c1", "", "outside", "*", call_id="live")
        await db.commit()
    assert [(g["kind"], g["target"]) for g in await _grants(api)] == [("outside", "*")]


def test_the_grants_todays_cards_store_are_live_and_a_rule_cards_is_not():
    """The allowlist against the real builders: what each command card would grant."""
    shell = "git push origin main"
    rules = sorted(terminal_policy.ask_rules(shell))
    once = approvals._command_request(shell, rules, None)
    assert once.once_only and not permissions.grant_is_live(once.kind, once.target)
    for req in (approvals._command_request("ls", [], None, ask_all=True), approvals._command_request("ls", [], None),
                command_gate._outside_request("mv a ~/b")):
        assert not req.once_only and permissions.grant_is_live(req.kind, req.target), req.target


async def test_the_filter_by_kind_still_works(api):
    await _seed_conversations()
    listed = (await api.get("/api/v1/permissions/grants", params={"kind": "outside"})).json()
    assert {(g["conversation_id"], g["what"]) for g in listed} == {("c-top", "outside"), ("c-sub", "outside")}


async def test_the_rules_list_moves_an_app_from_the_old_hands_setting_first(api, tmp_path):
    hands = tmp_path / "data" / "hands"
    hands.mkdir(parents=True)
    (hands / "settings.json").write_text(json.dumps({"always": [{"bundle_id": "com.apple.Notes", "name": "Notes"}]}))
    rules = (await api.get("/api/v1/permissions/rules")).json()
    assert [(r["kind"], r["target"], r["label"], r["use_count"], r["last_used_at"]) for r in rules] == [
        ("app", "com.apple.Notes", "Notes", 0, None)]
