from server.services import optimizer

# ── propose_edits tests ──────────────────────────────────────────────────────


class _Resp:
    def __init__(self, content): self.content = content


class _Adapter:
    def __init__(self, content): self._c = content
    async def chat(self, *, system, user): return _Resp(self._c)


class _SpawnEdits:
    name = "fin"
    persona_role = "analyst"
    persona_tone = "terse"
    system_prompt = "## Role\nYou are an analyst."


def _items():
    return [{"task": "summarize", "baseline_overall": 6,
             "baseline_dims": {"completion": {"score": 6, "status": "weak"}}}]


async def test_propose_edits_parses_and_caps(monkeypatch):
    content = ('{"edits": ['
               '{"op":"replace","section":"Role","content":"You are a sharp analyst."},'
               '{"op":"add","section":"Style","content":"Lead with the number."},'
               '{"op":"add","section":"Extra","content":"third"}]}')

    async def fake_build(role): return _Adapter(content)
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    edits = await optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=[])
    assert len(edits) == 2  # capped to lr_budget
    assert edits[0]["op"] == "replace" and edits[0]["section"] == "Role"


async def test_propose_edits_drops_avoided(monkeypatch):
    content = ('{"edits": ['
               '{"op":"add","section":"Style","content":"Lead with the number."}]}')

    async def fake_build(role): return _Adapter(content)
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    avoid = [{"op": "add", "section": "Style", "content": "Lead with the number."}]
    edits = await optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=avoid)
    assert edits == []  # the only proposed edit was in the avoid buffer


async def test_propose_edits_empty_on_failure(monkeypatch):
    class _Boom:
        async def chat(self, *, system, user): raise RuntimeError("llm down")

    async def fake_build(role): return _Boom()
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    edits = await optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=[])
    assert edits == []
