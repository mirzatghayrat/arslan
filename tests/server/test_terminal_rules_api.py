"""0.1.48 Settings: list the commands the user said not to ask about again, and forget one."""
from server.db import session as db_session
from server.services import terminal_policy as tp
from tests.server.test_proactive_api import client  # noqa: F401 — token-protected app client


async def test_lists_remembered_rules_in_the_cards_words_and_forgets_one(client):  # noqa: F811
    async with db_session.AsyncSessionLocal() as db:
        await tp.allow_always(db, "install")
        await tp.allow_always(db, "hermes:recursive delete")
    body = (await client.get("/api/v1/settings/terminal-rules")).json()
    assert body["rules"] == [
        {"rule": "hermes:recursive delete", "description": "recursive delete"},
        {"rule": "install", "description": "installs software"},
    ]
    after = (await client.delete("/api/v1/settings/terminal-rules",
                                 params={"rule": "hermes:recursive delete"})).json()
    assert [r["rule"] for r in after["rules"]] == ["install"]
    async with db_session.AsyncSessionLocal() as db:
        assert await tp.always_allowed(db) == {"install"}


def test_describe_falls_back_to_the_rule_itself():
    assert tp.describe("git-push") == "publishes to a remote repository"
    assert tp.describe("something-else") == "something-else"
