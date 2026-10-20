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
