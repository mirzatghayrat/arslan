"""LOOP1 a6: a tool's traits are on its `Tool`, every one stated, and the name sets other modules read are derived from
them. The sets are pinned here, so a changed trait shows as a changed set in the diff that makes it."""
import pytest

from server.orchestrator import parallel_reads, tool_loop, untrusted
from server.registry import tool, tool_defs
from server.registry.tool import Tool, Traits
from server.services import replay_safety, task_service

OBJECT = {"type": "object", "properties": {}}
_TRAITS = dict(effect="read", parallel=False, outside=False, replay_safe=False, saves=False)


def test_the_derived_sets_are_the_ones_before_a6():
    assert task_service._READ_TOOLS == {
        "web_search", "web_extract", "read_skill", "recall", "read_file", "list_dir", "search_files", "list_my_tasks",
        "list_nodes", "list_my_capabilities", "whats_new", "my_status", "render_chart", "task_progress",
        "background_status", "browser_open", "browser_look", "browser_back", "mac_list_shortcuts",
        "update_plan", "desktop_apps", "desktop_look", "progress_report"}    # INB7-f
    assert task_service._LOCAL_WRITE_TOOLS == {
        "write_file", "edit_file", "run_python", "remember", "create_skill", "import_memories",
        "start_background_work", "stop_background_work", "attach_file", "verify"}   # CAP10: verify writes only its copy
    assert replay_safety.REPLAY_SAFE_BUILTINS == {"web_search", "web_extract", "render_chart", "run_python",
                                                  "read_skill"}
    assert tool_loop.WRAP_UP_TOOLS == {"write_file", "edit_file"}
    assert tool_loop.FINISH_TOOLS == {"write_file", "edit_file", "run_command"}
    # Before a6 a tuple without the browser tools, which `counts_as_external` matched by their prefix instead.
    assert untrusted._OUTSIDE_TOOLS == {
        "web_search", "web_extract", "read_file", "search_files", "conversation_search", "recall", "find_capability",
        "task_progress", "browser_open", "browser_look", "browser_back", "browser_click",
        "browser_type", "browser_select", "browser_press",
        "verify"}       # CAP10: what a project's own tests printed
    assert parallel_reads.READS <= task_service._READ_TOOLS


def test_keys_outside_the_registry_state_their_traits_once():
    names = {t.name for t in tool_defs.TOOLS}
    assert set(tool_defs.UNLISTED) == {"run_python", "find_tools", "use_tool", "escalate"}
    assert not names & set(tool_defs.UNLISTED)
    assert set(tool_defs.TRAITS) == names | set(tool_defs.UNLISTED)


def test_a_tool_without_its_traits_is_refused_when_it_is_defined():
    with pytest.raises(TypeError, match="traits"):
        Tool("a", "d", OBJECT, host=True)
    for missing in _TRAITS:
        with pytest.raises(TypeError, match=missing):
            Traits(**{name: value for name, value in _TRAITS.items() if name != missing})


@pytest.mark.parametrize("change,why", [
    ({"effect": "write"}, "effect"), ({"parallel": None}, "parallel"), ({"outside": 1}, "outside"),
    ({"replay_safe": "yes"}, "replay_safe"), ({"saves": 0}, "saves")])
def test_a_trait_that_is_not_one_of_its_values_is_refused(change, why):
    with pytest.raises(ValueError, match=why):
        Traits(**{**_TRAITS, **change})


def test_a_table_with_unstated_or_twice_stated_traits_is_refused():
    with pytest.raises(ValueError, match="registry tool"):
        tool.check_traits(tool_defs.TOOLS, {"web_search": Traits(**_TRAITS)})
    with pytest.raises(ValueError, match="must be a Traits"):
        tool.check_traits(tool_defs.TOOLS, {"not_a_tool": None})
    with pytest.raises(ValueError, match="must be a Traits"):
        tool.check_traits([Tool("a", "d", OBJECT, host=True, traits=None)], {})
