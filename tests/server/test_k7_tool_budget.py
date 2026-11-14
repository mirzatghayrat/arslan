"""K7: the tool table one request carries stays under about 12,000 characters (card K7, acceptance).

Measured with C3's function (`tests/server/tool_json.py`), on default config plus three MCP servers
of realistic size: 50 tools, about the size of the user's own largest one. Before K7 every discovered
MCP tool rode along on every request, so the table grew with every server connected.
"""

from server.orchestrator import arslan
from tests.server.k7_mcp_fixture import mac_with_mcp  # noqa: F401 — the fixture
from tests.server.tool_json import rendered_tool_json_chars

# About 12,000: main stood at 11,994 when INB2's `sensitive` flag on remember (#475 F4, the user's decision of
# 2026-10-29) added 34 characters. HR-1b's `git_config` flag on run_command (⓪Plan's ruling 5, 2026-11-11) adds 31,
# with no description: git's note says when to use it. Raising this is for review to confirm.
# SBX-5b's `app_data_once` on run_command (the user's "C lite", 2026-11-11) adds 38 the same way, with no description:
# the sandbox's stop note says when and how. For review to confirm.
BUDGET = 12_120


async def test_the_fixture_is_the_size_the_card_describes(mac_with_mcp):  # noqa: F811
    tools = await arslan._every_tool()
    assert sum(t["key"].startswith("mcp_") for t in tools) == 50


async def test_a_chat_request_carries_at_most_about_12k_characters_of_tools(mac_with_mcp):  # noqa: F811
    chars = rendered_tool_json_chars(await arslan._arslan_tools())
    print(f"\nK7 tool JSON, chat, Mac without Hands, 3 MCP servers: {chars:,} characters")
    assert chars <= BUDGET
