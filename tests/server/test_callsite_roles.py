import inspect
from server.services import fact_classify, turn_facts
from server.orchestrator import escalation, dispatcher, spawn_loop, memory


def _calls_with_role(module, role: str) -> bool:
    src = inspect.getsource(module)
    return f'build_adapter(role="{role}")' in src or f"build_adapter(role='{role}')" in src


def test_callsites_pass_expected_roles():
    # 0.1.48: the router is gone; its cheap slot now notes facts after the answer.
    assert _calls_with_role(turn_facts, "router")
    assert _calls_with_role(fact_classify, "converse")
    assert _calls_with_role(escalation, "critical")
    assert _calls_with_role(dispatcher, "execute") or _calls_with_role(spawn_loop, "execute")
    assert _calls_with_role(memory, "summarize")
