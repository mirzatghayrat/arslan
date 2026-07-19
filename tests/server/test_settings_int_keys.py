"""The int-settings READ path — the touch point the "five touch points" rule misses.

An int setting needs: _INT_KEYS (write), an accessor (what the service reads),
SettingsIn, SettingsOut, and the consumer. That is five — and it is not enough. There
is a SIXTH: `get_settings()`, which used to hand-list its int keys. D5 wired all five
and forgot the sixth, so `brain_usage_event_retention_days` / `brain_usage_event_max_rows`
were WRITE-ONLY: PUT persisted them, the pruner honored them, and GET reported the
pydantic defaults forever.

Two concrete harms, both reproduced by the review that caught this:
  * a user sets retention to 0 (both gates off), gets a 200 saying 30/200000, and the
    append-only event table now grows without bound with no way to observe it;
  * a user sets 365, and the ordinary settings-form round-trip — GET the body, PUT it
    back — writes 30 over it and the next prune tick deletes 335 days of timeline.

The sibling key run_debug_retention_days had a test, but it only exercised the
ACCESSOR, never PUT -> GET through the API, which is exactly why it did not generalize.
These tests go through the API, and the completeness test makes the omission structural
rather than something the next person must remember.
"""
from __future__ import annotations

import pytest

AUTH: dict[str, str] = {}


def test_every_writable_int_key_is_also_readable():
    """The structural guard. A key writable but not readable is a one-way setting."""
    from server.services import settings_service

    assert set(settings_service._INT_KEYS) == set(settings_service._INT_ACCESSORS), (
        "every _INT_KEYS entry needs an _INT_ACCESSORS entry or GET /settings will "
        "silently report the pydantic default instead of the stored value")


def test_int_keys_are_declared_on_both_schemas():
    from server.schemas import SettingsIn, SettingsOut
    from server.services import settings_service

    for key in settings_service._INT_KEYS:
        assert key in SettingsIn.model_fields, f"{key} missing from SettingsIn"
        assert key in SettingsOut.model_fields, f"{key} missing from SettingsOut"


@pytest.mark.parametrize("key,value", [
    ("brain_usage_event_retention_days", 365),
    ("brain_usage_event_max_rows", 1_000_000),
    ("run_debug_retention_days", 7),
])
async def test_int_key_survives_a_put_then_get(client, key, value):
    """PUT then GET must return what was stored — not the schema default."""
    r = await client.put("/api/v1/settings", json={key: value}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()[key] == value, "the PUT response already lies about what was saved"

    got = await client.get("/api/v1/settings", headers=AUTH)
    assert got.json()[key] == value


async def test_the_settings_form_round_trip_does_not_revert_retention(client):
    """🔴 The actual harm. A client that GETs the settings body and PUTs it back — the
    standard form round-trip — must not silently rewrite a deliberate value with the
    default and delete the difference on the next prune tick."""
    await client.put("/api/v1/settings",
                     json={"brain_usage_event_retention_days": 365}, headers=AUTH)

    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    await client.put("/api/v1/settings",
                     json={"brain_usage_event_retention_days":
                           body["brain_usage_event_retention_days"]}, headers=AUTH)

    from server.services import settings_service

    async with client.db_maker() as s:
        # what the PRUNER actually reads — the only value that matters
        assert await settings_service.brain_usage_event_retention_days(s) == 365


async def test_disabling_the_gates_is_reported_truthfully(client):
    """Setting 0 disables a gate. That is allowed — but GET must SAY 0, so an operator
    can see that the event table is currently unbounded."""
    await client.put("/api/v1/settings",
                     json={"brain_usage_event_retention_days": 0,
                           "brain_usage_event_max_rows": 0}, headers=AUTH)
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert body["brain_usage_event_retention_days"] == 0
    assert body["brain_usage_event_max_rows"] == 0
