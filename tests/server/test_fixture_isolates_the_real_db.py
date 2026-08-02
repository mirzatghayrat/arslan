"""The shared test client must never be able to touch the user's real database.

Found while adding the conversation listing: the shared `client` fixture
overrode the `get_session` DEPENDENCY but not `db_session.AsyncSessionLocal`,
so any endpoint that opened its own session read and wrote the real database.
On this machine that is the user's live packaged app. The new endpoint was
caught doing it — it returned the user's own conversations — and
`delete_conversation` sits on the same path, so a DELETE test whose id happened
to collide with a real `thread-<epoch>` would have purged real rows.

Nothing was lost: test ids look like "conv-x" and real ones like
"thread-1785600881705", so they never collided. That is luck of naming, not a
safeguard, which is why this file exists.
"""
from __future__ import annotations

import pathlib


async def test_the_shared_client_isolates_the_session_global(client):
    """⓪ + the assertion in one: prove the global is NOT the app default."""
    from server.db import session as db_session

    # The fixture's maker is exposed for direct DB access; the global must be it.
    assert db_session.AsyncSessionLocal is client.db_maker, (
        "the shared client leaves db_session.AsyncSessionLocal pointing at the "
        "real database — endpoints that open their own session escape the test DB"
    )


async def test_writes_through_an_endpoint_land_in_the_temp_db(client):
    """Discriminating: comparing identities could pass while a *copy* of the
    maker still pointed elsewhere. This proves the round trip."""
    from server.db.models import ArslanMessage

    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id="isolated-probe", role="user", content="hi"))
        await db.commit()

    rows = (await client.get("/api/v1/conversations")).json()
    assert [r["conversation_id"] for r in rows] == ["isolated-probe"], rows


def test_the_fixture_says_why_in_writing():
    """A guard whose reason lives only in a commit message gets undone."""
    src = pathlib.Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")
    assert "_patch_session_global" in src
    assert "AsyncSessionLocal" in src
