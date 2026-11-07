"""LOOP1 a: one object per tool. A table that can't work is refused when it is built, never in a turn."""
from dataclasses import fields

import pytest

from server.registry import tool, tool_defs
from server.registry.executors import EXECUTORS
from server.registry.tool import Offer, Tool, Traits

OBJECT = {"type": "object", "properties": {}}
# LOOP1 a6: every Tool states its traits (no defaults); these tests are about the other fields.
_TRAITS = Traits(effect="external_write", parallel=False, outside=False, replay_safe=False, saves=False)


def _offer(**values) -> Offer:
    """A turn with nothing on but what the test names: `Offer` has no defaults, so that no predicate can see one."""
    return Offer(**{**{field.name: False for field in fields(Offer)}, "skills": "", **values})


def test_todays_table_passes_its_own_check():
    tool.check(tool_defs.TOOLS, EXECUTORS)


@pytest.mark.parametrize("tools,why", [
    ([Tool("a", "d", OBJECT, host=True, traits=_TRAITS), Tool("a", "d", OBJECT, host=True, traits=_TRAITS)],
     "defined twice"),
    ([Tool("a", "d", {"type": "string"}, host=True, traits=_TRAITS)], "JSON object schema"),
    ([Tool("nobody_answers_this", "d", OBJECT, traits=_TRAITS)], "not both or neither"),
    ([Tool("web_search", "d", OBJECT, host=True, traits=_TRAITS)], "not both or neither"),
])
def test_a_table_that_cant_work_is_refused(tools, why):
    with pytest.raises(ValueError, match=why):
        tool.check(tools, EXECUTORS)


def test_a_turn_is_offered_what_its_predicates_say_in_table_order():
    tools = [Tool("always", "first", OBJECT, host=True, traits=_TRAITS),
             Tool("in_a_job", "second", OBJECT, host=True, offered=lambda offer: offer.in_job, traits=_TRAITS),
             Tool("in_a_task", "third", OBJECT, host=True, offered=lambda offer: offer.in_task, traits=_TRAITS)]
    offer = _offer(in_task=True, in_job=False, can_ask=False)
    assert tool.listed(tools, offer) == [{"key": "always", "description": "first"},
                                         {"key": "in_a_task", "description": "third"}]


@pytest.mark.parametrize("in_task,in_job,can_ask,offered", [
    (True, False, True, True), (False, False, True, False), (True, True, True, False), (True, False, False, False)])
def test_a_job_can_start_only_from_a_turn_where_someone_can_be_asked(in_task, in_job, can_ask, offered):
    offer = _offer(in_task=in_task, in_job=in_job, can_ask=can_ask)
    keys = {entry["key"] for entry in tool.listed(tool_defs.TOOLS, offer)}
    jobs = {"start_background_work", "background_status", "stop_background_work"}
    assert (jobs <= keys if offered else not jobs & keys)


def _gates():
    return {t.name: t.gate for t in tool_defs.TOOLS if t.gate is not None}


def test_each_gate_is_its_modules_function_of_that_name():
    """LOOP1 c2: `Tool.gate` holds the function itself, taken from `tool_gates` or `command_gate` when the table is
    built. A gate that names no module function could only be reached through the tool."""
    import sys
    assert _gates(), "no tool has a gate"
    for name, gate in _gates().items():
        module = sys.modules[gate.__module__]
        assert module.__name__ in ("server.orchestrator.tool_gates", "server.orchestrator.command_gate"), name
        assert getattr(module, gate.__name__) is gate, name


def test_no_test_patches_a_gate_function():
    """Because the tool holds the function, patching `tool_gates.schedule` (say) would reach nothing: the call would
    still run the real gate, and the test would pass for the wrong reason. Patch what the gate reads instead
    (`_writing_in_own_folder`, `_unattended`, `command_gate._sandbox_enabled`, ...), which it reads by name."""
    import ast
    from pathlib import Path
    names = {gate.__name__ for gate in _gates().values()}
    found = []
    for path in sorted(Path(__file__).parent.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr"
                    and len(node.args) >= 2 and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in ("tool_gates", "command_gate")
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value in names):
                found.append(f"{path.name}:{node.lineno} {node.args[0].id}.{node.args[1].value}")
    assert not found, f"a patch of a gate function never reaches the tool, which holds the function: {found}"
