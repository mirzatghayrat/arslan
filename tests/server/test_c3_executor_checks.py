"""C3a: `_arslan_tools` no longer asks whether always-registered executors exist (card C3, ⓪Plan's Q5).

`"<key>" in EXECUTORS` was true for every key below: `EXECUTORS` registers them unconditionally
(server/registry/executors.py), and tests only ever add to it or replace an entry, never remove one. The
checks are gone. This test keeps the one thing they could have meant: a tool offered without a check
must have an executor, or the model would be offered a tool that cannot run.
"""
from server.registry.executors import EXECUTORS

OFFERED_WITHOUT_A_CHECK = (
    "web_search", "web_extract", "render_chart", "recall", "remember", "conversation_search", "memory_note",
    "task_progress", "delegate_work", "read_skill", "find_capability", "whats_new", "list_my_capabilities",
)


def test_every_tool_offered_without_a_check_has_an_executor():
    assert set(OFFERED_WITHOUT_A_CHECK) <= set(EXECUTORS)
