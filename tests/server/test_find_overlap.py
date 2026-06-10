"""Deterministic spawn-overlap detection (name- or full-domain-matched; never category alone)."""
from __future__ import annotations

from types import SimpleNamespace

from server.services import spawn_service


def _spawn(id, name, category, subcategory=None):
    return SimpleNamespace(id=id, name=name, domain_category=category, domain_subcategory=subcategory)


def test_name_match_including_suffix():
    existing = [_spawn(3, "数据研究", "data-analysis", "internet")]
    out = spawn_service.find_overlap({"name": "数据研究", "domain": "data-analysis.report"}, existing)
    assert out == {"spawn_id": 3, "name": "数据研究", "axes": []}
    existing2 = [_spawn(5, "数据研究-2", "data-analysis", "internet")]
    assert spawn_service.find_overlap({"name": "数据研究", "domain": "x.y"}, existing2)["spawn_id"] == 5


def test_full_domain_match_under_different_name():
    existing = [_spawn(7, "互联网分析师", "data-analysis", "internet")]
    out = spawn_service.find_overlap({"name": "数小析", "domain": "data-analysis.internet"}, existing)
    assert out == {"spawn_id": 7, "name": "互联网分析师", "axes": []}


def test_same_category_different_subcategory_does_NOT_collide():
    existing = [_spawn(9, "股票研究", "finance", "equity-research")]
    assert spawn_service.find_overlap({"name": "加密研究", "domain": "finance.crypto"}, existing) is None


def test_category_only_no_subcategory_does_not_match_on_domain():
    existing = [_spawn(1, "A", "data-analysis", None)]
    assert spawn_service.find_overlap({"name": "B", "domain": "data-analysis"}, existing) is None


def test_empty_registry_and_blank_name():
    assert spawn_service.find_overlap({"name": "x", "domain": "y.z"}, []) is None
    assert spawn_service.find_overlap({"name": "", "domain": ""}, [_spawn(1, "x", "y", "z")]) is None


# ---------------------------------------------------------------------------
# Task 6: pairwise overlap rule (plan §Task 6, Step 1)
# ---------------------------------------------------------------------------

class _S:
    def __init__(self, id, name, cat="d", sub=None):
        self.id = id
        self.name = name
        self.domain_category = cat
        self.domain_subcategory = sub


def test_suffix_overmatch_fixed():
    """top-10 must NOT overlap top-1 (old behavior stripped both to 'top')."""
    assert spawn_service.find_overlap({"name": "top-10"}, [_S(1, "top-1")]) is None


def test_suffix_dedup_still_matches():
    """data-2 still overlaps data — the auto-suffix case the rule exists for."""
    hit = spawn_service.find_overlap({"name": "data-2"}, [_S(1, "data")])
    assert hit and hit["spawn_id"] == 1
    hit = spawn_service.find_overlap({"name": "data"}, [_S(1, "data-2")])
    assert hit and hit["spawn_id"] == 1


def test_exact_numeric_name_matches_itself():
    hit = spawn_service.find_overlap({"name": "gpt-4"}, [_S(1, "GPT-4")])
    assert hit and hit["spawn_id"] == 1
