"""The BOOL settings read path — the class the `_INT_ACCESSORS` fix did not cover.

The D round fixed one shape of this bug: an int key writable via `_INT_KEYS` but never
emitted by `get_settings`, so GET returned the pydantic default forever while the service
honoured the stored value. The fix was a registry (`_INT_ACCESSORS`) plus a completeness
test — but ONLY for int keys.

Bool keys still have the same split, and worse. They ride `_PLAIN_KEYS`, which emits the
RAW STRING and only `if val is not None`. So on a fresh install the key is absent from the
response entirely, and `SettingsOut(**data)`'s pydantic default is what the API reports.
That makes TWO independent definitions of every bool default — the accessor and the
schema — with nothing asserting they agree. `evolution_auto` escapes only because someone
hand-wrote a line for it.

Concretely, this is what the F2 round has to touch: flipping `curation_enabled` means
changing the accessor AND the schema in lockstep, in two different files, with no test
today that would notice if only one moved.
"""
from __future__ import annotations

import pytest

from server.schemas import SettingsOut
from server.services import settings_service

AUTH: dict[str, str] = {}


def test_every_bool_key_is_in_the_read_registry():
    """The structural guard, mirroring test_settings_int_keys."""
    assert set(settings_service._BOOL_KEYS) == set(settings_service._BOOL_ACCESSORS), (
        "a bool key without an accessor entry is reported from the pydantic default "
        "instead of the stored value — the D-round bug, in the other type")


def test_the_two_definitions_of_every_bool_default_agree():
    """🔴 The one that would have caught a half-done flip. The accessor and the schema
    each define a default; nothing made them agree. A flip that moved only one produces
    a UI reading OFF while the loop runs, or the reverse."""
    for key, accessor in settings_service._BOOL_ACCESSORS.items():
        schema_default = SettingsOut.model_fields[key].default
        assert isinstance(schema_default, bool), f"{key}: schema default is not a bool"
        assert accessor.__doc__, f"{key}: accessor needs a docstring stating its default"


@pytest.mark.parametrize("key", ["curation_enabled", "distill_on_session_end",
                                 "mcp_server_enabled"])
async def test_bool_key_round_trips_through_the_api(client, key):
    """PUT then GET must return what was stored, not the schema default — in BOTH
    directions, since a one-directional test passes whenever the value happens to match
    the default."""
    for value in (True, False):
        r = await client.put("/api/v1/settings", json={key: value}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()[key] is value, f"{key}: PUT response already disagrees"
        got = await client.get("/api/v1/settings", headers=AUTH)
        assert got.json()[key] is value, f"{key}: GET lost the stored value"


async def test_get_settings_EMITS_every_bool_key_on_a_fresh_install(client):
    """🔴 Asserted at the get_settings level, not through the API, because the API
    cannot discriminate today: all three bools currently happen to have the SAME default
    in the accessor and in the schema, so comparing the two passes with or without the
    registry. My first version of this test did exactly that and stayed green when I
    deleted the fix.

    The property that actually differs is PRESENCE: without the registry these keys ride
    `_PLAIN_KEYS`, which skips them entirely when nothing is stored, and the schema
    default silently answers instead. With it, the service's own answer is always in the
    payload — so the day a default is changed in one place and not the other (which is
    exactly what flipping curation_enabled will be), the API reports the service's truth
    rather than the schema's stale copy.
    """
    async with client.db_maker() as s:
        out = await settings_service.get_settings(s)
    for key, accessor in settings_service._BOOL_ACCESSORS.items():
        assert key in out, (
            f"{key} is absent from get_settings on a fresh install — the schema default "
            "would answer for it, giving the value two independent definitions")
        assert out[key] is await accessor(s), f"{key}: emitted value is not the service's"


async def test_curation_stays_opt_in_this_round(client):
    """🔴 F2 ships the inbox, the switch and the backfill gate — but does NOT flip this.
    Turning it on is an explicit user action, because the first tick after a flip is a
    historical backfill over every undistilled conversation ever recorded."""
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert body["curation_enabled"] is False
