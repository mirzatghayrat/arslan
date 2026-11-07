"""Every built-in tool, one object each, by family (server/registry/tool.py). Families not listed yet are still in
`arslan._every_tool` and `tool_loop._NATIVE_PARAM_SCHEMAS`; LOOP1's slice a5 moves them here."""
from server.registry import tool
from server.registry.executors import EXECUTORS
from server.registry.tool_defs.capability import CAPABILITY
from server.registry.tool_defs.files import ATTACH_FILE, FILES
from server.registry.tool_defs.memory import MEMORY
from server.registry.tool_defs.network import NETWORK
from server.registry.tool_defs.schedule import SCHEDULE
from server.registry.tool_defs.tasks import TASKS
from server.registry.tool_defs.terminal import TERMINAL
from server.registry.tool_defs.web import WEB

# The order is part of the contract (find_tools breaks ties by it), and Hands, browser and Mac (a5) still sit in it, as
# code in `_every_tool`. It lists these runs around that code, and each where its settings have been read: a predicate
# in a run listed earlier would see only `Offer`'s defaults. DELETE-BY: v0.1.64, with a5, when one run is left.
BEFORE_HANDS = (*WEB, *MEMORY, *TASKS)
AFTER_HANDS = (*CAPABILITY, *FILES, *NETWORK, *SCHEDULE)
AFTER_TERMINAL = (ATTACH_FILE,)
TOOLS = (*BEFORE_HANDS, *AFTER_HANDS, *TERMINAL, *AFTER_TERMINAL)
tool.check(TOOLS, EXECUTORS)
# 0.1.63 K5: built-in schemas go to every provider verbatim (F3's normaliser is for MCP tools only): no `pattern`, no
# top-level `anyOf`, no type arrays (tests/server/test_k5_tool_schemas.py).
SCHEMAS = {t.name: t.schema for t in TOOLS}
