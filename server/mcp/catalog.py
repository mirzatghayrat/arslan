"""Hand-graded tool tiers for MCP servers whose tool names do not say what they do (Playwright).

0.1.63 C9b: this used to be the preset connector catalog as well (the recommended list in Settings
and the model's `suggest_connector` tool). Both are gone: recommending MCP servers waits for its own
round after v0.1.65 (user, 2026-10-21); adding one is `find_capability` (the official MCP Registry) or
the manual form. What stays grades the tools of a server already installed (`server.mcp.discovery`)."""
from __future__ import annotations

# The grading rule is the obvious one, applied by hand: a tool that only OBSERVES
# is safe; a tool that ACTS on the page starts at orchestrator and can be raised
# per tool in Settings. Listing them explicitly rather than pattern-matching
# "read-ish" names is the point — a new tool nobody graded must fall through to
# the conservative default rather than inherit a guess from its name.
PLAYWRIGHT_TOOL_TIERS: dict[str, str] = {
    # observe only
    "browser_snapshot": "safe",
    "browser_take_screenshot": "safe",
    "browser_console_messages": "safe",
    "browser_network_requests": "safe",
    # One endpoint also creates/closes/selects tabs; its name is not read-only.
    "browser_tabs": "orchestrator",
    # act on the page — deliberately NOT safe
    "browser_click": "orchestrator",
    "browser_type": "orchestrator",
    "browser_fill_form": "orchestrator",
    "browser_navigate": "orchestrator",
    "browser_navigate_back": "orchestrator",
    "browser_press_key": "orchestrator",
    "browser_select_option": "orchestrator",
    "browser_hover": "orchestrator",
    "browser_drag": "orchestrator",
    "browser_file_upload": "orchestrator",
    "browser_evaluate": "orchestrator",
    "browser_handle_dialog": "orchestrator",
    "browser_wait_for": "orchestrator",
    "browser_resize": "orchestrator",
    "browser_close": "orchestrator",
    "browser_install": "orchestrator",
}

# Which connectors carry a hand-graded table. Keyed by the command+args shape a
# server was created from, because MCPServer does not record which preset it
# came from and inventing a column for this would be a migration for a lookup.
MANUAL_TIERS: dict[str, dict[str, str]] = {
    "@playwright/mcp": PLAYWRIGHT_TOOL_TIERS,
}


def manual_tier(server_args: list[str] | None, tool_name: str) -> str | None:
    """A hand-assigned tier, or None when this server is not hand-graded at all.

    ONCE A CONNECTOR IS IN THE TABLE, THE TABLE IS AUTHORITATIVE: an ungraded
    tool from a graded server gets "orchestrator", never the heuristic. That is
    the whole reason the table exists — this connector's names do not mean what
    the verb list thinks they mean, and falling back would hand a future
    `browser_read_*` a "safe" grade purely because it starts with a read verb,
    which is exactly the review this table replaces.

    None still means "not one of the hand-graded connectors", and those keep the
    heuristic they always had."""
    for token in server_args or []:
        for marker, table in MANUAL_TIERS.items():
            if marker in str(token):
                return table.get(tool_name, "orchestrator")
    return None
