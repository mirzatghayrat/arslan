"""LOOP1 a: one object per tool. A table that can't work is refused when it is built, never in a turn."""
import pytest

from server.registry import tool, tool_defs
from server.registry.executors import EXECUTORS
from server.registry.tool import Offer, Tool

OBJECT = {"type": "object", "properties": {}}


def test_todays_table_passes_its_own_check():
    tool.check(tool_defs.TOOLS, EXECUTORS)


@pytest.mark.parametrize("tools,why", [
    ([Tool("a", "d", OBJECT, host=True), Tool("a", "d", OBJECT, host=True)], "defined twice"),
    ([Tool("a", "d", {"type": "string"}, host=True)], "JSON object schema"),
    ([Tool("nobody_answers_this", "d", OBJECT)], "not both or neither"),
    ([Tool("web_search", "d", OBJECT, host=True)], "not both or neither"),
])
def test_a_table_that_cant_work_is_refused(tools, why):
    with pytest.raises(ValueError, match=why):
        tool.check(tools, EXECUTORS)


def test_a_turn_is_offered_what_its_predicates_say_in_table_order():
    tools = [Tool("always", "first", OBJECT, host=True),
             Tool("in_a_job", "second", OBJECT, host=True, offered=lambda offer: offer.in_job),
             Tool("in_a_task", "third", OBJECT, host=True, offered=lambda offer: offer.in_task)]
    offer = Offer(in_task=True, in_job=False, can_ask=False)
    assert tool.listed(tools, offer) == [{"key": "always", "description": "first"},
                                         {"key": "in_a_task", "description": "third"}]


@pytest.mark.parametrize("in_task,in_job,can_ask,offered", [
    (True, False, True, True), (False, False, True, False), (True, True, True, False), (True, False, False, False)])
def test_a_job_can_start_only_from_a_turn_where_someone_can_be_asked(in_task, in_job, can_ask, offered):
    offer = Offer(in_task=in_task, in_job=in_job, can_ask=can_ask)
    keys = {entry["key"] for entry in tool.listed(tool_defs.TOOLS, offer)}
    jobs = {"start_background_work", "background_status", "stop_background_work"}
    assert (jobs <= keys if offered else not jobs & keys)
