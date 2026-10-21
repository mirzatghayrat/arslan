"""S1 (U14 a): a run with nobody to ask uses no standing yes (card S1; ⓪Plan's Q2 and (iii)).

A scheduled run binds no card surface (`permissions.asking_with`). Before S1, `decide` read the rules
("Always") and the task and conversation grants first and asked only after: an "Always" app rule let a
scheduled run act in that app with nobody there (up to Hands' five steps). Now, with no surface, nothing
standing answers. `decide` and `decide_many` both go straight to a policy refusal and its ledger row, and
that row records no "Always" set, so the Inbox never offers an "Always" that would read as fixing the
scheduled run; its words say to do it in a chat.
"""
import pytest

from server.db import session as db_session
from server.services import permission_store, permissions
from server.services.permissions import Context, Request

CTX = Context(conversation_id="conv-1", task_id="turn-1")


class Asker:
    def __init__(self, *answers):
        self.answers, self.frames = list(answers), []

    async def __call__(self, frame):
        self.frames.append(frame)
        return self.answers.pop(0)


def yes(scope):
    return {"approved": True, "scope": scope, "note": "", "by": "mac"}


def app(bundle="com.apple.Notes"):
    return Request(kind="app", target=bundle, title="Use Notes?", always_label="Notes")


@pytest.fixture(autouse=True)
def _fresh(execution_db):
    permission_store._reset_for_tests()
    permissions._reset_for_tests()
    yield


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


async def test_an_always_rule_does_not_answer_when_nobody_can_be_asked():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    d = await permissions.decide(app(), Context(conversation_id="conv-9", task_id="t9"))
    assert (d.allowed, d.by) == (False, "policy")
    assert "scheduled run never takes such a step" in d.model_text and "in a chat" in d.model_text


async def test_a_conversation_grant_does_not_answer_when_nobody_can_be_asked():
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)
    d = await permissions.decide(app(), CTX)
    assert (d.allowed, d.by) == (False, "policy")


async def test_decide_many_ignores_rules_and_grants_too():
    """⓪Plan (iii): decide_many reads the store itself, so it needs the same check."""
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    decisions = await permissions.decide_many([app("com.apple.Notes"), app("com.apple.mail")], CTX, title="Use 2 apps?")
    assert [(d.allowed, d.by) for d in decisions] == [(False, "policy"), (False, "policy")]


async def test_an_unattended_refusal_offers_no_always_in_the_inbox():
    d = await permissions.decide(app(), CTX)
    assert d.by == "policy"
    [row] = [r for r in await _rows() if r.decided_by == "policy"]
    assert (row.kind, row.decision) == ("app", "deny")
    assert not (row.extra or {}).get(permissions.ALWAYS_KEY)


async def test_with_a_surface_rules_and_grants_still_answer():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    with permissions.asking_with(Asker()):                   # no answers left: must not ask
        d = await permissions.decide(app(), Context(conversation_id="conv-9", task_id="t"))
    assert (d.allowed, d.by) == (True, "rule")
