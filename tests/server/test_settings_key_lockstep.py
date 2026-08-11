"""`search_base_url` is registered everywhere it has to be.

WHY A KEY-SPECIFIC TEST WHEN A GENERAL GUARD EXISTS. `test_settings_plain_keys.py`
already closes the general hole, and closes it better than a second sweep would: it
requires every _PLAIN_KEYS entry to be on both schemas OR to carry a written reason
why accepting it from a client would be harmful. But it can only speak about keys
that ARE in _PLAIN_KEYS. Forgetting the key there entirely is silent — the sweep has
nothing to iterate over — so that half is asserted here.

🔴 An earlier draft of this file added its own sweep asserting that EVERY plain key
must be on both schemas. That premise is wrong: `curation_backfill_from` is written
by the curation loop, and putting it on the request schema would let a client move
the backfill boundary backwards and trigger a paid sweep over every conversation.
The guard would have forced a real defect. Deleted rather than exempted — the
existing test already states that hazard, with the reason attached.
"""
from __future__ import annotations

from server import schemas
from server.services import settings_service


def test_search_base_url_is_registered_in_all_three_places():
    """The github_token failure: on one side only, so the frontend sent it, the API
    accepted it, and nothing stored it. Every layer reported success."""
    assert "search_base_url" in settings_service._PLAIN_KEYS, (
        "missing from _PLAIN_KEYS — reads and writes never reach the KV table"
    )
    assert "search_base_url" in set(schemas.SettingsIn.model_fields), (
        "missing from SettingsIn — a PUT carrying it is dropped without an error"
    )
    assert "search_base_url" in set(schemas.SettingsOut.model_fields), (
        "missing from SettingsOut — it can be written but never read back, so the "
        "Settings page shows an empty field over a stored value"
    )


def test_search_base_url_defaults_to_empty_rather_than_a_guessed_address():
    """No default instance. A shipped default would be either a public SearXNG (which
    sends every query to a stranger's box) or a LAN address that is somebody else's
    machine on most networks."""
    assert schemas.SettingsOut.model_fields["search_base_url"].default == ""
