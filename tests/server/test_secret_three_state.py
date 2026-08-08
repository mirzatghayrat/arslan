"""Every stored secret reports one of three states, and the seam is tested.

THE STATES. `unset` (nobody ever entered one), `set` (there and readable),
`undecryptable` (STORED, but this process cannot open it). Collapsing the third into
the first is the defect this whole spec exists for: the app told its own author "no
API key set" for a month while the key sat in the database, because the salt had
changed and `_safe_decrypt` returns "" on InvalidToken.

Provider configs already got this right — `_key_status` and the UI that reads it.
This propagates the same vocabulary to the settings-level secrets rather than
inventing a second one.

🔴 AND IT TESTS THE SEAM, because that is where this family of defect lives. While
writing it: `github_token` is in `_SECRET_KEYS`, so update_settings encrypts it and
get_settings masks it — and it appeared on NEITHER pydantic schema, so the PUT route's
`body.model_dump()` silently dropped it going in and `SettingsOut(**data)` dropped it
coming out. The frontend sends it correctly and has its own passing tests saying so.
Two sides each tested in isolation, the seam between them untested, and a settings
field that looked saveable and was not.

schemas.py:29-34 documents the same thing happening to synthesis_config_id and
embedding_config_id. That comment was written by someone who had just been bitten;
this is the third instance. So the round-trip test below covers ALL of _SECRET_KEYS,
derived from the tuple rather than listed, because a hand-written list is how the
third instance became possible.
"""
from __future__ import annotations

import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import settings_service as ss

# main.py:348 mounts this router under /api/v1. Spelled out once, as a constant:
# posting to a wrong path is how an earlier test in this session went green on a
# 404, and the guard below makes that impossible to repeat quietly.
SETTINGS = "/api/v1/settings"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import server.config as config

    importlib.reload(config)

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.db_maker = maker  # type: ignore[attr-defined]
        yield c
    await eng.dispose()


class TestTheSeamNoSchemaSilentlyDropsASecret:
    @pytest.mark.parametrize("key", ss._SECRET_KEYS)
    async def test_every_secret_key_round_trips_through_put_then_get(self, client, key):
        # Derived from _SECRET_KEYS, not hand-listed: a hand-written list is exactly
        # how github_token came to be missing from both schemas while the frontend
        # sent it and its own tests passed.
        value = f"secret-value-for-{key}"

        put = await client.put(SETTINGS, json={key: value})
        assert put.status_code != 404, f"{SETTINGS} not found — this test would prove nothing"
        assert put.status_code == 200, put.text

        async with client.db_maker() as db:
            assert await ss.get_decrypted(db, key) == value, (
                f"{key} did not reach the database — check that it is on BOTH "
                f"SettingsIn and SettingsOut"
            )

    @pytest.mark.parametrize("key", ss._SECRET_KEYS)
    async def test_every_secret_key_comes_back_masked_on_get(self, client, key):
        await client.put(SETTINGS, json={key: "NOT-A-REAL-KEY-0000"})

        got = (await client.get(SETTINGS)).json()

        assert key in got, f"{key} is absent from the GET response"
        assert got[key] == "NO...0000", got[key]


class TestThreeStatesAreReported:
    @pytest.mark.parametrize("key", ss._SECRET_KEYS)
    async def test_unset_when_never_entered(self, client, key):
        got = (await client.get(SETTINGS)).json()
        assert got[f"{key}_status"] == "unset"

    @pytest.mark.parametrize("key", ss._SECRET_KEYS)
    async def test_set_after_entering_one(self, client, key):
        await client.put(SETTINGS, json={key: "NOT-A-REAL-KEY-0000"})

        got = (await client.get(SETTINGS)).json()

        assert got[f"{key}_status"] == "set"

    @pytest.mark.parametrize("key", ss._SECRET_KEYS)
    async def test_undecryptable_is_not_reported_as_unset(self, client, key, monkeypatch):
        # THE case. Ciphertext this process cannot open must not read as "never set" —
        # that is the sentence that sent someone looking for an unfilled field for a
        # month while the value sat right there.
        from server.db.models import Setting

        async with client.db_maker() as db:
            db.add(Setting(key=key, value="gAAAAABnot-openable-by-anyone"))
            await db.commit()

        got = (await client.get(SETTINGS)).json()

        assert got[f"{key}_status"] == "undecryptable"
        # And the masked field must NOT look like a healthy key.
        assert got[key] == "", "an unopenable secret was rendered as if it were fine"

    async def test_the_status_fields_are_derived_from_the_registry(self):
        # Structural: the emitted set must equal _SECRET_KEYS, so adding a fourth
        # secret cannot leave a state field behind. (Membership in a tuple, not a
        # grep — this asserts a value, not the presence of text.)
        assert ss._SECRET_STATE_KEYS == tuple(f"{k}_status" for k in ss._SECRET_KEYS)

    async def test_status_fields_cannot_be_written_back(self, client):
        # The GET→PUT round-trip sends the whole body back. A client echoing
        # "..._status" must not create a settings row for it.
        body = (await client.get(SETTINGS)).json()
        await client.put(SETTINGS, json=body)

        async with client.db_maker() as db:
            for status_key in ss._SECRET_STATE_KEYS:
                raw = await ss._get_raw(db, status_key)
                assert raw is None, f"{status_key} was persisted as a setting"


class TestTheSharedPredicate:
    def test_provider_configs_use_the_same_function(self):
        # One vocabulary, not two. provider_config_service had this first; it must now
        # delegate rather than keep a second copy that can drift.
        from server.services import provider_config_service as pcs
        from server.services import secret_state

        assert pcs._key_status is secret_state.secret_state

    @pytest.mark.parametrize("stored,expected", [
        (None, "unset"),
        ("", "unset"),
        ("gAAAAABnot-openable", "undecryptable"),
    ])
    def test_states_for_raw_stored_values(self, stored, expected):
        from server.services.secret_state import secret_state

        assert secret_state(stored) == expected

    def test_a_readable_value_is_set(self):
        from server import crypto
        from server.services.secret_state import secret_state

        assert secret_state(crypto.encrypt("anything")) == "set"

    def test_ciphertext_of_an_empty_string_is_unset_not_set(self):
        # Storing "" encrypted is how a cleared key looks. Reporting that as `set`
        # would put a mask on an empty field.
        from server import crypto
        from server.services.secret_state import secret_state

        assert secret_state(crypto.encrypt("")) == "unset"


class TestTheFifthStoragePointMcpEnv:
    """MCPServer.env — the storage point whose failure is the most misleading.

    An unreadable env decodes to ``{}``, which is indistinguishable from "this server
    never needed credentials". The server is then started WITHOUT its API key and fails
    with whatever the remote service says about a missing token — a symptom that points
    at the remote service, at the network, at anything except the salt.

    🔴 Nothing renders env_status yet. That is deliberate scope (the frontend is a later
    step) and it is stated here rather than implied, because catalog.py's `containment`
    field was added, shipped to the API, and never rendered — adding a field is free,
    rendering it is the whole job.
    """

    @staticmethod
    def _dict_for(env_value):
        from server.db.models import MCPServer
        from server.services.mcp_service import _to_dict

        return _to_dict(MCPServer(id=1, label="m", command="echo", args=[],
                                  transport="stdio", status="registered", env=env_value))

    def test_no_env_is_unset(self):
        assert self._dict_for(None)["env_status"] == "unset"

    def test_a_readable_env_is_set(self):
        import json

        from server import crypto

        row = self._dict_for(crypto.encrypt(json.dumps({"BRAVE_API_KEY": "bsk-1"})))
        assert row["env_status"] == "set"

    def test_an_unreadable_env_is_not_reported_as_absent(self):
        row = self._dict_for("gAAAAABnot-openable-by-anyone")

        assert row["env_status"] == "undecryptable"
        # The masked env is still {} — that part is unchanged and correct, which is
        # exactly why the status field has to carry the distinction.
        assert row["env"] == {}
