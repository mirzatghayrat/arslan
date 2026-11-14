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


async def _promoted(client, *, default: str, parent: list[str], child: str | None) -> dict:
    """The parent set through the mode route (`parent`, in order), its sub-session's own mode `child`; the parent is
    deleted keeping it. Returns the mode route's answer for the kept conversation, which reads as it did before."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=PARENT, kind="chat"))
        db.add(ConversationContext(id=CHILD, kind="sub", parent_id=PARENT, permission_mode=child))
        await db.commit()
    assert (await client.put("/api/v1/settings", json={"default_permission_mode": default})).status_code == 200
    for mode in parent:
        assert (await client.put(f"/api/v1/conversations/{PARENT}/permission-mode", json={"mode": mode})).status_code == 200
    url = f"/api/v1/conversations/{CHILD}/permission-mode"
    before = (await client.get(url)).json()["chosen"]
    assert (await permissions.mode_for(CHILD)).chosen == before
    got = await client.delete(f"/api/v1/conversations/{PARENT}?sub_sessions=keep")
    assert got.status_code == 200 and got.json()["kept"] == [CHILD]
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, CHILD)
        assert (row.kind, row.parent_id) == ("chat", None)
    after = (await client.get(url)).json()
    assert (await permissions.mode_for(CHILD)).chosen == after["chosen"] == before
    return after


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
    got = await _promoted(client, default="full_access", parent=["ask_risky"], child="ask")
    assert (got["own"], got["chosen"]) == ("ask", "ask")


async def test_a_parent_wider_than_the_default_still_reads_as_it_ran(client):
    """Guard: the parent was in full access and the default is "ask"; the kept conversation ran in full access, the
    user's own choice for that chain, and reads it after the delete as before."""
    got = await _promoted(client, default="ask", parent=["full_access"], child=None)
    assert (got["own"], got["chosen"], got["previous"]) == ("full_access", "full_access", None)
