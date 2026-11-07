"""Every built-in tool, one object each, by family (server/registry/tool.py)."""
from collections.abc import Callable

from server.registry import tool
from server.registry.tool import Traits
from server.registry.tool_defs.browser import BROWSER
from server.registry.tool_defs.capability import CAPABILITY
from server.registry.tool_defs.files import ATTACH_FILE, FILES
from server.registry.tool_defs.hands import HANDS
from server.registry.tool_defs.mac import MAC
from server.registry.tool_defs.memory import MEMORY
from server.registry.tool_defs.network import NETWORK
from server.registry.tool_defs.schedule import SCHEDULE
from server.registry.tool_defs.tasks import TASKS
from server.registry.tool_defs.terminal import TERMINAL
from server.registry.tool_defs.web import WEB

# The order is part of the contract: find_tools breaks ties by it.
TOOLS = (*WEB, *MEMORY, *TASKS, *BROWSER, *MAC, *HANDS, *CAPABILITY, *FILES, *NETWORK, *SCHEDULE, *TERMINAL, ATTACH_FILE)
# LOOP1 a6: `tool.check(TOOLS, EXECUTORS)` runs where EXECUTORS is built (executors.py). The modules that read the
# traits import this table, and some of them are imported while executors.py is, so this file imports no executor.
# run_python has an executor, but `_every_tool` doesn't list it, so a request can't carry it. A `Tool` would need a
# predicate that is never true; its words are in seed_catalog. Only its parameters are here, for `_tool_params`.
# 0.1.63 K5: built-in schemas go to every provider verbatim (F3's normaliser is for MCP tools only): no `pattern`, no
# top-level `anyOf`, no type arrays (tests/server/test_k5_tool_schemas.py).
SCHEMAS = {**{t.name: t.schema for t in TOOLS},
           "run_python": {"type": "object",
                          "properties": {"code": {"type": "string"}}}}

# LOOP1 a6: the traits of the keys that aren't registry tools: run_python (above), the two that reach the tools a
# request isn't shown (on_demand.py; use_tool's call is judged under the tool it names) and escalate (tool_loop).
# MCP tools aren't here: each module judges them per call.
UNLISTED = {
    "run_python": Traits(effect="local_write", parallel=False, outside=False, replay_safe=True, saves=False),
    "find_tools": Traits(effect="external_write", parallel=False, outside=False, replay_safe=False, saves=False),
    "use_tool": Traits(effect="external_write", parallel=False, outside=False, replay_safe=False, saves=False),
    "escalate": Traits(effect="external_write", parallel=False, outside=False, replay_safe=False, saves=False),
}
tool.check_traits(TOOLS, UNLISTED)
TRAITS = {**{t.name: t.traits for t in TOOLS}, **UNLISTED}


def named(has: Callable[[Traits], bool]) -> frozenset[str]:
    """The keys whose traits say yes: how each module's name set (parallel_reads.READS, replay_safety's, …) is made."""
    return frozenset(key for key, traits in TRAITS.items() if has(traits))
