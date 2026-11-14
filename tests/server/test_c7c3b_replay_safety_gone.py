"""C7c-3b (v0.1.64): replay_safety is gone, and with it the two stages of a tool call it held.

Under a conversation id of `evolution-eval` or `evolution-replay`, the eval allowance capped web reads at fifty and
the eval backstop refused every tool but five, after the tool's own gate. The eval and replay paths that ran under
those ids went in C7b-1, C7b-2 and C7b-4 (v0.1.63). Conversation ids are set by the host, never by tool arguments:
the app names the conversation it opens, and a task schedule_task makes binds to the conversation it was made in,
whatever its arguments name (test_schedule_tools). A task stored earlier keeps its id: one stored under either old id
now gets the live gates, as a conversation under any other id does (test_gate_order's
`test_a_former_eval_id_gets_the_live_gates`).
"""
import ast
import dataclasses
import importlib.util
import re
from pathlib import Path

from server.orchestrator import tool_loop
from server.registry.tool import Traits


def test_replay_safety_its_stages_and_its_trait_are_gone():
    assert importlib.util.find_spec("server.services.replay_safety") is None
    assert not hasattr(tool_loop, "_eval_backstop") and not hasattr(tool_loop, "_check_fetch_budget")
    assert "replay_safe" not in {field.name for field in dataclasses.fields(Traits)}


def test_no_product_code_names_an_eval_sentinel():
    """Every string constant in server/ and arslan/, with no file left out."""
    root = Path(tool_loop.__file__).resolve().parents[2]
    sentinel = re.compile(r"^evolution-[a-z][a-z-]*$")
    walked: set[str] = set()
    found: list[str] = []
    for top in ("server", "arslan"):
        for path in sorted((root / top).rglob("*.py")):
            walked.add(path.relative_to(root).as_posix())
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and sentinel.match(node.value):
                    found.append(f"{path.relative_to(root).as_posix()}:{node.lineno} {node.value!r}")
    assert {"server/orchestrator/tool_loop.py", "arslan/execution_budget.py"} <= walked     # it read both trees
    assert not found, ("The eval/replay seal went in C7c-3b, so a reserved conversation id seals nothing: an eval "
                       f"path needs its own tool list, not a reserved id. Found: {found}")
