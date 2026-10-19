"""P0-a: facts_text's fail-closed sensitive isolation, on memory v2.

C2a removed the tests of v1's own cap and ranking (40 rows by confidence, then id order; NULL rows):
memory v2 ranks by relevance in personal_context, whose budget and sensitivity tests are in
tests/server/test_personal_context.py. What stays is the gate facts_text adds on top: a sensitive
entry needs both the call site's include_sensitive and the task context's allow_sensitive.
"""
import inspect

from server.orchestrator import memory
from server.services import personal_context as pc


def _context(**kwargs):
    return pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=True, query="事实", **kwargs)


async def test_default_is_fail_closed(execution_db):
    # 用户修正锚定:默认 include_sensitive=False
    sig = inspect.signature(memory.facts_text)
    assert sig.parameters["include_sensitive"].default is False
    await memory.add_manual_fact("普通事实")
    await memory.add_manual_fact("私密事实", sensitive=True)
    with pc.bind(_context(allow_sensitive=True)):
        out = await memory.facts_text()          # 裸调用 = spawn 语义,即使上下文允许
    assert "普通事实" in out and "私密事实" not in out


async def test_host_privilege_is_explicit(execution_db):
    await memory.add_manual_fact("私密事实", sensitive=True)
    with pc.bind(_context(allow_sensitive=True)):
        assert "私密事实" in await memory.facts_text(include_sensitive=True)
    with pc.bind(_context()):                    # the context has not allowed it
        assert "私密事实" not in await memory.facts_text(include_sensitive=True)


async def test_empty_returns_empty_string(execution_db):
    with pc.bind(_context()):
        assert await memory.facts_text() == ""
