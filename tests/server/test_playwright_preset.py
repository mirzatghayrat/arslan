"""Playwright as a preset connector: hand-graded, contained, honestly described.

Three things the brief made non-negotiable, and each is here because the
obvious implementation gets it wrong:

  1. TIERS ARE ASSIGNED BY HAND. The heuristic is a verb list, and not one of
     snapshot / click / navigate / type is in it — so every playwright tool,
     including the purely observational ones, comes back "orchestrator" and the
     toolset has no safe tool to assign. Verified below rather than asserted.

  2. CONTAINMENT IS IN THE ARGS. A note telling the user to be careful is not
     containment. --isolated means the browser starts with no cookies and none
     of their signed-in accounts, every time, whether or not anyone remembers.

  3. THE DESCRIPTION DOES NOT OVERSELL. Action tools start restricted, so the
     connector must not read as though it can drive anything out of the box.
"""
from __future__ import annotations

import pytest

from server.mcp import catalog
from server.mcp.discovery import suggest_tier, suggested_tier_for


class _Server:
    def __init__(self, args):
        self.args = args


PLAYWRIGHT = _Server(["-y", "@playwright/mcp@latest", "--isolated"])
MEMORY = _Server(["-y", "@modelcontextprotocol/server-memory"])


def test_the_preset_exists_and_is_one_click():
    c = catalog.find_connector("playwright")
    assert c is not None, "playwright is not in the preset catalog"
    assert c["one_click"] is True, "playwright needs no credentials; it must be one-click"


def test_containment_is_in_the_launch_arguments():
    """Not in a note, not in documentation — in the command that runs."""
    c = catalog.find_connector("playwright")
    assert "--isolated" in c["args"], (
        "without --isolated the browser reuses the default profile, which means "
        "the user's logged-in sessions. That is a different product decision "
        "than the one this preset was approved for.")
    assert c.get("containment"), "the containment choice must be stated to the user"


# ---------------------------------------------------------------------------
# (0) The premise. If the heuristic already graded these correctly, the manual
# table would be dead weight and every test below would prove nothing.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "browser_snapshot", "browser_console_messages", "browser_take_screenshot"])
def test_the_heuristic_alone_would_call_every_observer_unsafe(tool):
    assert suggest_tier(tool) == "orchestrator", (
        f"{tool} is now graded by the heuristic — re-check whether the manual "
        "table is still needed before trusting it")


@pytest.mark.parametrize("tool", [
    "browser_snapshot", "browser_take_screenshot", "browser_console_messages",
    "browser_network_requests", "browser_tabs"])
def test_observers_are_graded_safe(tool):
    assert suggested_tier_for(PLAYWRIGHT, tool) == "safe"


@pytest.mark.parametrize("tool", [
    "browser_click", "browser_type", "browser_fill_form", "browser_navigate",
    "browser_evaluate", "browser_file_upload", "browser_press_key"])
def test_anything_that_acts_starts_restricted(tool):
    """The discriminating half. A table that graded everything safe would pass
    the observers test and hand a spawn the ability to click through a page."""
    assert suggested_tier_for(PLAYWRIGHT, tool) == "orchestrator"


def test_an_ungraded_tool_from_a_graded_server_is_never_handed_to_the_heuristic():
    """The sharp edge, found by writing this test.

    New playwright releases add tools. If an ungraded one fell back to the verb
    list, a future `browser_read_*` would be graded SAFE automatically — purely
    because its name starts with a read verb — and would skip the very review
    this table exists to require. So once a connector is hand-graded, the table
    is authoritative and anything outside it is restricted."""
    assert suggest_tier("browser_read_everything") == "safe", (
        "premise check: the heuristic really would call this safe")
    assert suggested_tier_for(PLAYWRIGHT, "browser_read_everything") == "orchestrator"
    assert catalog.manual_tier(PLAYWRIGHT.args, "browser_read_everything") == "orchestrator"


def test_other_servers_are_untouched_by_the_manual_table():
    """The override is scoped, not global: a different server keeps the
    heuristic it always had."""
    assert catalog.manual_tier(MEMORY.args, "browser_snapshot") is None
    assert suggested_tier_for(MEMORY, "list_entities") == "safe"


def test_at_least_one_safe_tool_exists_so_a_spawn_can_be_assigned():
    """The acceptance condition from the brief, stated as the thing it protects:
    assert_assignable requires a safe, wired tool, and without one this whole
    connector gives a spawn nothing."""
    safe = [t for t, tier in catalog.PLAYWRIGHT_TOOL_TIERS.items() if tier == "safe"]
    assert safe, "no safe tool — the toolset could not be assigned to any spawn"


def test_the_description_does_not_promise_unrestricted_control():
    """Action tools start restricted, so the copy must not read as though the
    connector arrives able to drive anything."""
    c = catalog.find_connector("playwright")
    text = c["description"].lower()
    assert "once you allow" in text or "you allow" in text, (
        "the description must say that acting on the page is not on by default")
    assert "no logged-in accounts" in text or "no logged-in" in text
