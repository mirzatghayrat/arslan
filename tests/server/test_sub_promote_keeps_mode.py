"""SUB5a follow-up: a sub-session kept when its parent is deleted ("keep") becomes an ordinary chat that runs in the
mode it ran under, never a wider one (`sub_sessions._promote`). A sub-session's mode is the narrowest along its chain
(S5a, `permissions._chosen`); once promoted it has no chain, so that mode is written onto its own row. In plan,
Start goes back to what the chain had before plan, never wider.

Each case is checked through `permissions.mode_for` and through the mode route, and the mode it reads after the
delete is the one it read before it."""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.services import background_jobs, permission_store, permissions, sub_sessions

PARENT, CHILD = "c-promote-parent", "c-promote-child"


@pytest.fixture(autouse=True)
def _fresh():
    for module in (background_jobs, sub_sessions, permission_store, permissions):
        module._reset_for_tests()
    yield
    for module in (background_jobs, sub_sessions, permission_store, permissions):
        module._reset_for_tests()


async def _put(client, conversation_id: str, *modes: str) -> None:
    for mode in modes:
        got = await client.put(f"/api/v1/conversations/{conversation_id}/permission-mode", json={"mode": mode})
        assert got.status_code == 200


async def _start(client, conversation_id: str) -> dict:
    return (await client.post(f"/api/v1/conversations/{conversation_id}/permission-mode/start")).json()


async def _reads_the_same(client, delete: str, *, kept: list[str], watched: list[str]) -> dict[str, dict]:
    """Deletes (`delete`, the route's query included) and checks each of `watched` reads, through `mode_for` and the
    mode route, the mode it read before. `kept` is what the delete promotes, each now an ordinary chat. Returns the
    mode route's answer for each of `watched` after the delete."""
    def url(cid: str) -> str:
        return f"/api/v1/conversations/{cid}/permission-mode"
    before = {cid: (await client.get(url(cid))).json()["chosen"] for cid in watched}
    for cid in watched:
        assert (await permissions.mode_for(cid)).chosen == before[cid]
    got = await client.delete(f"/api/v1/conversations/{delete}")
    assert got.status_code == 200 and got.json()["kept"] == kept
    async with db_session.AsyncSessionLocal() as db:
        for cid in kept:
            row = await db.get(ConversationContext, cid)
            assert (row.kind, row.parent_id) == ("chat", None)
    after = {cid: (await client.get(url(cid))).json() for cid in watched}
    for cid in watched:
        assert (await permissions.mode_for(cid)).chosen == after[cid]["chosen"] == before[cid]
    return after


async def _promoted(client, *, default: str, parent: list[str], child: str | None, child_puts: tuple = ()) -> dict:
    """The parent set through the mode route (`parent`, in order), its sub-session's own mode `child`, then set
    through the route (`child_puts`); the parent is deleted keeping it. Returns the mode route's answer for the kept
    conversation, which reads as it did before."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=PARENT, kind="chat"))
        db.add(ConversationContext(id=CHILD, kind="sub", parent_id=PARENT, permission_mode=child))
        await db.commit()
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": default})).status_code == 200
    await _put(client, PARENT, *parent)
    await _put(client, CHILD, *child_puts)
    return (await _reads_the_same(client, f"{PARENT}?sub_sessions=keep", kept=[CHILD], watched=[CHILD]))[CHILD]


async def test_a_parent_in_plan_leaves_it_in_plan_and_start_goes_back_to_the_parents_mode_before_plan(client):
    """The default is full access; the parent was in "ask" and went into plan. The kept conversation stays in plan,
    and its Start goes back to "ask", not to the default."""
    got = await _promoted(client, default="full_access", parent=["ask", "plan"], child=None)
    assert (got["own"], got["chosen"], got["previous"]) == ("plan", "plan", "ask")
    started = (await client.post(f"/api/v1/conversations/{CHILD}/permission-mode/start")).json()
    assert (started["own"], started["chosen"]) == ("ask", "ask")
    assert (await permissions.mode_for(CHILD)).chosen == "ask"


async def test_start_never_widens_past_the_sub_sessions_own_narrower_mode_before_plan(client):
    """The parent went into plan from the default (full access) while its sub-session had chosen "ask only when
    risky": before plan, the chain ran in "ask only when risky", and that is where Start goes."""
    got = await _promoted(client, default="full_access", parent=["plan"], child="ask_risky")
    assert (got["own"], got["chosen"], got["previous"]) == ("plan", "plan", "ask_risky")
    started = (await client.post(f"/api/v1/conversations/{CHILD}/permission-mode/start")).json()
    assert (started["own"], started["chosen"]) == ("ask_risky", "ask_risky")


async def test_a_parent_in_ask_leaves_it_in_ask(client):
    got = await _promoted(client, default="full_access", parent=["ask"], child=None)
    assert (got["own"], got["chosen"], got["previous"]) == ("ask", "ask", None)


async def test_a_sub_session_narrower_than_its_parent_keeps_its_own(client):
    """The sub-session chose "ask" after a plan it entered from full access, so its row still holds full access as
    the mode before plan. Promoted, it keeps its own "ask", and nothing wider is left on the row for a later Start:
    the mode before plan is only kept while in plan."""
    got = await _promoted(client, default="full_access", parent=["ask_risky"], child=None,
                          child_puts=("full_access", "plan", "ask"))
    assert (got["own"], got["chosen"], got["previous"]) == ("ask", "ask", None)


async def test_a_broken_chain_under_plan_stays_in_plan(client):
    """The sub-session's parent is itself a sub-session whose parent row is gone: the chain isn't whole. The parent
    is in plan, so the sub-session ran in plan; promoted, it stays in plan, not "ask". Its Start goes no wider than
    "ask" (the parent entered plan from the full-access default)."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=PARENT, kind="sub", parent_id="c-promote-missing"))
        db.add(ConversationContext(id=CHILD, kind="sub", parent_id=PARENT))
        await db.commit()
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": "full_access"})).status_code == 200
    await _put(client, PARENT, "plan")
    got = (await _reads_the_same(client, f"{PARENT}?sub_session=true&sub_sessions=keep", kept=[CHILD],
                                 watched=[CHILD]))[CHILD]
    assert (got["own"], got["chosen"], got["previous"]) == ("plan", "plan", "ask")
    started = await _start(client, CHILD)
    assert (started["own"], started["chosen"]) == ("ask", "ask")
    assert (await permissions.mode_for(CHILD)).chosen == "ask"


async def test_a_nested_kept_chain_keeps_the_narrowest_along_each_chain(client):
    """Grandparent -> parent -> sub-session. The grandparent went into plan from "ask only when risky"; the parent
    has no mode of its own; the sub-session chose "ask". The grandparent is deleted keeping the parent, then the
    parent keeping the sub-session. Each promoted row stays in plan; Start goes back to the narrowest before plan
    along its own chain: "ask only when risky" for the parent, "ask" for the sub-session."""
    grand = "c-promote-grand"
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=grand, kind="chat"))
        db.add(ConversationContext(id=PARENT, kind="sub", parent_id=grand))
        db.add(ConversationContext(id=CHILD, kind="sub", parent_id=PARENT, permission_mode="ask"))
        await db.commit()
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": "full_access"})).status_code == 200
    await _put(client, grand, "ask_risky", "plan")
    got = await _reads_the_same(client, f"{grand}?sub_sessions=keep", kept=[PARENT], watched=[PARENT, CHILD])
    assert (got[PARENT]["own"], got[PARENT]["chosen"], got[PARENT]["previous"]) == ("plan", "plan", "ask_risky")
    assert (got[CHILD]["own"], got[CHILD]["chosen"]) == ("ask", "plan")
    got = await _reads_the_same(client, f"{PARENT}?sub_sessions=keep", kept=[CHILD], watched=[CHILD])
    assert (got[CHILD]["own"], got[CHILD]["chosen"], got[CHILD]["previous"]) == ("plan", "plan", "ask")
    started = await _start(client, CHILD)
    assert (started["own"], started["chosen"]) == ("ask", "ask")


async def test_a_sub_session_in_plan_under_a_wider_parent_starts_no_wider_than_its_chain(client):
    """The parent is in "ask only when risky"; the sub-session went into plan from full access, wider than its
    parent. Promoted, it stays in plan, and Start goes to what the chain ran before plan: "ask only when risky"."""
    got = await _promoted(client, default="full_access", parent=["ask_risky"], child=None,
                          child_puts=("full_access", "plan"))
    assert (got["own"], got["chosen"], got["previous"]) == ("plan", "plan", "ask_risky")
    started = await _start(client, CHILD)
    assert (started["own"], started["chosen"]) == ("ask_risky", "ask_risky")


@pytest.mark.parametrize(("child", "child_previous", "expected"), [
    (None, None, ("ask", "ask", None)),
    ("plan", "full_access", ("plan", "plan", "ask")),
])
async def test_an_invalid_stored_mode_in_the_chain_reads_ask(client, child, child_previous, expected):
    """The parent's stored mode isn't a mode (written straight to the database): it reads "ask", and a narrower
    readable mode along the chain narrows it further. In plan, Start goes no wider than that "ask"."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=PARENT, kind="chat", permission_mode="not-a-mode"))
        db.add(ConversationContext(id=CHILD, kind="sub", parent_id=PARENT, permission_mode=child,
                                   previous_mode=child_previous))
        await db.commit()
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": "full_access"})).status_code == 200
    got = (await _reads_the_same(client, f"{PARENT}?sub_sessions=keep", kept=[CHILD], watched=[CHILD]))[CHILD]
    assert (got["own"], got["chosen"], got["previous"]) == expected


async def test_a_parent_wider_than_the_default_still_reads_as_it_ran(client):
    """Guard: the parent was in full access and the default is "ask"; the kept conversation ran in full access, the
    user's own choice for that chain, and reads it after the delete as before."""
    got = await _promoted(client, default="ask", parent=["full_access"], child=None)
    assert (got["own"], got["chosen"], got["previous"]) == ("full_access", "full_access", None)
