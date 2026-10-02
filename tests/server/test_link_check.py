"""Host link check on a saved table (0.1.50)."""
import pytest

from server.orchestrator import link_check, tool_loop
from tests.server import test_trajectory_golden as golden

SEARCH = {"tool": "web_search", "args": {"query": "jobs"}, "result": {"ok": True, "results": [
    {"title": "A", "url": "https://m.jobs.example/a"}, {"title": "B", "url": "https://jobs.example/b/"}]}}
PAGE = {"tool": "web_extract", "args": {"url": "https://jobs.example/c"},
        "result": {"ok": True, "text": "C job page, apply at https://apply.example/c#top"}}
CMD = {"tool": "run_command", "args": {"command": "curl …"},
       "result": {"ok": True, "stdout": '{"url":"https://api.example/job?id=7"}'}}
FAILED = {"tool": "web_extract", "args": {"url": "https://dead.example/x"}, "result": {"ok": False}}
OWN = {"tool": "write_file", "args": {"content": "https://own.example/z"}, "result": {"ok": True}}


def test_normalize_ignores_scheme_www_slash_fragment_and_encoding():
    n = link_check.normalize
    assert n("https://www.jobs.example/b/") == n("http://jobs.example/b") == "jobs.example/b"
    assert n("https://jobs.example/a#x") == n("https://jobs.example/a")
    assert n("https://jobs.example/%E4%BA%A7") == n("https://jobs.example/产")
    assert n("https://m.jobs.example/a") != n("https://jobs.example/a")       # a different host
    assert n("https://jobs.example/a?id=1") != n("https://jobs.example/a?id=2")


def test_evidence_is_every_link_the_turn_saw_but_not_its_own_writes_or_failures():
    seen = link_check.evidence([SEARCH, PAGE, CMD, FAILED, OWN])
    for url in ("https://m.jobs.example/a", "https://jobs.example/b", "https://jobs.example/c",
                "https://apply.example/c", "https://api.example/job?id=7"):
        assert link_check.normalize(url) in seen, url
    assert link_check.normalize("https://dead.example/x") not in seen
    assert link_check.normalize("https://own.example/z") not in seen


def test_review_flags_shared_and_unseen_links():
    seen = link_check.evidence([SEARCH, PAGE])
    table = ("company,link\nA,https://m.jobs.example/a\nB,https://jobs.example/b\n"
             "C,https://jobs.example/b\nD,https://www.jobs.example/d-guessed\n")
    found = link_check.review(table, seen)
    assert found["shared"] == {"https://jobs.example/b": [3, 4]}
    assert found["unseen"] == ["https://www.jobs.example/d-guessed"]
    text = link_check.hint("out/jobs.csv", found)
    assert "Host check on jobs.csv" in text and "lines 3, 4 use the same link" in text
    assert "1 links never appeared" in text and "mark them unverified" in text


def test_review_is_quiet_for_a_clean_table_or_too_few_links():
    seen = link_check.evidence([SEARCH, PAGE])
    clean = "A,https://m.jobs.example/a\nB,https://jobs.example/b\nC,https://jobs.example/c\n"
    assert link_check.review(clean, seen) is None
    assert link_check.review("one https://x.example/1 two https://x.example/2", set()) is None


def test_only_text_files_are_checked():
    assert link_check.applies("a/jobs.csv") and link_check.applies("r.MD")
    assert not link_check.applies("deck.pptx") and not link_check.applies("photo.png")


class _Search:
    async def execute(self, args):
        return {"ok": True, "results": [{"title": f"job {i}", "url": f"https://jobs.example/{i}"} for i in range(3)]}


async def _run(monkeypatch, replies, *, research=True):
    adapter = golden._Recorder(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search())
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())

    async def resolve():
        return [{"key": "web_search", "description": "s"}, {"key": "write_file", "description": "w"}]
    result = await tool_loop.run_native(system="S", user_content="10 jobs as a table", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    return result, adapter.calls


BAD = "a,https://jobs.example/0\nb,https://jobs.example/0\nc,https://jobs.example/99\n"
GOOD = "a,https://jobs.example/0\nb,https://jobs.example/1\nc,https://jobs.example/2\n"


def _save(content, cid):
    return golden._Resp(None, [golden._tc("write_file", {"path": "jobs.csv", "content": content}, cid)])


@pytest.mark.asyncio
async def test_the_model_sees_the_check_after_saving_a_doubtful_table(monkeypatch):
    replies = [golden._Resp(None, [golden._tc("web_search", {"query": "jobs"}, "s1")]), _save(BAD, "w1"),
               _save(GOOD, "w2"), golden._Resp("Saved jobs.csv.")]
    result, calls = await _run(monkeypatch, replies)
    assert "[Host check on jobs.csv" in calls[2]["user"]
    assert "lines 1, 2 use the same link (https://jobs.example/0)" in calls[2]["user"]
    assert "https://jobs.example/99" in calls[2]["user"]
    assert "Host check" not in calls[3]["user"]                   # the fixed table passes quietly
    assert result["final"] == "Saved jobs.csv."


@pytest.mark.asyncio
async def test_at_most_two_checks_per_file(monkeypatch):
    replies = [golden._Resp(None, [golden._tc("web_search", {"query": "jobs"}, "s1")]),
               _save(BAD, "w1"), _save(BAD, "w2"), _save(BAD, "w3"), golden._Resp("done")]
    _, calls = await _run(monkeypatch, replies)
    assert ["Host check" in c["user"] for c in calls[2:5]] == [True, True, False]


@pytest.mark.asyncio
async def test_no_research_no_check(monkeypatch):
    _, calls = await _run(monkeypatch, [_save(BAD, "w1"), golden._Resp("done")])
    assert "Host check" not in calls[1]["user"]


@pytest.mark.asyncio
async def test_an_edited_file_is_read_back_and_checked(monkeypatch):
    async def saved(rel):
        assert rel == "jobs.csv"
        return BAD
    monkeypatch.setattr(tool_loop, "_read_saved", saved)
    note = await tool_loop._link_check_note("edit_file", {"path": "jobs.csv", "old": "x", "new": "y"},
                                            {"ok": True, "path": "jobs.csv"},
                                            [{"tool": "web_search", "args": {}, "result": {"ok": True, "results": [
                                                {"url": "https://jobs.example/0"}]}}], {})
    assert note and "same link" in note
