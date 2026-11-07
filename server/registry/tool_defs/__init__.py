"""Every built-in tool, one object each, by family (server/registry/tool.py)."""
from server.registry import tool
from server.registry.executors import EXECUTORS
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
tool.check(TOOLS, EXECUTORS)
# run_python has an executor, but `_every_tool` doesn't list it, so a request can't carry it. A `Tool` would need a
# predicate that is never true; its words are in seed_catalog. Only its parameters are here, for `_tool_params`.
# 0.1.63 K5: built-in schemas go to every provider verbatim (F3's normaliser is for MCP tools only): no `pattern`, no
# top-level `anyOf`, no type arrays (tests/server/test_k5_tool_schemas.py).
SCHEMAS = {**{t.name: t.schema for t in TOOLS},
           "run_python": {"type": "object",
                          "properties": {"code": {"type": "string"}}}}
