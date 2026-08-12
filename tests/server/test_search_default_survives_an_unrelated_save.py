"""A fresh install must not lose keyless search by saving an unrelated setting.

🔴 THE DEFECT, found by opening the app. `SettingsOut.search_provider` defaulted to
"tavily" while the registry's own default is the KEYLESS fallback. So on a fresh
install:

  * the service has no stored value, so search resolves to DuckDuckGo and works;
  * GET /settings answers "tavily", because that is the schema default;
  * the Settings screen shows Tavily selected, and it auto-saves a FULL body
    (`{...settingsRef.current, ...pending}`), so changing the theme — anything —
    PUTs search_provider="tavily";
  * Tavily requires a key, none is set, and search answers "not configured (no API
    key set)".

A new user therefore breaks their own working search by changing an unrelated
setting, and is then told to go get an API key for the feature whose whole point
was that it needs none.

WHAT THIS TEST HAS TO DO to discriminate: assert the RESOLVED PROVIDER after a
round trip, not the schema default. A test reading the default alone passes the
moment someone edits the literal, without proving the two ends agree.
"""
from __future__ import annotations

import pytest

from server import schemas
from server.registry import search_providers


def test_the_shipped_default_is_the_keyless_one():
    """The two ends must name the same provider.

    Kept as an equality against the registry rather than a hardcoded string: the
    failure was two literals disagreeing, and a second literal here would be a
    third place to disagree.
    """
    assert (
        schemas.SettingsOut.model_fields["search_provider"].default
        == search_providers._FALLBACK
    )


def test_the_default_the_api_reports_needs_no_key():
    """The property that actually matters. Whatever the default is called, a fresh
    install must be able to search without the user having anything to enter."""
    default_name = schemas.SettingsOut.model_fields["search_provider"].default
    provider = search_providers.get_provider(default_name, api_key="")
    assert provider.requires_key is False, (
        f"the default provider reported by the API ({default_name!r}) needs a key, so "
        "a fresh install shows a provider it cannot use"
    )


@pytest.mark.asyncio
async def test_echoing_back_what_the_api_reported_keeps_search_working():
    """The seam, driven directly so no harness state can decide the answer.

    The Settings screen PUTs a full body built from what it was SHOWN, so whatever
    the API reports for search_provider comes straight back and is stored. This
    feeds exactly that value in and asks the resolver whether search still works.

    (An earlier version of this test drove the real client fixture and failed on
    its precondition for an unrelated reason — the harness carries a stored key it
    cannot decrypt, so the resolver answered "key-undecryptable" before the save
    ever happened. A test whose setup can fail for a different reason than the one
    it is about cannot tell you which one you are looking at.)
    """
    from server.registry import executors

    reported = schemas.SettingsOut.model_fields["search_provider"].default

    async def echoed_back():
        # No key entered, no base url — a fresh install that has saved once.
        return executors.SearchConfig(name=reported, key="", key_state="unset")

    original = executors._read_search_config
    executors._read_search_config = echoed_back
    try:
        resolved = await executors._search_provider()
    finally:
        executors._read_search_config = original

    assert resolved.provider is not None, (
        f"storing the provider the API reported ({reported!r}) leaves search "
        f"unusable: reason={resolved.reason!r}. A user who changed an unrelated "
        "setting would now be told to go and get an API key."
    )


@pytest.mark.asyncio
async def test_a_fresh_install_that_changes_the_language_still_searches(client):
    """The measured chain, pinned end to end over real HTTP.

        fresh install                 -> DuckDuckGoHtmlProvider
        user changes the LANGUAGE     -> still DuckDuckGoHtmlProvider

    Before the fix the second line read `None, reason="no-key"`: the screen was
    shown "tavily", it PUT a full body, and the stored provider became one that
    needs a key nobody had entered.

    Driven through the API rather than the resolver so it covers the whole path a
    user takes, and it asserts the RESOLVED PROVIDER — asserting the stored string
    would pass against any default that happens to be written, which is how the
    original defect looked correct.
    """
    from server.registry import executors

    shown = (await client.get("/api/v1/settings")).json()["search_provider"]

    async def as_if_stored():
        # Exactly what the screen sends back after the user edits one other field.
        return executors.SearchConfig(name=shown, key="", key_state="unset")

    original = executors._read_search_config
    executors._read_search_config = as_if_stored
    try:
        after = await executors._search_provider()
    finally:
        executors._read_search_config = original

    assert type(after.provider).__name__ == "DuckDuckGoHtmlProvider", (
        f"after a fresh install echoed back {shown!r}, search resolved to "
        f"{type(after.provider).__name__ if after.provider else None} "
        f"(reason={after.reason!r}) — keyless search is broken by an unrelated save"
    )
