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

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan

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
    ('tell application "Mail" to send message 1', "app_risky", ["Mail"]),
    ('tell application "Music" to buy track 1', "money", ["Music"]),
    ('do shell script "ls ~"', "app_risky", []),
    ('display dialog "hello"', "opaque", []),
])
def test_how_an_applescript_is_asked(script, kind, apps):
    assert hands_service.script_kind(script) == (kind, apps)
