"""H2 (docs/plans/0162/H2): a Hands result that stopped before anything reached an app says
`executed: False`, so a task counts it as a known failure instead of "check this yourself"; one
that may have done part or all of it never says so. Hands is faked; nothing is sent to a model."""
import re
from pathlib import Path

import pytest

from server.registry import hands_tools
from server.services import background_jobs, desktop_status, hands_client, hands_contract, hands_service
from tests.server import test_hands_0153 as base

_case = base._case
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

ROOT = Path(__file__).resolve().parents[2]
CLICK = {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}


# ── every code is sorted ─────────────────────────────────────────────────────

def _codes_in_hands() -> dict[str, str]:
    """Every refusal code the helper can say: `refuse("…"` in desktop/hands/src, the capture codes it
    passes through, and the lost-reply code hands_client makes up."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "desktop" / "hands" / "src").glob("*.rs")):
        text = path.read_text()
        for match in re.finditer(r'refuse\(\s*"([A-Za-z_]+)"', text):
            found.setdefault(match.group(1), f"{path.name}:{text[:match.start()].count(chr(10)) + 1}")
        if "fn capture_code" in text:
            body = text.split("fn capture_code", 1)[1].split("\n}\n", 1)[0]
            for code in re.findall(r'=> "([a-z_0-9]+)"', body):
                found.setdefault(code, f"{path.name}: capture_code")
    client = (ROOT / "server" / "services" / "hands_client.py").read_text()
    for code in re.findall(r'"code": "([A-Za-z_]+)"', client):
        found.setdefault(code, "hands_client.py")
    return found


def _codes_in_tools() -> set[str]:
    text = (ROOT / "server" / "registry" / "hands_tools.py").read_text()
    said = set(re.findall(r'"code": "([A-Za-z_]+)"', text)) | set(re.findall(r'\bcode="([A-Za-z_]+)"', text))
    said |= set(re.findall(re.escape('["code"] = "') + '([A-Za-z_]+)"', text))     # out["code"] = "…"
    return said | set(hands_tools._SHOT_NOTES)


# hands_contract.parse()'s own fallbacks: a reply that is not one, a refusal or an agent-desktop error without a code
PARSE_FALLBACKS = {"refused", "bad_reply", "bad_output", "INTERNAL"}


def test_the_two_lists_do_not_overlap():
    assert not hands_tools.NOT_EXECUTED & hands_tools.MAYBE_EXECUTED


def test_every_code_hands_or_the_tools_can_say_is_sorted():
    """A code added later without saying whether it ran turns CI red here."""
    known = hands_tools.NOT_EXECUTED | hands_tools.MAYBE_EXECUTED
    from_hands = _codes_in_hands()
    assert len(from_hands) > 40, "the scan found Hands' codes"
    unsorted = {code: where for code, where in from_hands.items() if code not in known}
    assert not unsorted, f"say whether these ran (hands_tools.NOT_EXECUTED / MAYBE_EXECUTED): {unsorted}"
    for name, codes in (("hands_contract.REFUSALS", set(hands_contract.REFUSALS)),
                        ("hands_contract.HINTS", set(hands_contract.HINTS)),
                        ("hands_tools.py", _codes_in_tools())):
        assert not codes - known, f"{name}: {sorted(codes - known)}"
    assert PARSE_FALLBACKS <= hands_tools.MAYBE_EXECUTED


def test_a_code_nothing_says_any_more_leaves_the_lists():
    """The other way round: a code stays sorted only while something says it (F5b's deleted engine left
    seven behind)."""
    said = (set(_codes_in_hands()) | _codes_in_tools() | set(hands_contract.REFUSALS) | set(hands_contract.HINTS)
            | PARSE_FALLBACKS)
    known = hands_tools.NOT_EXECUTED | hands_tools.MAYBE_EXECUTED
    assert not known - said, f"nothing says these any more; take them out of the lists: {sorted(known - said)}"


@pytest.mark.parametrize("code", ["unknown", "TIMEOUT", "submit_unsure", "takeover_paused", "stopped_by_user",
                                  "batch_stopped", "bad_output", "helper_failed", "menu_press_failed",
                                  "ACTION_FAILED", "STALE_REF"])
def test_what_may_have_run_is_never_called_not_run(code):
    assert code in hands_tools.MAYBE_EXECUTED
    failed = hands_tools._failed(hands_contract.Result(ok=False, code=code, refused=True))
    assert "executed" not in failed


def test_a_code_nobody_sorted_yet_is_taken_as_maybe():
    failed = hands_tools._failed(hands_contract.Result(ok=False, code="something_new", refused=True))
    assert "executed" not in failed


# ── a card said no ───────────────────────────────────────────────────────────

async def test_a_declined_card_did_not_run(hands, asks, in_job):
    _, answer = asks
    answer["value"] = False
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "declined" and result["executed"] is False and hands.ops("click") == []


async def test_a_card_nobody_answered_did_not_run(hands, asks, in_job):
    _, answer = asks
    answer["value"] = "expired"
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "no_answer" and result["executed"] is False and hands.ops("click") == []


async def test_a_declined_risky_step_did_not_run(hands, asks, in_job):
    seen, answer = asks
    hands.target = {**hands.target, "name": "Delete"}

    async def yes_then_no(frame):
        seen.append(frame)
        return {"approved": frame["kind"] != "desktop_risky", "scope": (frame.get("options") or [None])[0],
                "note": "", "by": "mac"}
    from server.services import permissions
    with permissions.asking_with(yes_then_no):
        result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert [f["kind"] for f in seen] == ["desktop_app", "desktop_risky"]
    assert result["code"] == "declined" and result["executed"] is False and hands.ops("click") == []


async def test_a_declined_shortcut_did_not_run(asks, in_job, monkeypatch):
    _, answer = asks
    answer["value"] = False
    ran = []

    async def run(argv, **kw):
        ran.append(argv)
        return {"ok": True}
    monkeypatch.setattr(hands_tools, "_run", run)
    result = await hands_tools.MacRunShortcutExecutor().execute({"name": "Tidy"})
    assert result["code"] == "declined" and result["executed"] is False and ran == []


# ── checks before the action ─────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["screen_locked", "app_denied", "changed", "borrow_off", "waiting_for_pause",
                                  "window_elsewhere", "ref_unknown", "password_field"])
async def test_hands_refusing_before_the_action_did_not_run(hands, asks, in_job, monkeypatch, code):
    real = hands.call

    async def refuses(op, args=None, **kw):
        if op == "click":
            hands.calls.append((op, dict(args or {})))
            return {"ok": False, "refused": {"code": code, "message": "x"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", refuses)
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == code and result["executed"] is False


async def test_a_never_list_app_is_refused_before_anything(hands, asks, in_job):
    hands.apps.append({"name": "Keychain Access", "bundle_id": "com.apple.keychainaccess", "tier": "full"})
    result = await hands_tools.DesktopOpenExecutor().execute({"app": "Keychain Access"})
    assert result["code"] == "app_denied" and result["executed"] is False


async def test_a_look_only_app_is_refused_before_anything(hands, asks, in_job):
    hands.tier = "look_only"
    result = await hands_tools.DesktopClickExecutor().execute({**CLICK, "app": "Safari"})
    assert result["code"] == "app_look_only" and result["executed"] is False and hands.ops("click") == []


async def test_a_stopped_job_did_not_run(hands, asks, in_job, monkeypatch):
    class Job:
        phase = "running"
    monkeypatch.setitem(background_jobs._jobs, "job-1", Job())
    from server.services import hands_service
    hands_service.stop_running_jobs()
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "stopped_by_user" and result["executed"] is False and hands.calls == []


async def test_a_describe_that_failed_did_not_run_the_action(hands, asks, in_job, monkeypatch):
    """The target is read before the action; a lost reply to that read sent no action."""
    real = hands.call

    async def lost(op, args=None, **kw):
        if op == "describe":
            return {"ok": False, "refused": {"code": "unknown", "message": "Arslan Hands stopped answering"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", lost)
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "unknown" and result["executed"] is False and hands.ops("click") == []


async def test_hands_that_could_not_be_reached_did_not_run(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def unreachable(op, args=None, **kw):
        if op == "click":
            raise hands_client.HandsUnavailable("could not reach Arslan Hands")
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", unreachable)
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "hands_unavailable" and result["executed"] is False


async def test_hands_switched_off_and_bad_requests_did_not_run(hands, asks, in_job, monkeypatch):
    assert (await hands_tools.DesktopClickExecutor().execute({"ref": "@sfixture0:e3"})) == {
        "ok": False, "external": False, "code": "bad_request", "executed": False,
        "error": "app required (a name from desktop_apps)"}
    monkeypatch.setattr(hands_client, "available", lambda: False)
    for tool, args in ((hands_tools.DesktopClickExecutor(), CLICK), (hands_tools.DesktopLookExecutor(), CLICK),
                       (hands_tools.DesktopAppsExecutor(), {}), (hands_tools.DesktopOpenExecutor(), {"app": "Notes"}),
                       (hands_tools.DesktopAccessExecutor(), {"apps": ["Notes"], "why": "x"}),
                       (hands_tools.DesktopTakeoverExecutor(), {"why": "x", "minutes": 2})):
        result = await tool.execute(args)
        assert result["code"] == "hands_unavailable" and result["executed"] is False, tool.key
        assert result["error"] == "Arslan Hands is not available on this Mac.", "the words are unchanged"


async def test_acting_in_a_chat_reply_after_stop_did_not_run(hands, asks, in_turn):
    # H3: the chat reply's own limit is gone; a Stop in the turn is what refuses now.
    with desktop_status.working("c1"):
        hands_service.stop_running_jobs()
        result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "stopped_by_user" and result["executed"] is False
    assert hands.ops("click") == []


async def test_a_script_outside_background_work_did_not_run():
    result = await hands_tools.MacAppleScriptExecutor().execute({"script": 'tell application "Notes" to activate'})
    assert result["code"] == "act_in_background" and result["executed"] is False


# ── what may have run ────────────────────────────────────────────────────────

async def test_a_lost_reply_to_the_action_may_have_run(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def lost(op, args=None, **kw):
        if op == "click":
            hands.calls.append((op, dict(args or {})))
            return {"ok": False, "refused": {"code": "unknown", "message": "Arslan Hands stopped answering"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", lost)
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "unknown" and "executed" not in result and hands.ops("click") == ["click"]


async def test_text_typed_without_return_may_have_run(hands, asks, in_job):
    hands.target = {"role": "textfield", "name": "Body", "states": [], "password": False}
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": "hi", "submit": True})
    assert result["code"] == "submit_unsure" and "executed" not in result
    assert hands.ops("set_value") == ["set_value"]


async def test_a_timed_out_action_may_have_run(hands, asks, in_job):
    hands.fail_with = _case("err_timeout")["envelope"] | {"command": "click"}
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "TIMEOUT" and "executed" not in result


async def test_a_takeover_paused_mid_action_may_have_run(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def paused(op, args=None, **kw):
        if op == "click":
            return {"ok": False, "refused": {"code": "takeover_paused", "message": "x"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", paused)
    result = await hands_tools.DesktopClickExecutor().execute(CLICK)
    assert result["code"] == "takeover_ended" and "executed" not in result


# ── batches ──────────────────────────────────────────────────────────────────

async def test_a_batch_whose_first_step_was_declined_did_not_run(hands, asks, in_job):
    _, answer = asks
    answer["value"] = False
    result = await hands_tools.DesktopBatchExecutor().execute(
        {"app": "Notes", "steps": [{"action": "click", "ref": "@sfixture0:e3"}, {"action": "press", "keys": "tab"}]})
    assert result["code"] == "batch_stopped" and result["executed"] is False and hands.ops("click", "press") == []


async def test_a_batch_that_stopped_after_a_step_ran_may_have_run(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def second_refused(op, args=None, **kw):
        if op == "press":
            return {"ok": False, "refused": {"code": "changed", "message": "x"}}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", second_refused)
    result = await hands_tools.DesktopBatchExecutor().execute(
        {"app": "Notes", "steps": [{"action": "click", "ref": "@sfixture0:e3"}, {"action": "press", "keys": "tab"}]})
    assert result["code"] == "batch_stopped" and "executed" not in result and hands.ops("click") == ["click"]
