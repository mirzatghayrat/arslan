"""0.1.53 Hands: Mac apps through Arslan Hands (agent-desktop behind a helper app
that alone holds Accessibility). Spec: docs/specs/2026-10-03-0153-hands-agent-desktop.md.

The backend half of the contract is checked against the real agent-desktop
envelopes in tests/fixtures/hands_contract/; Hands itself is faked here (its own
tests are in desktop/hands). Nothing here launches anything."""
import json
import os
import stat
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import (approvals, background_jobs, desktop_status, hands_client, hands_contract,
                             hands_service, personal_context as pc, task_service)

pytestmark = pytest.mark.one_arslan

CASES = sorted((Path(__file__).resolve().parents[1] / "fixtures" / "hands_contract").glob("*.json"))


def _case(name: str) -> dict:
    return next(json.loads(p.read_text()) for p in CASES if json.loads(p.read_text())["case"] == name)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(hands_service, "_dir", lambda: tmp_path / "hands")
    hands_service._reset_for_tests()
    yield
    hands_service._reset_for_tests()


# ── the contract, backend side ───────────────────────────────────────────────

@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_every_recorded_envelope_reads_as_the_contract_says(path):
    case = json.loads(path.read_text())
    expect = case["expect"]
    result = hands_contract.parse({"ok": True, "envelope": case["envelope"], "exit": case["exit"]})
    allowed_ok = expect["ok"] or "ok" in expect.get("also", [])
    assert result.ok == case["envelope"]["ok"] and (result.ok <= allowed_ok)
    if result.ok:
        for pointer in expect.get("reads", {}):
            node = {"data": result.data}
            for part in pointer.strip("/").split("/"):
                node = node[int(part)] if isinstance(node, list) else node[part]
    else:
        assert result.code in [expect.get("code"), *expect.get("also", [])]
        if result.code == expect.get("code"):
            assert result.hint == expect.get("hint"), case["case"]
        assert not result.refused, "agent-desktop's errors are not Hands' refusals"
        if result.hint:
            assert hands_contract.MESSAGES[result.hint] in result.advice()


def test_hands_own_refusals_read_as_refusals_with_advice():
    result = hands_contract.parse({"ok": False, "refused": {"code": "app_denied", "message": "x"}})
    assert result.refused and result.code == "app_denied"
    assert "never touches" in result.advice()
    unknown = hands_contract.parse({"ok": False, "refused": {"code": "something_new", "message": "say this"}})
    assert unknown.advice() == "say this"


def test_the_outline_shows_refs_and_hides_password_values():
    data = _case("snapshot")["envelope"]["data"]
    text = hands_contract.render_tree(data["tree"])
    assert "button “Save” [@sfixture0:e3]" in text
    password = next(line for line in text.splitlines() if "“Password”" in line)
    assert "(secure)" in password and "=" not in password
    # agent-desktop hides secure values itself; the outline does too, whatever binary sits behind Hands.
    leaky = {"role": "window", "children": [{"role": "textfield", "name": "PIN", "value": "4321",
                                              "states": ["secure"], "ref_id": "@sx1y2z3:e1"}]}
    assert "4321" not in hands_contract.render_tree(leaky)
    many = {"role": "window", "children": [
        {"role": "table", "ref_id": "@sx1y2z3:e1",
         "children": [{"role": "row", "name": f"note {i}", "ref_id": f"@sx1y2z3:e{i + 10}"} for i in range(120)]},
        {"role": "textfield", "states": ["focused"], "ref_id": "@sx1y2z3:e500"}]}
    outline = hands_contract.render_tree(many)
    assert outline.count("row “note") == 10 and "… 110 more row (look with ref [@sx1y2z3:e1]" in outline
    assert "@sx1y2z3:e500" in outline, "what comes after a long list is still shown"
    focused = {"role": "textfield", "states": ["focused"], "ref_id": "@sx1y2z3:e9"}
    assert "(focused)" in hands_contract.render_tree(focused), "the model can see where typing goes"
    short = hands_contract.render_tree(data["tree"], limit=120)
    assert short.endswith("look again with a ref to open a part)")


# ── the shared policy file and what asks every time ──────────────────────────

def test_settings_show_the_list_hands_enforces():
    lists = hands_service.built_in_lists()
    for label in ("Keychain Access", "1Password", "System Settings", "Arslan", "Notification Center"):
        assert label in lists["never"]
    assert lists["look_only"] == ["Web browsers"] and lists["click_only"] == ["Terminals and code editors"]
    rust = Path(__file__).resolve().parents[2] / "desktop" / "hands" / "src" / "policy.rs"
    assert 'include_str!("../policy.json")' in rust.read_text(), "the helper compiles in the same file"


@pytest.mark.parametrize("label,risky", [
    ("Delete", True), ("Move to Trash", True), ("Send", True), ("删除", True), ("发送", True), ("提交订单", True),
    ("付款", True), ("Transfer money", True), ("Buy now", True), ("Löschen", True), ("送信", True),
    ("Save", False), ("New Note", False), ("Rename", False), ("保存", False), ("Sender", False), (None, False),
])
def test_risky_labels(label, risky):
    assert hands_service.risky_label(label) is risky


def test_risky_keys_and_return_where_it_sends():
    assert hands_service.risky_keys("cmd+delete", bundle_id="com.apple.finder", app="Finder")
    assert hands_service.risky_keys("return", bundle_id="com.apple.MobileSMS", app="Messages")
    assert not hands_service.risky_keys("return", bundle_id="com.apple.Notes", app="Notes")
    assert hands_service.risky_text("see you\n", bundle_id="com.tinyspeck.slackmacgap", app="Slack")
    assert not hands_service.risky_text("see you\n", bundle_id="com.apple.Notes", app="Notes")
    # A Team ID prefix (seen on a real Mac) does not hide an app from the lists.
    assert hands_service.sends_on_return("ABCDE12345.com.tinyspeck.slackmacgap", "x")


def test_settings_file_is_private_and_the_never_list_deduplicated(tmp_path):
    assert hands_service.settings() == {"enabled": True, "cursor": True, "never": []}
    hands_service.update_settings(never=["Notes", "notes", "  Mail  ", ""], cursor=False)
    assert hands_service.settings() == {"enabled": True, "cursor": False, "never": ["Notes", "Mail"]}
    folder = tmp_path / "hands"
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(folder / "settings.json").st_mode) == 0o600


def test_the_trace_is_private_never_holds_typed_text_and_keeps_seven_days(tmp_path):
    hands_service.trace({"op": "set_value", "app": "Notes", "typed_chars": 9})
    folder = tmp_path / "hands" / "trace"
    files = list(folder.glob("*.jsonl"))
    assert len(files) == 1 and stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    old = folder / f"{(date.today() - timedelta(days=7)).isoformat()}.jsonl"
    old.write_text('{"op": "click"}\n')
    hands_service.prune_trace()
    assert not old.exists()
    assert [e["op"] for e in hands_service.read_trace()] == ["set_value"]


# ── the tools, with Hands faked ──────────────────────────────────────────────

class FakeHands:
    """Answers like Arslan Hands would, from the contract fixtures."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.target = {"role": "button", "name": "Save", "actions": ["Click"], "states": [], "password": False}
        self.tier = "full"
        self.apps = [{"name": "Notes", "bundle_id": "com.apple.Notes", "tier": "full"},
                     {"name": "Safari", "bundle_id": "com.apple.Safari", "tier": "look_only"},
                     {"name": "Messages", "bundle_id": "com.apple.MobileSMS", "tier": "full"}]
        self.fail_with: dict | None = None

    async def call(self, op, args=None, *, timeout=60.0, start=True):
        self.calls.append((op, dict(args or {})))
        if self.fail_with and op not in ("list_apps", "describe", "request_permission", "session_start",
                                         "session_label"):
            return {"ok": True, "envelope": self.fail_with}
        if op == "list_apps":
            return {"ok": True, "apps": self.apps}
        if op == "session_start":
            return {"ok": True, "session": "run-1-2-0"}
        if op in ("session_label", "session_end", "request_permission", "stop"):
            return {"ok": True}
        if op == "status":
            return {"ok": True, "accessibility": False, "peer_check": "off", "version": "0.1.0"}
        app = next((a for a in self.apps if a["name"] == args.get("app")), self.apps[0])
        if op == "describe":
            return {"ok": True, "app": app, "tier": self.tier, "sends_on_return": False, "target": self.target}
        envelope = {"snapshot": _case("snapshot"), "find": _case("find"), "click": _case("click"),
                    "set_value": _case("set_value"), "press": _case("press"), "select": _case("select"),
                    "scroll": _case("scroll"), "wait": _case("wait"), "get": _case("get_value"),
                    "type": _case("type")}[op]["envelope"]
        return {"ok": True, "app": app, "envelope": envelope}

    def ops(self, *names):
        return [op for op, _ in self.calls if not names or op in names]


@pytest.fixture
def hands(monkeypatch):
    fake = FakeHands()
    monkeypatch.setattr(hands_client, "call", fake.call)
    monkeypatch.setattr(hands_client, "available", lambda: True)
    return fake


@pytest.fixture
def asks(monkeypatch):
    seen, answer = [], {"value": True}

    async def ask(conversation_id, frame):
        seen.append(frame)
        return answer["value"]
    monkeypatch.setattr(approvals, "ask", ask)
    return seen, answer


@pytest.fixture
def in_turn():
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")):
        yield


@pytest.fixture
def in_job():
    token = background_jobs._inside_job.set("job-1")
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")):
        yield
    background_jobs._inside_job.reset(token)
    hands_tools.forget_job("job-1")


async def test_looking_asks_once_per_app_per_conversation(hands, asks, in_turn):
    seen, _ = asks
    look = hands_tools.DesktopLookExecutor()
    first = await look.execute({"app": "Notes"})
    assert first["ok"] and first["external"] is True and "[@sfixture0:e3]" in first["text"]
    assert (await look.execute({"app": "Notes"}))["ok"]
    assert [(f["kind"], f["target"]) for f in seen] == [("desktop_look", "Notes")]
    found = await look.execute({"app": "Notes", "text": "Save"})
    assert found["ok"] and "button “Save”" in found["text"]
    assert hands.ops("snapshot", "find") == ["snapshot", "snapshot", "find"]


async def test_the_app_list_leaves_out_helper_processes_without_a_bundle_id(hands, in_turn):
    """Measured: agent-desktop's own list-apps run shows up as a running app (no bundle id)."""
    hands.apps = hands.apps + [{"name": "agent-desktop", "bundle_id": None, "pid": 9}]
    text = (await hands_tools.DesktopAppsExecutor().execute({}))["text"]
    assert "agent-desktop" not in text and "Notes" in text


async def test_a_never_list_app_is_named_as_such_not_as_missing(hands, asks, in_turn):
    seen, _ = asks
    for name in ("System Settings", "com.apple.keychainaccess", "1Password"):
        result = await hands_tools.DesktopLookExecutor().execute({"app": name})
        assert result["code"] == "app_denied", name
    hands_service.update_settings(never=["Bear"])
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "bear"}))["code"] == "app_denied"
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Nonesuch"}))["code"] == "app_not_running"
    assert seen == [] and hands.ops("snapshot", "find") == []


async def test_a_window_is_picked_by_its_title(hands, asks, in_turn, monkeypatch):
    real = hands.call

    async def with_windows(op, args=None, **kw):
        if op == "list_windows":
            hands.calls.append((op, dict(args or {})))
            return {"ok": True, "envelope": {"version": "2.4", "ok": True, "command": "list-windows", "data": [
                {"id": "w-1", "title": "Downloads"}, {"id": "w-2", "title": "Hands smoke 2026"}]}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", with_windows)
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes", "window": "hands smoke"}))["ok"]
    full = [a for op, a in hands.calls if op == "snapshot" and "max_depth" not in a]
    assert [a.get("window_id") for a in full] == ["w-2"]
    missing = await hands_tools.DesktopLookExecutor().execute({"app": "Notes", "window": "Nope"})
    assert missing["code"] == "window_not_found"


async def test_without_screen_recording_a_window_title_is_read_from_its_element(hands, asks, in_turn, monkeypatch):
    """Without Screen Recording the window list carries no real titles (agent-desktop
    fills in the app's name, or nothing; measured); a one-level look at each window
    reads its accessibility title instead."""
    real = hands.call

    async def untitled(op, args=None, **kw):
        args = dict(args or {})
        if op == "list_windows":
            hands.calls.append((op, args))
            return {"ok": True, "envelope": {"version": "2.4", "ok": True, "command": "list-windows", "data": [
                {"id": "w-1", "title": "Finder"}, {"id": "w-2", "title": ""}]}}
        if op == "snapshot" and args.get("max_depth") == 1:
            hands.calls.append((op, args))
            name = {"w-1": "Downloads", "w-2": "Hands smoke abc"}[args["window_id"]]
            return {"ok": True, "envelope": {"version": "2.4", "ok": True, "command": "snapshot",
                                             "data": {"tree": {"role": "window", "name": name}}}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", untitled)
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes", "window": "hands smoke"}))["ok"]
    full = [a for op, a in hands.calls if op == "snapshot" and "max_depth" not in a]
    assert [a.get("window_id") for a in full] == ["w-2"]


async def test_several_windows_and_none_named_looks_at_the_focused_one(hands, asks, in_turn, monkeypatch):
    real = hands.call

    async def several(op, args=None, **kw):
        args = dict(args or {})
        if op == "list_windows":
            hands.calls.append((op, args))
            return {"ok": True, "envelope": {"version": "2.4", "ok": True, "command": "list-windows", "data": [
                {"id": "w-1", "title": "Notes", "is_focused": False}, {"id": "w-2", "title": "Notes", "is_focused": True}]}}
        if op == "snapshot" and not args.get("window_id"):
            hands.calls.append((op, args))
            return {"ok": True, "envelope": {"version": "2.4", "ok": False, "command": "snapshot", "error": {
                "code": "AMBIGUOUS_TARGET", "message": "More than one window matches the target"}}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", several)
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes"}))["ok"]
    assert [a.get("window_id") for op, a in hands.calls if op == "snapshot"] == [None, "w-2"]


async def test_a_declined_look_reads_nothing(hands, asks, in_turn):
    _, answer = asks
    answer["value"] = False
    result = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert result["code"] == "declined"
    assert hands.ops("snapshot", "find", "wait") == []


async def test_acting_outside_a_job_is_sent_to_background_work(hands, asks, in_turn):
    seen, _ = asks
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["code"] == "act_in_background"
    assert hands.calls == [] and seen == []


async def test_acting_asks_once_per_app_per_job_and_risky_labels_every_time(hands, asks, in_job):
    seen, _ = asks
    click = hands_tools.DesktopClickExecutor()
    for _ in range(2):
        assert (await click.execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}))["ok"]
    assert [f["kind"] for f in seen] == ["desktop_app"]
    hands.target = {**hands.target, "name": "Delete"}
    for _ in range(2):
        # The model calls it "Tidy up"; the card shows what the button really says.
        assert (await click.execute({"app": "Notes", "element": "Tidy up", "ref": "@sfixture0:e4"}))["ok"]
    risky = [f for f in seen if f["kind"] == "desktop_risky"]
    assert len(risky) == 2 and all("“Delete”" in f["target"] for f in risky)
    assert hands.ops("click") == ["click"] * 4
    assert all(args.get("session") == "run-1-2-0" for op, args in hands.calls if op == "click")


async def test_a_declined_app_is_not_touched(hands, asks, in_job):
    _, answer = asks
    answer["value"] = False
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["code"] == "declined" and hands.ops("click") == []


async def test_password_fields_are_refused_before_anyone_is_asked(hands, asks, in_job):
    seen, _ = asks
    hands.target = {"role": "textfield", "name": "Password", "states": ["secure"], "password": True}
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Password", "ref": "@sfixture0:e2", "text": "hunter2"})
    assert result["code"] == "password_field" and seen == [] and hands.ops("set_value", "type") == []


async def test_look_only_apps_refuse_before_asking(hands, asks, in_job):
    seen, _ = asks
    hands.tier = "look_only"
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Safari", "element": "Buy", "ref": "@sfixture0:e3"})
    assert result["code"] == "app_look_only" and seen == [] and hands.ops("click") == []
    pressed = await hands_tools.DesktopPressExecutor().execute({"app": "Safari", "keys": "return"})
    assert pressed["code"] == "app_look_only" and hands.ops("press") == []


async def test_typing_sets_the_value_and_return_in_messages_asks_every_time(hands, asks, in_job):
    seen, _ = asks
    hands.target = {"role": "textfield", "name": "Message", "states": [], "password": False}
    typ = hands_tools.DesktopTypeExecutor()
    assert (await typ.execute({"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": "Groceries"}))["ok"]
    assert hands.ops("set_value") == ["set_value"]
    assert [f["kind"] for f in seen] == ["desktop_app"]
    await typ.execute({"app": "Messages", "element": "Message", "ref": "@sfixture0:e1", "text": "hi", "submit": True})
    assert [f["kind"] for f in seen][-1] == "desktop_risky"
    trace = hands_service.read_trace()
    assert all("Groceries" not in json.dumps(e) for e in trace) and trace[-1]["typed_chars"] == 9


async def test_append_reads_first_and_a_refused_set_value_falls_back_to_typing(hands, asks, in_job):
    hands.target = {"role": "textfield", "name": "Body", "states": [], "password": False}
    await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": " more", "mode": "append"})
    gets = [a for op, a in hands.calls if op == "get"]
    sets = [a for op, a in hands.calls if op == "set_value"]
    assert gets and sets[-1]["value"].endswith(" more")
    hands.fail_with = _case("err_type_refused_headless")["envelope"] | {"command": "set-value"}
    await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": "x"})
    assert hands.ops("set_value", "type")[-2:] == ["set_value", "type"]


async def test_a_stopped_job_refuses_further_hands_calls_and_later_jobs_do_not(hands, asks, in_job, monkeypatch):
    class Job:
        phase = "running"
    monkeypatch.setitem(background_jobs._jobs, "job-1", Job())
    assert hands_service.stop_running_jobs() == ["job-1"]
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["code"] == "stopped_by_user" and hands.calls == []
    assert not hands_service.stopped("job-2")


async def test_without_accessibility_hands_asks_macos_once_and_says_where_the_switch_is(hands, asks, in_turn):
    hands.fail_with = _case("err_perm_denied")["envelope"]
    look = hands_tools.DesktopLookExecutor()
    first = await look.execute({"app": "Notes"})
    await look.execute({"app": "Notes"})
    assert first["code"] == "PERM_DENIED" and "Privacy & Security → Accessibility" in first["error"]
    assert hands.ops("request_permission") == ["request_permission"]
    # Measured on a real Mac: a stale grant kept the switch on while macOS refused, no prompt came, and
    # the model ran AppleScript after AppleScript, each one asking the user. The advice stops that and
    # names the fix (remove the entry, ask again).
    assert "do not do it with AppleScript" in first["error"]
    assert "remove it with “−”" in first["error"] and "Ask macOS" in first["error"]


async def test_a_read_that_times_out_is_tried_once_more_an_action_never(hands, asks, in_turn, monkeypatch):
    timeouts = {"left": 1}
    real = hands.call

    async def flaky(op, args=None, **kw):
        if op == "snapshot" and timeouts["left"]:
            timeouts["left"] -= 1
            hands.calls.append((op, dict(args or {})))
            return {"ok": True, "envelope": _case("err_timeout")["envelope"] | {"command": "snapshot"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", flaky)
    assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes"}))["ok"]
    assert hands.ops("snapshot") == ["snapshot", "snapshot"]


async def test_a_timed_out_action_is_not_repeated(hands, asks, in_job):
    hands.fail_with = _case("err_timeout")["envelope"] | {"command": "click"}
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["code"] == "TIMEOUT" and hands.ops("click") == ["click"]


async def test_stale_refs_say_look_again(hands, asks, in_job):
    hands.fail_with = _case("err_stale_ref")["envelope"]
    result = await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["code"] == "STALE_REF" and "Look again" in result["error"]


async def test_tools_are_offered_like_the_browser(execution_db, hands, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(task_service, "current", lambda: object())
    keys = [t["key"] for t in await arslan._arslan_tools()]
    assert {"desktop_apps", "desktop_look"} <= set(keys)
    assert not {"desktop_click", "desktop_type", "desktop_press"} & set(keys)
    token = background_jobs._inside_job.set("job-9")
    try:
        in_job_keys = {t["key"] for t in await arslan._arslan_tools()}
    finally:
        background_jobs._inside_job.reset(token)
    assert {"desktop_click", "desktop_type", "desktop_select", "desktop_scroll", "desktop_press"} <= in_job_keys
    hands_service.update_settings(enabled=False)
    assert not {"desktop_apps", "desktop_look"} & {t["key"] for t in await arslan._arslan_tools()}


async def test_effects_and_island_steps():
    assert await task_service.effect_of("desktop_look", {}) == "read"
    assert await task_service.effect_of("desktop_apps", {}) == "read"
    for key in ("desktop_click", "desktop_type", "desktop_select", "desktop_scroll", "desktop_press"):
        assert await task_service.effect_of(key, {}) == "external_write"
    step = desktop_status.step_target("desktop_type", {"app": "Notes", "element": "Body", "text": "SECRET"})
    assert step == "Notes · Body"


def test_every_desktop_tool_has_a_schema_and_an_executor():
    from server.orchestrator.tool_loop import _NATIVE_PARAM_SCHEMAS as schemas
    from server.registry.executors import EXECUTORS
    for key in ("desktop_apps", "desktop_look", "desktop_click", "desktop_type", "desktop_select",
                "desktop_scroll", "desktop_press"):
        assert key in EXECUTORS and key in schemas


# ── the API ──────────────────────────────────────────────────────────────────

async def test_api_settings_stop_and_trace(client, monkeypatch, hands):
    monkeypatch.setattr(hands_client, "running", lambda: True)
    got = (await client.get("/api/v1/hands")).json()
    assert got["available"] is True and got["enabled"] is True and "Keychain Access" in got["built_in"]["never"]
    put = (await client.put("/api/v1/hands", json={"never": ["Notes"]})).json()
    assert put["never"] == ["Notes"]

    class Job:
        phase = "running"
    monkeypatch.setitem(background_jobs._jobs, "job-7", Job())
    stopped = (await client.post("/api/v1/hands/stop")).json()
    assert stopped["stopped"] is True and stopped["jobs"] >= 1 and hands_service.stopped("job-7")
    assert ("stop", {}) in hands.calls
    hands_service.trace({"op": "click", "app": "Notes"})
    entries = (await client.get("/api/v1/hands/trace")).json()["entries"]
    assert entries[0]["op"] == "click"
