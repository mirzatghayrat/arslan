"""Arslan direct chat retrieves from shared collections (never spawn wells)."""


def _patch_common(monkeypatch, arslan_mod):
    async def fake_assemble(cid):
        return {"summary": "", "history": [{"role": "user", "content": "hi"}]}
    async def fake_facts():
        return ""
    async def fake_roster():
        return "(none)"
    async def fake_add(cid, role, content):
        return 1
    monkeypatch.setattr(arslan_mod.memory, "assemble_working_context", fake_assemble)
    monkeypatch.setattr(arslan_mod.memory, "facts_text", fake_facts)
    monkeypatch.setattr(arslan_mod, "_team_roster", fake_roster)
    monkeypatch.setattr(arslan_mod.memory, "add_message", fake_add)


async def test_handle_answer_injects_collection_kb(monkeypatch):
    from server.orchestrator import arslan as arslan_mod
    from server.services import knowledge
    captured = {}

    async def fake_retrieve_scoped(query, *, spawn_id, k=5, used_ref=None):
        assert spawn_id is None
        return [("公司手册.pdf", "报销上限 500 元")]

    async def fake_run_native(**kwargs):
        captured["system"] = kwargs["system"]
        return {"final": "好的"}

    monkeypatch.setattr(knowledge, "retrieve_scoped", fake_retrieve_scoped)
    monkeypatch.setattr(arslan_mod.tool_loop, "run_native", fake_run_native)
    _patch_common(monkeypatch, arslan_mod)

    await arslan_mod._handle_answer("c1", "报销上限多少", lambda e: None)
    assert "[公司手册.pdf] 报销上限 500 元" in captured["system"]


async def test_handle_answer_survives_retrieve_failure(monkeypatch):
    from server.orchestrator import arslan as arslan_mod
    from server.services import knowledge
    captured = {}

    async def boom(query, *, spawn_id, k=5, used_ref=None):
        raise RuntimeError("db locked")

    async def fake_run_native(**kwargs):
        captured["system"] = kwargs["system"]
        return {"final": "ok"}

    monkeypatch.setattr(knowledge, "retrieve_scoped", boom)
    monkeypatch.setattr(arslan_mod.tool_loop, "run_native", fake_run_native)
    _patch_common(monkeypatch, arslan_mod)

    await arslan_mod._handle_answer("c1", "hi", lambda e: None)
    assert "system" in captured  # answered despite retrieval failure
