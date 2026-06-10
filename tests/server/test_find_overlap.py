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
