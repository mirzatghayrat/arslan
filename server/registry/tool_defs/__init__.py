"""Every built-in tool, one object each, by family (server/registry/tool.py). Families not listed yet are still in
`arslan._every_tool` and `tool_loop._NATIVE_PARAM_SCHEMAS`; LOOP1's slices a3–a5 move them here."""
from server.registry import tool
from server.registry.executors import EXECUTORS
from server.registry.tool_defs.memory import MEMORY
from server.registry.tool_defs.tasks import TASKS
from server.registry.tool_defs.web import WEB

TOOLS = (*WEB, *MEMORY, *TASKS)
tool.check(TOOLS, EXECUTORS)
SCHEMAS = {t.name: t.schema for t in TOOLS}
