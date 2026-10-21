"""K5: the web rules live with the web tools, not in the system text (card K5, ⓪Plan's Q3/Q4).

`_NATIVE_EFFICIENCY` ("RESEARCH DISCIPLINE": snippets locate a source, one or two broad searches then
extract, answer as soon as you can, name the unknowns) was appended to every run_native system, tools or
not. It now lives in web_search's and web_extract's descriptions, so it comes with the tools.
web_search's description also says what to do with `search_blocked` (D5's card). The research-scope note
stays where it was: in the status block, only after a successful web_extract.
"""
from server.orchestrator import arslan, tool_loop
from tests.server import test_trajectory_golden as golden
from tests.server.test_agent_status_requests import NativeRecorder


async def _web_descriptions(execution_db) -> dict[str, str]:
    return {t["key"]: t["description"] for t in await arslan._arslan_tools() if t["key"].startswith("web_")}


async def test_the_system_text_no_longer_carries_the_research_rules(monkeypatch):
    adapter = NativeRecorder([golden._Resp("ok")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def resolve():
        return [{"key": "web_search", "description": "search"}]
    await tool_loop.run_native(system="SYS", user_content="hi", history=[], emit=lambda e: None,
                               on_chunk=lambda c: None, resolve_tools=resolve)
    sent = str(adapter.calls[0]["system"])
    assert "RESEARCH DISCIPLINE" not in sent and "1–2 broad searches" not in sent
    assert sent == "SYS\n\n" + tool_loop.GUARD_NOTE
    assert not hasattr(tool_loop, "_NATIVE_EFFICIENCY")


async def test_the_web_tools_carry_the_rules(execution_db):
    desc = await _web_descriptions(execution_db)
    assert "snippets" in desc["web_search"] and "at most 1–2 broad searches" in desc["web_search"]
    assert "answer as soon as you can" in desc["web_search"]
    assert "most authoritative page" in desc["web_extract"]
    assert "name the specific unknowns" in desc["web_extract"]


async def test_web_search_says_what_a_blocked_search_means(execution_db):
    desc = (await _web_descriptions(execution_db))["web_search"]
    assert "search_blocked" in desc and "nothing was searched" in desc
    assert "Settings" in desc and "never answer from memory" in desc
