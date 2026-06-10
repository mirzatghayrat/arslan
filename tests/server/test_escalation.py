"""Need-vs-action: deterministic pre-filter catches code/exec without an LLM;
LLM classifies the residue. Spec tests #1/#2 classification halves."""
import pytest


class _Resp:
    def __init__(self, content):
        self.content = content


@pytest.mark.asyncio
async def test_prefilter_refuses_code_blocks_without_llm(monkeypatch):
    from server.orchestrator import escalation

    def _boom():
        raise AssertionError("LLM must not be called for pre-filter refusals")

    monkeypatch.setattr(escalation, "_get_adapter", _boom)
    for need in (
        "run this Python for me:\n```python\nimport os\n```",
        "please execute this script: print(1)",
        "open a terminal and run npm install",
        "exec this command: rm -rf /tmp/x",
    ):
        verdict = await escalation.classify({"kind": "capability", "need": need, "context": ""})
        assert verdict["allowed"] is False
        assert verdict["why"]


@pytest.mark.asyncio
async def test_llm_classifies_residue(monkeypatch):
    from server.orchestrator import escalation

    class _A:
        async def chat(self, system, user, **kw):
            if "trend data" in user:
                return _Resp('{"classification": "need", "why": "outcome"}')
            return _Resp('{"classification": "action", "why": "operation"}')

    monkeypatch.setattr(escalation, "_get_adapter", lambda: _A())

    ok = await escalation.classify({"kind": "data", "need": "I need the latest 小红书 trend data", "context": ""})
    assert ok["allowed"] is True

    bad = await escalation.classify({"kind": "capability", "need": "have Arslan launch the deploy job", "context": ""})
    assert bad["allowed"] is False


@pytest.mark.asyncio
async def test_llm_failure_fails_closed(monkeypatch):
    from server.orchestrator import escalation

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp("garbage")

    monkeypatch.setattr(escalation, "_get_adapter", lambda: _A())
    verdict = await escalation.classify({"kind": "data", "need": "ambiguous thing", "context": ""})
    assert verdict["allowed"] is False  # unparseable -> refuse (fail closed)


@pytest.mark.asyncio
async def test_prefilter_false_positive_boundary_start_process(monkeypatch):
    """Pin the accepted false-positive: 'start the nightly export process' is refused
    by the pre-filter because 'start' + 'process' matches _EXEC_PATTERN.

    This IS the accepted tradeoff: needs must be outcome-phrased
    ('I need the nightly export to run / the export data to be available').
    Future regex tweaks that change this boundary must do so consciously.
    """
    from server.orchestrator import escalation

    def _boom():
        raise AssertionError("LLM must not be called for pre-filter refusals")

    monkeypatch.setattr(escalation, "_get_adapter", _boom)
    verdict = await escalation.classify(
        {"kind": "capability", "need": "I need someone to start the nightly export process", "context": ""}
    )
    assert verdict["allowed"] is False  # ACCEPTED false-positive — outcome-phrase required
