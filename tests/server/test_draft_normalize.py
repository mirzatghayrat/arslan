"""Draft normalization: LLM `capabilities` may arrive as a comma-joined string."""
from __future__ import annotations

from server.services import spawn_service


def test_capabilities_list_passthrough():
    assert spawn_service.normalize_capabilities(["a", "b"]) == ["a", "b"]


def test_capabilities_comma_string_is_split():
    # the exact shape DeepSeek returned that crashed the create-spawn card
    out = spawn_service.normalize_capabilities("互联网数据采集,数据分析与可视化,撰写数据分析报告")
    assert out == ["互联网数据采集", "数据分析与可视化", "撰写数据分析报告"]


def test_capabilities_handles_fullwidth_comma_and_whitespace():
    assert spawn_service.normalize_capabilities(" a ，b , c ") == ["a", "b", "c"]


def test_capabilities_none_and_garbage_become_empty_list():
    assert spawn_service.normalize_capabilities(None) == []
    assert spawn_service.normalize_capabilities(42) == []
    assert spawn_service.normalize_capabilities("") == []


def test_normalize_draft_coerces_capabilities_and_preserves_other_fields():
    draft = {"name": "x", "domain": "finance.research", "capabilities": "a,b", "persona_role": "r"}
    out = spawn_service.normalize_draft(draft)
    assert out["capabilities"] == ["a", "b"]
    assert out["name"] == "x" and out["domain"] == "finance.research" and out["persona_role"] == "r"
    # does not mutate the input
    assert draft["capabilities"] == "a,b"


def test_normalize_draft_non_dict_returns_empty():
    assert spawn_service.normalize_draft(None) == {}
    assert spawn_service.normalize_draft("nope") == {}
