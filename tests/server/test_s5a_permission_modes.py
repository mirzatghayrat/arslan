"""S5a-1: permission modes per conversation (docs/plans/0164/S5a-permission-modes.md).

Plan / Ask every step / Ask only when risky / Full access. A mode widens only in `permissions.decide`, after money
and before standing answers, only where someone can be asked; the hard rules (`hard_rules.never_auto`) hold in every
mode; a sub-session never widens; "Ask only when risky" runs as "Ask every step" in three cases."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.db.models import ApprovalEvent, Setting
from server.services import checkpoints, execution_context, permission_store, permissions, settings_service
from server.services.permissions import Context, Request

CONV = "conv-s5a"


class Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": None, "note": "", "by": "mac"}


@pytest.fixture(autouse=True)
def _fresh(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    permissions._reset_for_tests()
    # The fallbacks' inputs, all "fine" unless a test says otherwise: a sandbox that is on and starts, a work folder
    # that isn't home, a run with no checkpoint to read.
    from server.orchestrator import command_gate
    from server.services import command_sandbox
    monkeypatch.setattr(command_sandbox, "available", lambda: True)

    async def folder(db):
        return tmp_path / "work"
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", folder)
    (tmp_path / "work").mkdir()
    assert command_gate is not None
    yield


async def _set(conversation_id: str, mode: str | None, *, parent: str | None = None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, conversation_id) or ConversationContext(id=conversation_id)
        row.permission_mode = mode
        if parent is not None:
            row.kind, row.parent_id = "sub", parent
        db.add(row)
        await db.commit()


def _requests(work: Path) -> dict[str, Request]:
    def r(kind, target="*", detail="", **kw):
        return Request(kind=kind, target=target, title=f"{kind}?", detail=detail, **kw)
    return {
        "workspace_write": r("workspace_write", str(work), "notes.txt"),
        "app": r("app", "com.apple.Notes"),
        "mcp_tool": r("mcp_tool", "mcp_1__read"),
        "schedule": r("schedule"),
        "destructive": r("destructive", "mcp_1__drop"),
        "command": r("command", "unsandboxed:*", "ls"),
        "command_rule": r("command", "rules:git-push", "git push"),
        "outside": r("outside", "*", "cp a.txt ~/Desktop/a.txt"),
        "outside_rule": r("outside", "*", "git push"),
        "outside_later": r("outside", "*", "echo x > .git/hooks/pre-commit"),
        "write_later": r("workspace_write", str(work), ".git/hooks/pre-commit"),
        "network": r("network", "network:*", "curl https://example.com"),
        "money": r("money", "shop", once_only=True),
        "send": r("send", "mail"),
        "site": r("site", "https://example.com"),
        "shortcut": r("shortcut", "Do it"),
        "run_later": r("run_later", "/x/.envrc", once_only=True),
        "git_config": r("git_config"),
        "git_include": r("git_include"),
        "git_refused": r("git_refused", once_only=True),
        "app_data": r("app_data", "/x/Library/Mail", once_only=True),
        "remote": r("remote", "remote:box"),
        "takeover": r("takeover", "screen"),
    }


# What full access answers without a card; everything else in the table still asks there.
_FULL_ACCESS_ANSWERS = {"workspace_write", "app", "mcp_tool", "schedule", "destructive", "command", "outside"}
_ANSWERED = {"plan": set(), "ask": set(), "ask_risky": {"workspace_write"}, "full_access": _FULL_ACCESS_ANSWERS}


@pytest.mark.parametrize("mode", list(_ANSWERED))
async def test_each_mode_answers_exactly_its_kinds_and_every_other_card_still_asks(mode, tmp_path):
    await _set(CONV, mode)
    for name, req in _requests(tmp_path / "work").items():
        asker = Asker()
        with permissions.asking_with(asker):
            decision = await permissions.decide(req, Context(CONV, task_id="t"))
        answered = name in _ANSWERED[mode]
        assert (len(asker.frames) == 0) is answered, (mode, name)
        assert decision.allowed is answered and (decision.by == "mode") is answered, (mode, name)


async def test_what_the_mode_answers_is_one_ledger_row_naming_the_mode(tmp_path):
    await _set(CONV, "full_access")
    with permissions.asking_with(Asker()):
        await permissions.decide(_requests(tmp_path / "work")["app"], Context(CONV, task_id="t"))
        await permissions.decide(_requests(tmp_path / "work")["money"], Context(CONV, task_id="t"))
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa.select(ApprovalEvent).order_by(ApprovalEvent.id))).scalars().all()
    assert [(r.kind, r.mode, r.decided_by, r.decision) for r in rows] == [
        ("app", "full_access", "mode", "allow"), ("money", "full_access", "user", "deny")]


async def test_a_mode_never_answers_for_a_run_with_nobody_to_ask(tmp_path):
    await _set(CONV, "full_access")
    decision = await permissions.decide(_requests(tmp_path / "work")["app"], Context(CONV))
    assert (decision.allowed, decision.by) == (False, "policy")


async def test_the_default_is_the_settings_value_and_a_conversations_own_mode_wins():
    assert (await permissions.mode_for(CONV)).mode == "ask_risky"
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"default_permission_mode": "ask"})
    assert (await permissions.mode_for(CONV)).mode == "ask"
    await _set(CONV, "full_access")
    assert (await permissions.mode_for(CONV)).mode == "full_access"


@pytest.mark.parametrize("parent, own, expected", [
    ("ask", "full_access", "ask"),
    ("full_access", None, "full_access"),
    ("plan", "full_access", "plan"),
    ("full_access", "ask", "ask"),
    ("ask_risky", "full_access", "ask_risky"),
])
async def test_a_sub_session_takes_the_narrower_of_its_parents_mode_and_its_own(parent, own, expected):
    await _set("parent", parent)
    await _set("child", own, parent="parent")
    assert (await permissions.mode_for("child")).mode == expected


async def test_a_grandchild_never_widens_past_its_grandparent():
    await _set("top", "ask")
    await _set("mid", "full_access", parent="top")
    await _set("leaf", "full_access", parent="mid")
    assert (await permissions.mode_for("leaf")).mode == "ask"


# ── the three fallbacks: "Ask only when risky" runs as "Ask every step", and says why ─────────────────────────────

async def _write_card_shown(tmp_path) -> bool:
    asker = Asker()
    with permissions.asking_with(asker):
        await permissions.decide(_requests(tmp_path / "work")["workspace_write"], Context(CONV, task_id="t"))
    return bool(asker.frames)


async def test_fallback_when_the_sandbox_cant_start(monkeypatch, tmp_path):
    from server.services import command_sandbox
    await _set(CONV, "ask_risky")
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    mode = await permissions.mode_for(CONV)
    assert (mode.mode, mode.chosen, mode.fallback) == ("ask", "ask_risky", "sandbox_off")
    assert await _write_card_shown(tmp_path)


async def test_fallback_when_the_sandbox_is_switched_off(tmp_path):
    await _set(CONV, "ask_risky")
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"terminal_sandbox_enabled": "false"})
    assert (await permissions.mode_for(CONV)).fallback == "sandbox_off"
    assert await _write_card_shown(tmp_path)


async def test_fallback_when_the_work_folder_is_home(monkeypatch, tmp_path):
    await _set(CONV, "ask_risky")

    async def home(db):
        return Path.home()
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", home)
    mode = await permissions.mode_for(CONV)
    assert (mode.mode, mode.fallback) == ("ask", "home_folder")
    assert await _write_card_shown(tmp_path)


async def test_fallback_when_the_checkpoint_cant_be_saved(monkeypatch, tmp_path):
    await _set(CONV, "ask_risky")
    monkeypatch.setattr(checkpoints, "root_dir", lambda: tmp_path / "checkpoints")
    checkpoints._reset_for_tests()
    for name in ("a", "b", "c"):
        (tmp_path / "work" / name).write_text(name)
    with execution_context.bind_run(4242):
        assert not await _write_card_shown(tmp_path)        # under the cap: saved, so the edit doesn't ask
        checkpoints._reset_for_tests()
        monkeypatch.setattr(checkpoints, "MAX_FILES", 2)     # over the cap: no undo, so it asks
        with execution_context.bind_run(4243):
            mode = await permissions.mode_for(CONV, check_save=True)
            assert (mode.mode, mode.fallback) == ("ask", "no_checkpoint")
            assert await _write_card_shown(tmp_path)


async def test_no_fallback_for_the_other_modes(monkeypatch):
    from server.services import command_sandbox
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    for mode in ("ask", "full_access", "plan"):
        await _set(CONV, mode)
        assert (await permissions.mode_for(CONV)).mode == mode


# ── plan ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def _run_tool(monkeypatch, tool_key: str, args: dict) -> tuple[dict, list]:
    from server.orchestrator import tool_loop
    from server.orchestrator.turn_state import ToolTurn
    ran: list = []

    class Executor:
        key = tool_key

        async def execute(self, args):
            ran.append(tool_key)
            return {"ok": True}
    monkeypatch.setitem(tool_loop.EXECUTORS, tool_key, Executor())

    async def resolve():
        return [{"key": tool_key, "description": tool_key}]

    async def card(*a, **kw):
        return True
    result = await tool_loop._run_tool(tool_key, args, "{}", ToolTurn(
        resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
        confirm_command=card, confirm_workspace_write=card, conversation_id=CONV))
    return result, ran


@pytest.mark.parametrize("tool_key, args", [
    ("write_file", {"path": "a.txt", "content": "x"}),
    ("edit_file", {"path": "a.txt", "old": "x", "new": "y"}),
    ("run_command", {"command": "ls"}),
])
async def test_plan_refuses_writes_and_commands_with_a_message(monkeypatch, tool_key, args):
    await _set(CONV, "plan")
    result, ran = await _run_tool(monkeypatch, tool_key, args)
    assert ran == [] and result["ok"] is False and result.get("code") == "plan_mode"
    assert "Plan mode" in result["error"]


async def test_plan_lets_a_read_run(monkeypatch):
    await _set(CONV, "plan")
    result, ran = await _run_tool(monkeypatch, "list_dir", {"path": "."})
    assert ran == ["list_dir"], result


async def test_the_same_write_runs_when_not_in_plan(monkeypatch):
    await _set(CONV, "ask")
    _, ran = await _run_tool(monkeypatch, "run_command", {"command": "ls"})
    assert ran == ["run_command"]


# ── the API: the desktop window's, never the phone's ─────────────────────────────────────────────────────────────

async def test_the_mode_api_and_plans_start_restores_the_mode_before_plan(client):
    url = "/api/v1/conversations/c1/permission-mode"
    got = (await client.get(url)).json()
    assert (got["mode"], got["chosen"], got["own"], got["fallback"]) in {
        ("ask_risky", "ask_risky", None, ""), ("ask", "ask_risky", None, "sandbox_off"),
        ("ask", "ask_risky", None, "home_folder")}
    assert (await client.put(url, json={"mode": "everything"})).status_code == 422
    assert (await client.put(url, json={"mode": "ask"})).json()["own"] == "ask"
    assert (await client.put(url, json={"mode": "plan"})).json()["own"] == "plan"
    started = (await client.post(url + "/start")).json()
    assert started["own"] == "ask"
    assert (await client.post(url + "/start")).status_code == 409          # not in plan


async def test_start_from_plan_with_no_mode_before_goes_back_to_the_default_never_full_access(client):
    url = "/api/v1/conversations/c2/permission-mode"
    await client.put("/api/v1/settings", json={"default_permission_mode": "full_access"})
    await client.put(url, json={"mode": "plan"})
    assert (await client.post(url + "/start")).json()["own"] is None       # the default, by the user's own choice
    await client.put("/api/v1/settings", json={"default_permission_mode": "ask"})
    await client.put(url, json={"mode": "full_access"})
    await client.put(url, json={"mode": "plan"})
    assert (await client.post(url + "/start")).json()["own"] == "full_access"   # what it was, not wider
    await client.put(url, json={"mode": "ask_risky"})
    await client.put(url, json={"mode": "plan"})
    assert (await client.post(url + "/start")).json()["own"] == "ask_risky"


async def test_no_phone_route_or_bridge_call_or_island_request_sets_a_mode(client):
    from server.api import conversations, phone
    assert [r.path for r in conversations.router.routes if "permission-mode" in r.path]
    assert not [r.path for r in phone.router.routes if "mode" in r.path]
    root = Path(__file__).resolve().parents[2]
    for folder in (root / "desktop" / "bridge" / "Sources", root / "web" / "src" / "island"):
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in {".swift", ".ts", ".tsx"}:
                text = path.read_text(errors="ignore")
                assert "permission-mode" not in text and "default_permission_mode" not in text, path
    # The phone's one conversation write takes its own field only; a mode in its body changes nothing.
    await client.put("/api/v1/conversations/c3/permission-mode", json={"mode": "ask"})
    await client.post("/api/v1/phone/conversations/c3/update", json={"kind": "chat", "permission_mode": "full_access"})
    assert (await client.get("/api/v1/conversations/c3/permission-mode")).json()["own"] == "ask"


async def test_the_phones_details_keep_their_two_documented_values():
    from server.services import phone_details
    for mode, shown in (("ask", "careful"), ("plan", "careful"), ("ask_risky", "standard"), ("full_access", "standard")):
        await _set(CONV, mode)
        async with db_session.AsyncSessionLocal() as db:
            assert (await phone_details.details(db, CONV))["mode"] == shown


# ── settings and the migration ───────────────────────────────────────────────────────────────────────────────────

async def test_settings_carry_the_default_and_the_old_policy_only_as_a_derived_read(client):
    body = (await client.get("/api/v1/settings")).json()
    assert body["default_permission_mode"] == "ask_risky" and body["shell_confirm_policy"] == "ask_risky"
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": "nope"})).status_code == 422
    body = (await client.put("/api/v1/settings", json={"default_permission_mode": "ask"})).json()
    assert (body["default_permission_mode"], body["shell_confirm_policy"]) == ("ask", "ask_all")
    # S5a-2 deletes this: the window still writes the old field until then; it lands in the new key only.
    body = (await client.put("/api/v1/settings", json={"shell_confirm_policy": "ask_risky"})).json()
    assert body["default_permission_mode"] == "ask_risky"
    async with client.db_maker() as db:
        keys = set((await db.execute(sa.select(Setting.key))).scalars())
    assert "shell_confirm_policy" not in keys
    assert not hasattr(settings_service, "shell_confirm_policy")


@pytest.mark.parametrize("stored, expected", [
    ("ask_all", "ask"), ("ask_risky", "ask_risky"), ("ASK_ALL", "ask_risky"), (None, None)])
def test_the_migration_maps_ask_all_to_ask_and_everything_else_to_ask_risky(tmp_path, stored, expected):
    from server.db.migrations.versions._0098_permission_modes import upgrade_sync
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE settings (key VARCHAR PRIMARY KEY, value TEXT)")
        c.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY)")
        if stored is not None:
            c.exec_driver_sql("INSERT INTO settings VALUES ('shell_confirm_policy', ?)", (stored,))
    for _ in range(2):                                  # idempotent
        with engine.begin() as c:
            upgrade_sync(c)
    with engine.begin() as c:
        rows = dict(c.exec_driver_sql("SELECT key, value FROM settings").fetchall())
        columns = {row[1] for row in c.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    assert rows.get("default_permission_mode") == expected and "shell_confirm_policy" not in rows
    assert {"permission_mode", "previous_mode"} <= columns
