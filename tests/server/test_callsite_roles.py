import inspect
from server.orchestrator import router, arslan, escalation, dispatcher, spawn_loop, memory


def _calls_with_role(module, role: str) -> bool:
    src = inspect.getsource(module)
    return f'build_adapter(role="{role}")' in src or f"build_adapter(role='{role}')" in src


def test_callsites_pass_expected_roles():
    assert _calls_with_role(router, "router")
    assert _calls_with_role(arslan, "converse")
    assert _calls_with_role(escalation, "critical")
    assert _calls_with_role(dispatcher, "execute") or _calls_with_role(spawn_loop, "execute")
    assert _calls_with_role(memory, "summarize")
