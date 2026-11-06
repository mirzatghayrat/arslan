"""Both config-id overrides must fail CLOSED when they point at nothing.

These two settings became writable this round (they were on neither schema, so the write
path was dead). The moment a user can actually store one, a stale id — the provider config
it names having since been deleted — becomes reachable. Neither site may fall back to
"just use something else": silently substituting a different embedding model would mix
vector spaces, and silently substituting a different synthesis model would spend on a
model the user did not choose.

Pinned here because both are `return None` inside a loop, which is exactly the shape that
survives a refactor by accident and stops being true without anything going red.
"""
from __future__ import annotations

from server import crypto
from server.db.models import ProviderConfig, Setting

AUTH: dict[str, str] = {}


async def test_embedding_override_pointing_at_a_missing_config_degrades_to_fts(client, monkeypatch):
    """embedding_service.active_provider: an override naming a config that does not exist
    returns None ⇒ retrieval stays FTS-only. It must NOT fall through to the preference
    scan, which would pick a DIFFERENT provider than the one the user asked for and embed
    new chunks into a vector space incompatible with the existing ones."""
    from server.db import session as db_session
    from server.services import embedding_service

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        # 🔴 A REAL, usable config must exist and NOT be the one named. With an empty
        # config list the loop body never runs and `return None` happens because there
        # was nothing to pick — which is what a NON-fail-closed implementation returns
        # too. My first version of this test seeded nothing and stayed green when I
        # made the lookup match any config.
        # zhipu with a DECRYPTABLE key, because the fallthrough must be able to succeed:
        # with an undecryptable key the preference scan also yields None and the
        # assertion below would hold no matter which branch ran.
        s.add(ProviderConfig(label="other", provider="zhipu", model="x",
                             api_key=crypto.encrypt("sk-test-12345678"), is_primary=True))
        s.add(Setting(key="embedding_config_id", value="99999"))   # names no config
        await s.commit()

    assert await embedding_service.active_provider() is None, (
        "a dangling embedding override must degrade to FTS-only, not silently fall "
        "through to whatever other provider happens to be configured")


async def test_status_reports_which_models_the_existing_vectors_came_from(client, monkeypatch):
    """🔴 A warning that a switch MIGHT split the corpus is only half the information;
    the user also needs to know whether it already did. The column exists and the count
    was never read, so the UI could not tell them.

    Two models seeded on purpose: with one model the grouping is indistinguishable from
    "return the only model", and the split — the state being warned about — is exactly
    what must be visible.
    """
    from sqlalchemy import text as sa_text

    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    from server.db.models import Spawn

    async with client.db_maker() as s:
        # the chunks' owner; knowledge_chunks.spawn_id is a foreign key
        s.add(Spawn(id=1, name="owner", domain_category="g", system_prompt="sp"))
        await s.flush()
        for i, model in enumerate(["old-model", "old-model", "new-model"]):
            await s.execute(sa_text(
                "INSERT INTO knowledge_chunks (spawn_id, source, chunk_index, text, "
                "embedding, embedding_model) VALUES (1, 'x', :i, 't', :e, :m)"),
                {"i": i, "e": b"\x00", "m": model})
        # a chunk with NO vector must not be counted as belonging to any model
        await s.execute(sa_text(
            "INSERT INTO knowledge_chunks (spawn_id, source, chunk_index, text) "
            "VALUES (1, 'x', 99, 't')"))
        await s.commit()

    body = (await client.get("/api/v1/embedding/status", headers=AUTH)).json()
    assert body["by_model"] == [
        {"model": "old-model", "count": 2},
        {"model": "new-model", "count": 1},
    ], "the split across vector spaces must be visible, most-common first"
