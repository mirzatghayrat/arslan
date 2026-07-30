"""GET /brain/search — the same pipeline the agent reads memory with.

The honesty constraints are the load-bearing part, so they are asserted first:
`ranking` must name the pipeline that actually ran (rerank is lexical overlap,
not semantics, and a relevance score beside these rows would dress a word match
as understanding), and `truncated` must be told rather than implied.

🔴 SESSION NOTE, the repo's own instituted first check: brain read endpoints
open the PRODUCTION AsyncSessionLocal, so the client fixture's dependency
override cannot reach them. A test that forgets this writes to the developer's
real database. Here it does not matter — retrieve_scoped is substituted outright
— but the reason is recorded so the next test in this file starts correctly.
"""
from __future__ import annotations

import pytest

from server.api import brain as brain_api


class _Svc:
    """Stand-in for the retrieval pipeline, returning (source, text) pairs."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def retrieve_scoped(self, query, *, spawn_id, k, record_usage=True, **kw):
        self.calls.append({"query": query, "k": k, "record_usage": record_usage})
        return self.rows[:k]


def _install(monkeypatch, rows, *, provider=None):
    from server.services import embedding_service, knowledge

    svc = _Svc(rows)
    monkeypatch.setattr(knowledge, "retrieve_scoped", svc.retrieve_scoped)

    async def _provider():
        return provider

    monkeypatch.setattr(embedding_service, "active_provider", _provider)
    return svc


ROWS = [("fact:12", "crypto_salt 与 SECRET_KEY 必须配对"),
        ("note:3", "开源迁移后的唯一开发树"),
        ("learning:7", "首启 SECRET_KEY 自动化")]


@pytest.mark.asyncio
async def test_it_reports_the_pipeline_that_actually_ran(monkeypatch):
    _install(monkeypatch, ROWS, provider=None)
    body = await brain_api.brain_search(q="salt", limit=20)
    assert body["ranking"] == "lexical"

    _install(monkeypatch, ROWS, provider=object())
    body = await brain_api.brain_search(q="salt", limit=20)
    assert body["ranking"] == "hybrid"


@pytest.mark.asyncio
async def test_no_result_carries_a_relevance_score(monkeypatch):
    """The constraint most likely to be broken by a well-meaning improvement.

    rerank is lexical overlap. A 0.92 beside a row would be a number the system
    cannot honestly produce, and the person reading it would take it for
    semantic confidence."""
    _install(monkeypatch, ROWS)
    body = await brain_api.brain_search(q="salt", limit=20)
    for row in body["results"]:
        assert not any(k in row for k in ("score", "relevance", "similarity", "rank")), row


@pytest.mark.asyncio
async def test_a_capped_result_set_says_so(monkeypatch):
    """Discriminating pair: truncated must be True only when it really is."""
    _install(monkeypatch, ROWS)
    body = await brain_api.brain_search(q="salt", limit=2)
    assert body["truncated"] is True
    assert len(body["results"]) == 2

    body = await brain_api.brain_search(q="salt", limit=20)
    assert body["truncated"] is False
    assert len(body["results"]) == 3


@pytest.mark.asyncio
async def test_browsing_your_own_memory_does_not_count_as_the_agent_using_it(monkeypatch):
    """Otherwise the activity strip starts measuring the person looking at it:
    every search would bump the usage counters that the strip draws from."""
    svc = _install(monkeypatch, ROWS)
    await brain_api.brain_search(q="salt", limit=20)
    assert svc.calls[0]["record_usage"] is False


@pytest.mark.asyncio
async def test_results_carry_the_matched_text(monkeypatch):
    """Decision: snippets are returned, so a hit can be judged without opening
    it. Asserted on content rather than on the key existing — an empty string
    would satisfy `"snippet" in row`."""
    _install(monkeypatch, ROWS)
    body = await brain_api.brain_search(q="salt", limit=20)
    assert "crypto_salt" in body["results"][0]["snippet"]
    assert body["results"][0]["kind"] == "fact"
    assert body["results"][0]["ref"] == "12"


@pytest.mark.asyncio
async def test_a_long_body_is_capped_rather_than_returned_whole(monkeypatch):
    """The snippet is a new data outlet; it should stay a snippet."""
    _install(monkeypatch, [("note:1", "x" * 5000)])
    body = await brain_api.brain_search(q="x", limit=20)
    assert len(body["results"][0]["snippet"]) <= 400


@pytest.mark.asyncio
async def test_an_unreadable_embedding_provider_degrades_to_lexical(monkeypatch):
    """A failure to answer "are embeddings on" must not fail the search, and
    must not claim hybrid."""
    from server.services import embedding_service, knowledge

    svc = _Svc(ROWS)
    monkeypatch.setattr(knowledge, "retrieve_scoped", svc.retrieve_scoped)

    async def boom():
        raise RuntimeError("no provider")

    monkeypatch.setattr(embedding_service, "active_provider", boom)
    body = await brain_api.brain_search(q="salt", limit=20)
    assert body["ranking"] == "lexical"
    assert body["results"]
