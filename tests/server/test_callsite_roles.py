import inspect
from server.services import turn_facts
from server.orchestrator import memory


def _calls_with_role(module, role: str) -> bool:
    src = inspect.getsource(module)
    return f'build_adapter(role="{role}")' in src or f"build_adapter(role='{role}')" in src


def test_callsites_pass_expected_roles():
    # 0.1.48: the router is gone; its cheap slot now notes facts after the answer.
    assert _calls_with_role(turn_facts, "router")
    # 0.1.63 C2a-2: fact_classify (the v1 classifier, role "converse") is gone.
    # 0.1.63 C7b-4: the dispatcher / spawn_loop ("execute") are gone.
    assert _calls_with_role(memory, "summarize")
