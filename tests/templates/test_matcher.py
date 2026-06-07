"""Tests for TagMatcher — Jaccard similarity scoring and ranking."""
import pytest

from arslan.templates.matcher import TagMatcher


@pytest.fixture
def matcher() -> TagMatcher:
    return TagMatcher()


# ---------------------------------------------------------------------------
# score() tests
# ---------------------------------------------------------------------------


def test_score_exact_match_above_threshold(matcher: TagMatcher) -> None:
    """Identical tag sets yield score > 0.5 (in fact, 1.0)."""
    tags = ["python", "web", "api"]
    s = matcher.score(tags, tags)
    assert s > 0.5
    assert s == pytest.approx(1.0)


def test_score_no_match_returns_zero(matcher: TagMatcher) -> None:
    """Completely disjoint tag sets return 0.0."""
    s = matcher.score(["a", "b"], ["c", "d"])
    assert s == 0.0


def test_score_partial_match_between_zero_and_one(matcher: TagMatcher) -> None:
    """Partially overlapping tag sets return a score strictly between 0 and 1."""
    s = matcher.score(["a", "b", "c"], ["b", "c", "d"])
    # intersection={b,c}, union={a,b,c,d} → 2/4 = 0.5
    assert 0.0 < s < 1.0
    assert s == pytest.approx(0.5)


def test_score_empty_query_returns_zero(matcher: TagMatcher) -> None:
    """Empty query_tags returns 0.0 regardless of template tags."""
    assert matcher.score([], ["a", "b"]) == 0.0


def test_score_empty_template_returns_zero(matcher: TagMatcher) -> None:
    """Empty template_tags returns 0.0 regardless of query tags."""
    assert matcher.score(["a", "b"], []) == 0.0


def test_score_both_empty_returns_zero(matcher: TagMatcher) -> None:
    """Both empty lists return 0.0."""
    assert matcher.score([], []) == 0.0


def test_score_case_insensitive(matcher: TagMatcher) -> None:
    """Tag comparison is case-insensitive."""
    s = matcher.score(["Python", "WEB"], ["python", "web"])
    assert s == pytest.approx(1.0)


def test_score_single_common_tag(matcher: TagMatcher) -> None:
    """Single shared tag among several yields correct Jaccard score."""
    # intersection={b}, union={a,b,c,d,e} → 1/5 = 0.2
    s = matcher.score(["a", "b", "c"], ["b", "d", "e"])
    assert s == pytest.approx(1 / 5)


# ---------------------------------------------------------------------------
# rank() tests
# ---------------------------------------------------------------------------


def test_rank_returns_sorted_by_score_descending(matcher: TagMatcher) -> None:
    """rank() returns templates sorted from highest to lowest score."""
    templates = [
        {"name": "low", "tags": ["z"]},
        {"name": "high", "tags": ["a", "b", "c"]},
        {"name": "mid", "tags": ["a", "b", "x"]},
    ]
    results = matcher.rank(["a", "b", "c"], templates)
    assert results[0]["name"] == "high"
    scores = [r["_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_rank_adds_score_key(matcher: TagMatcher) -> None:
    """rank() adds '_score' to each result dict."""
    templates = [{"name": "t", "tags": ["a"]}]
    results = matcher.rank(["a"], templates)
    assert "_score" in results[0]
    assert isinstance(results[0]["_score"], float)


def test_rank_winner_first(matcher: TagMatcher) -> None:
    """The best-matching template is the first element in rank results."""
    templates = [
        {"name": "unrelated", "tags": ["x", "y"]},
        {"name": "perfect", "tags": ["alpha", "beta", "gamma"]},
    ]
    results = matcher.rank(["alpha", "beta", "gamma"], templates)
    assert results[0]["name"] == "perfect"


def test_rank_min_score_filters_results(matcher: TagMatcher) -> None:
    """Templates below min_score threshold are excluded."""
    templates = [
        {"name": "zero", "tags": ["z"]},
        {"name": "match", "tags": ["a"]},
    ]
    results = matcher.rank(["a", "b"], templates, min_score=0.1)
    names = [r["name"] for r in results]
    assert "zero" not in names
    assert "match" in names


def test_rank_empty_templates_returns_empty(matcher: TagMatcher) -> None:
    """Ranking an empty template list returns an empty list."""
    assert matcher.rank(["a", "b"], []) == []


def test_rank_does_not_mutate_original(matcher: TagMatcher) -> None:
    """rank() does not modify the original template dicts."""
    original = {"name": "t", "tags": ["a"]}
    templates = [original]
    matcher.rank(["a"], templates)
    assert "_score" not in original


def test_rank_zero_min_score_includes_all(matcher: TagMatcher) -> None:
    """With min_score=0.0, all templates (even score-0 ones) are included."""
    templates = [
        {"name": "no-match", "tags": ["z"]},
        {"name": "match", "tags": ["a"]},
    ]
    results = matcher.rank(["a"], templates, min_score=0.0)
    assert len(results) == 2
