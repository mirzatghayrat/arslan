"""0.1.61 §A11 / §H.2: Hands asks through permissions.decide. One `app` card covers looking and
acting; money and risky steps are their own kinds and ask every time; a high-reach app never offers
"Always"; "Always" is a rule the next conversation reads; only the user's own no is a refusal; and
every decision is a ledger row. Hands is faked; nothing is sent to a model."""
import pytest

from server.db import session as db_session
from server.registry import hands_tools
from server.services import background_jobs, hands_service, permission_store
from server.services import personal_context as pc
from tests.server import test_hands_0153 as base
from tests.server.test_hands_0145 import browser  # noqa: F401  (a fixture: the browser, faked)

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job


CLICK = {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}


async def test_a_card_nobody_answered_is_no_answer_not_a_refusal(hands, asks, in_job):
    _, answer = asks
    answer["value"] = "expired"
    look = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert look["code"] == "no_answer"
    assert "NOT a refusal" in look["error"] and "did not allow" not in look["error"]
    assert hands.ops("snapshot") == []


async def test_a_no_tells_the_model_what_the_user_said_instead(hands, asks, in_job):
    _, answer = asks
    answer["value"], answer["note"] = False, "use the web version instead"
    look = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert look["code"] == "declined"
    assert "The user did not allow using Notes" in look["error"] and "use the web version instead" in look["error"]


async def test_with_nobody_to_ask_nothing_is_done_and_the_model_is_told(hands, in_job):
    look = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert look["code"] == "no_one_to_ask" and "nobody to ask" in look["error"]
    assert hands.ops("snapshot") == []


@pytest.mark.parametrize("label, kind", [("Pay now", "money"), ("Delete", "app_risky")])
async def test_money_and_risky_steps_ask_every_time_as_their_own_kinds(hands, asks, in_job, label, kind):
    seen, _ = asks
    hands.target = {**hands.target, "name": label}
    for _ in range(2):
        assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]
    assert [f["perm_kind"] for f in seen] == ["app", kind, kind]
    risky = [f for f in seen if f["perm_kind"] == kind]
    assert all(f["kind"] == "desktop_risky" and f["options"] == ["once"] for f in risky)
    assert hands.ops("click") == ["click", "click"]


async def test_a_high_reach_app_never_offers_always(hands, asks, in_turn):
    seen, _ = asks
    hands.apps = [*hands.apps, {"name": "Finder", "bundle_id": "com.apple.finder", "tier": "full"}]
    await hands_tools.DesktopLookExecutor().execute({"app": "Finder"})
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    finder, notes = seen
    assert "always" not in finder["options"] and finder["always_label"] == ""
    assert notes["options"] == ["task", "conversation", "always"] and notes["always_label"] == "Notes"


async def test_always_is_a_rule_the_next_conversation_reads_and_risky_steps_still_ask(hands, asks):
    seen, answer = asks
    answer["scope"] = "always"
    with pc.bind(pc.TaskMemoryContext(task_id="t1", run_id="r1", conversation_id="c1")):
        assert (await hands_tools.DesktopLookExecutor().execute({"app": "Notes"}))["ok"]
    answer["scope"] = None
    token = background_jobs._inside_job.set("job-2")
    try:
        with pc.bind(pc.TaskMemoryContext(task_id="t2", run_id="r2", conversation_id="c2")):
            assert (await hands_tools.DesktopClickExecutor().execute(CLICK))["ok"]
            hands.target = {**hands.target, "name": "Delete"}
            await hands_tools.DesktopClickExecutor().execute(CLICK)
    finally:
        background_jobs._inside_job.reset(token)
        hands_tools.forget_job("job-2")
    assert [f["perm_kind"] for f in seen] == ["app", "app_risky"]
    assert [a["bundle_id"] for a in await hands_service.always_apps()] == ["com.apple.Notes"]


async def test_every_decision_is_a_ledger_row_with_the_app(hands, asks, in_job):
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    await hands_tools.DesktopClickExecutor().execute(CLICK)
    async with db_session.AsyncSessionLocal() as db:
        rows = await permission_store.recent(db)
    rows = sorted(rows, key=lambda r: r.id)
    assert [(r.kind, r.decided_by, r.decision) for r in rows] == [("app", "user", "allow"), ("app", "grant", "allow")]
    assert rows[0].target == "com.apple.Notes" and rows[0].extra["app"] == "Notes"


@pytest.mark.parametrize("script, kind, apps", [
    ('tell application "Notes" to activate', "app", ["Notes"]),
    ('tell application "Reminders" to make new reminder with properties {name:"milk"}', "app", ["Reminders"]),
    ('tell application "Mail" to send message 1', "app_risky", ["Mail"]),
    ('tell application "Music" to buy track 1', "money", ["Music"]),
    ('do shell script "ls ~"', "app_risky", []),
    ('display dialog "hello"', "opaque", []),
])
def test_how_an_applescript_is_asked(script, kind, apps):
    assert hands_service.script_kind(script) == (kind, apps)


# The island answers an `app` card by its kind alone (0.1.61), no longer reading the script as
# approvals._RISKY_SCRIPT did. So every word that rule caught — and every other way a script reaches
# past the app it names — must make the card something the island does not answer.
_PAST_THE_APP = [
    'delete note 1', 'send message 1', 'move file "a" to folder "b"', 'do shell script "ls"',
    'purchase item 1', 'buy track 1', 'pay invoice 1', 'submit form 1', 'transfer funds', 'empty trash',
    'do script "ls"', 'run script "x"', 'load script file "x"', 'do JavaScript "x" in document 1',
    'execute javascript "x"', 'write text "ls"', 'keystroke "a"', 'key code 36',
    'DELETE note 1', 'Do Shell Script "ls"',
    # The same steps without those words (found reviewing D4, 0.1.63): a raw event, AppleScriptObjC,
    # Standard Additions writing a file.
    '«event sysoexec» "touch /tmp/x"', 'count notes\n«event sysoexec» "touch /tmp/x"',
    "current application's NSTask's launchedTaskWithLaunchPath:\"/usr/bin/touch\" arguments:{\"/tmp/x\"}",
    'count notes\nuse framework "Foundation"', 'open for access POSIX file "/tmp/x" with write permission',
    'write "a" to f', 'set eof f to 0',
]


@pytest.mark.parametrize("body", _PAST_THE_APP)
def test_a_script_that_deletes_sends_pays_or_reaches_past_its_app_is_never_an_app_card(body):
    kind, apps = hands_service.script_kind(f'tell application "Notes" to {body}')
    assert kind in ("app_risky", "money") and apps == ["Notes"], (body, kind)


@pytest.mark.parametrize("script", [
    'tell application "System Events" to tell process "Notes" to click button 1 of window 1',
    'tell application "Terminal" to activate', 'tell application "iTerm" to activate',
    'tell application "Finder" to get name of every window', 'tell application "Script Editor" to activate',
    'tell application id "com.apple.systemevents" to get name of every process',
    'tell application id "com.apple.terminal" to activate',
])
def test_a_script_for_an_app_that_reaches_every_other_app_is_asked_every_time(script):
    assert hands_service.script_kind(script)[0] == "app_risky"


async def test_a_risky_script_is_never_sent_as_an_app_card_and_asks_each_time(asks, in_job, monkeypatch):
    seen, _ = asks

    async def fake_run(argv, *, timeout=120):
        return {"ok": True, "external": True, "text": "done", "summary": "done"}
    monkeypatch.setattr(hands_tools, "_run", fake_run)
    scripts = ['tell application "Notes" to move note 1 to folder "Old"',
               'tell application "System Events" to keystroke "a"',
               'tell application "Terminal" to do script "ls"']
    for script in scripts * 2:
        assert (await hands_tools.MacAppleScriptExecutor().execute({"script": script}))["ok"]
    assert [f["perm_kind"] for f in seen] == ["app_risky"] * 6
    assert all(f["kind"] == "mac_script" and f["options"] == ["once"] for f in seen)


@pytest.mark.parametrize("past_the_app", [
    '«event sysoexec» "echo hi"',                                   # `do shell script`, raw
    'use framework "Foundation"\ncurrent application\'s NSTask\'s launchedTaskWithLaunchPath:"/bin/echo" arguments:{"hi"}',
    'set f to open for access POSIX file "/tmp/x" with write permission\nwrite "x" to f',
    '',                                                                       # a plain script too
])
async def test_no_grant_or_rule_for_an_app_stands_for_a_script(in_job, monkeypatch, past_the_app):
    """Release gate 0.1.61: an app's "Always" (what 0.1.60's Settings → Hands list becomes) and its "for
    this task" grant are Hands' — a script naming that app still needs its own card. With no card surface
    bound, needing one means it is not run."""
    ran = []

    async def fake_run(argv, *, timeout=120):
        ran.append(argv)
        return {"ok": True, "external": True, "text": "", "summary": ""}
    monkeypatch.setattr(hands_tools, "_run", fake_run)
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "app", "com.apple.Notes", label="Notes", created_from="migration")
        await permission_store.add_grant(db, "c1", "job-1", "app", "com.apple.Notes")
        await db.commit()
    script = 'tell application "Notes" to get name of every note\n' + past_the_app
    result = await hands_tools.MacAppleScriptExecutor().execute({"script": script})
    assert ran == [] and result["code"] == "no_one_to_ask", result


async def test_the_island_answers_hands_app_site_and_shortcut_cards_and_none_riskier(
        hands, asks, in_job, browser, monkeypatch):  # noqa: F811
    """0.1.61 §A4, from the Hands side: the island decides a card by its `perm_kind` alone. Every card
    Hands sends, made by the tools themselves, and whether the island may answer it."""
    from server.services import approvals
    seen, _ = asks

    async def fake_run(argv, *, timeout=120):
        return {"ok": True, "external": True, "text": "done", "summary": "done"}
    monkeypatch.setattr(hands_tools, "_run", fake_run)
    await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    await hands_tools.BrowserClickExecutor().execute({"element": "Star", "ref": "e1"})
    await hands_tools.MacRunShortcutExecutor().execute({"name": "Log water"})
    for script in ('tell application "Reminders" to count reminders', 'tell application "Reminders" to delete reminder 1',
                   'tell application "Music" to buy track 1', 'tell application "System Events" to keystroke "a"',
                   'display dialog "hello"'):
        await hands_tools.MacAppleScriptExecutor().execute({"script": script})
    for label in ("Pay now", "Delete"):
        hands.target = {**hands.target, "name": label}
        await hands_tools.DesktopClickExecutor().execute(CLICK)
    await hands_tools.DesktopTakeoverExecutor().execute({"why": "drag", "minutes": 5})
    answered = {(f["kind"], f["perm_kind"], approvals.island_may_answer(f)) for f in seen}
    assert answered == {
        ("desktop_app", "app", True), ("browser_site", "site", True), ("mac_shortcut", "shortcut", True),
        ("mac_script", "app_risky", False), ("mac_script", "money", False), ("mac_script", "opaque", False),
        ("desktop_risky", "money", False), ("desktop_risky", "app_risky", False),
        ("desktop_takeover", "takeover", False)}, sorted(answered)


@pytest.mark.parametrize("by, model_text, note, code, said, not_said", [
    ("user", "", "use the web version", "declined", "The user did not allow using Notes. They said: use the web version",
     "nobody to ask"),
    ("expired", "No answer came: this is NOT a refusal.", "", "no_answer", "NOT a refusal", "did not allow"),
    ("policy", "This run has nobody to ask.", "", "no_one_to_ask", "nobody to ask", "did not allow"),
    # §A6 (PR 7): the reviewer's own sentence (reason and way on) as it is, nothing added; with only a
    # note, the note and the way on.
    ("reviewer", "The reviewer (Approve for me) stopped this: Use Notes? Its reason: it deletes 40 notes. "
                 "Find a safer way to do what the user asked, or ask the user.", "", "reviewer_denied",
     "The reviewer (Approve for me) stopped this: Use Notes? Its reason: it deletes 40 notes. Find a safer way "
     "to do what the user asked, or ask the user.", "The user did not allow"),
    ("reviewer", "", "it deletes 40 notes", "reviewer_denied",
     "did not allow using Notes: it deletes 40 notes Find a safer way", "The user did not allow"),
    ("floor", "Money moves always need the user.", "", "not_allowed", "Money moves always need the user.",
     "nobody to ask"),
])
def test_each_kind_of_no_is_told_to_the_model_as_what_it_is(by, model_text, note, code, said, not_said):
    from server.services import permissions
    told = hands_tools._no(permissions.Decision(False, by, note=note, model_text=model_text), "using Notes")
    assert told["code"] == code and said in told["error"] and not_said not in told["error"], told
    if model_text:
        assert told["error"] == model_text, "permissions' own sentence, as it is (nothing added twice)"
