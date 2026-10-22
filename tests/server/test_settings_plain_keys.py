"""The PLAIN (string-on-the-wire) settings read path — the last uncovered shape.

`test_settings_int_keys` guards int keys, `test_settings_bool_keys` guards bool keys.
Both grew out of the same defect: a key writable in one place and read in another, with
two independent definitions of its default and nothing asserting they agree.

The key that first fell through both was `evolution_auto` (a bool in the service, a STRING
on the wire). C2b-2 removed it; the guard stays for every other plain key, because the
failure is the same: the accessor default (settings_service) and the schema default
(SettingsOut) disagree, and a half-done flip shows one state in the UI while the server
runs the other.
"""
from __future__ import annotations

from server.schemas import SettingsIn, SettingsOut
from server.services import settings_service

AUTH: dict[str, str] = {}

# Keys that ride _PLAIN_KEYS but must NOT appear on the request schema.
#
# 🔴 This list is a hazard statement, not a convenience. Every entry needs a reason why
# accepting it from a client would be actively harmful — "it is internal" is not enough
# on its own, because the next reader will use that as licence to add anything.
PLAIN_KEYS_NOT_USER_SETTABLE = {
    "curation_backfill_from": (
        "The curation loop's backfill boundary, written by ensure_backfill_boundary when "
        "the loop is switched on. Accepting it from a client would let anyone move the "
        "boundary BACKWARDS, which re-triggers a distillation sweep over every "
        "conversation after that instant — a mass historical backfill that spends money "
        "per conversation. That sweep is precisely what the F2 boundary gate exists to "
        "prevent, so exposing the knob would hand out a bypass for it. Harmful, not "
        "merely internal."
    ),
}


def test_every_plain_key_is_declared_or_explicitly_exempt():
    """🔴 The exemption list must be CLOSED.

    A test that only checks "declared keys are declared" lets the next internal key slip
    through silently — it would move the hole rather than close it. So the assertion runs
    the other way: every _PLAIN_KEYS entry must be EITHER on both schemas OR carry a
    written reason here. There is no third state.
    """
    for key in settings_service._PLAIN_KEYS:
        exempt = key in PLAIN_KEYS_NOT_USER_SETTABLE
        on_in = key in SettingsIn.model_fields
        on_out = key in SettingsOut.model_fields
        if exempt:
            assert not on_in, (
                f"{key} is listed as not-user-settable but IS on SettingsIn — the "
                "exemption is a lie; either remove it from the list or from the schema")
            assert PLAIN_KEYS_NOT_USER_SETTABLE[key].strip(), (
                f"{key}: an exemption without a stated reason is just a suppressed test")
            continue
        assert on_in, (
            f"{key} is writable via _PLAIN_KEYS but absent from SettingsIn — either "
            f"declare it, or add it to PLAIN_KEYS_NOT_USER_SETTABLE with the reason "
            f"accepting it would be harmful")
        assert on_out, (
            f"{key} is absent from SettingsOut — GET would report nothing for a key the "
            f"service honours")


def test_exemptions_name_real_keys():
    """An exemption for a key that no longer exists is dead weight that hides the next
    real gap behind a passing test."""
    for key in PLAIN_KEYS_NOT_USER_SETTABLE:
        assert key in settings_service._PLAIN_KEYS, (
            f"{key} is exempted but is not in _PLAIN_KEYS — stale exemption")


async def test_config_id_keys_round_trip(client):
    """🔴 The write path was DEAD for these two: they rode _PLAIN_KEYS (so
    update_settings would have stored them) but were on neither schema, and the PUT route
    passes `body.model_dump()` — pydantic dropped them before the service ever saw them.
    The frontend has been sending embedding_config_id all along (adapters.ts) and the
    value silently went nowhere.

    Asserted through the API in both directions, because that is the path that was broken;
    a service-level test would have passed the whole time.
    """
    for key in ("synthesis_config_id", "embedding_config_id"):
        for value in ("7", ""):
            r = await client.put("/api/v1/settings", json={key: value}, headers=AUTH)
            assert r.status_code == 200, r.text
            assert r.json()[key] == value, f"{key}: PUT response already lost it"
            got = await client.get("/api/v1/settings", headers=AUTH)
            assert got.json()[key] == value, f"{key}: GET lost the stored value"
