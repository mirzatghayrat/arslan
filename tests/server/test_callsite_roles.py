import inspect
from server.services import turn_facts


def _calls_with_role(module, role: str) -> bool:
    src = inspect.getsource(module)
    return f'build_adapter(role="{role}")' in src or f"build_adapter(role='{role}')" in src


def test_callsites_pass_expected_roles():
    # 0.1.48: the router is gone; its cheap slot now notes facts after the answer.
    assert _calls_with_role(turn_facts, "router")
    # 0.1.63 C2a-2: fact_classify (the v1 classifier, role "converse") is gone.
    # 0.1.63 C7b-4: the dispatcher / spawn_loop ("execute") are gone.
    # v0.1.64 ROUTE1: compaction runs on the conversation's model and keeps the "summarize" name; asserted by
    # behaviour in test_route1_remove_routing.py::test_compaction_follows_the_conversations_model.
