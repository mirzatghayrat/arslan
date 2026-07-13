from server.services import sandbox_service


async def test_summarize_deliverable_returns_one_line(monkeypatch):
    class FakeResp:
        content = "  精简版周报,已加环比数据  "
    class FakeAdapter:
        async def chat(self, *, system, user):
            return FakeResp()
    async def fake_build_adapter(*, role):
        return FakeAdapter()
    monkeypatch.setattr(sandbox_service, "build_adapter", fake_build_adapter)

    out = await sandbox_service.summarize_deliverable("Mermer", "整段很长的周报正文…")
    assert out == "精简版周报,已加环比数据"


async def test_summarize_deliverable_falls_back_to_first_line(monkeypatch):
    async def boom(*, role):
        raise RuntimeError("llm down")
    monkeypatch.setattr(sandbox_service, "build_adapter", boom)
    out = await sandbox_service.summarize_deliverable("Mermer", "第一行就是要点\n第二行\n第三行")
    assert out == "第一行就是要点"


async def test_summarize_deliverable_empty_returns_empty(monkeypatch):
    async def boom(*, role):
        raise RuntimeError("x")
    monkeypatch.setattr(sandbox_service, "build_adapter", boom)
    assert await sandbox_service.summarize_deliverable("Mermer", "") == ""
