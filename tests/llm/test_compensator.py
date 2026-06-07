"""Tests for the QualityCompensator."""
from __future__ import annotations

import pytest

from arslan.llm.compensator import QualityCompensator
from arslan.models import CapabilityProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def strong_profile() -> CapabilityProfile:
    return CapabilityProfile(
        name="claude-opus",
        provider="anthropic",
        reasoning=5,
        tool_use=5,
        chinese=4,
        creative=5,
        instruction=5,
        max_context=200000,
        cost_per_1k_tokens=0.015,
    )


@pytest.fixture
def weak_profile() -> CapabilityProfile:
    """reasoning=3 (NOT weak), tool_use=2 (weak), chinese=2 (weak), instruction=3 (NOT weak)."""
    return CapabilityProfile(
        name="llama-3-70b",
        provider="ollama",
        reasoning=3,
        tool_use=2,
        chinese=2,
        creative=3,
        instruction=3,
        max_context=8000,
        cost_per_1k_tokens=0.0,
    )


@pytest.fixture
def fully_weak_profile() -> CapabilityProfile:
    """All compensated caps are weak (< 3)."""
    return CapabilityProfile(
        name="tiny-llm",
        provider="ollama",
        reasoning=2,
        tool_use=1,
        chinese=2,
        creative=2,
        instruction=2,
        max_context=4096,
        cost_per_1k_tokens=0.0,
    )


# ---------------------------------------------------------------------------
# Test 1 – Strong model: prompt returned unchanged
# ---------------------------------------------------------------------------

def test_strong_model_prompt_unchanged(strong_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(strong_profile)
    prompt = "Explain quantum entanglement."
    assert compensator.compensate_prompt(prompt, task_type="reasoning") == prompt
    assert compensator.compensate_prompt(prompt, task_type="tool_use") == prompt
    assert compensator.compensate_prompt(prompt, task_type="chinese") == prompt
    assert compensator.compensate_prompt(prompt, task_type="general") == prompt


# ---------------------------------------------------------------------------
# Test 2 – Weak reasoning: adds CoT hint
# ---------------------------------------------------------------------------

def test_weak_reasoning_adds_cot(fully_weak_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(fully_weak_profile)
    result = compensator.compensate_prompt("Solve the puzzle.", task_type="reasoning")
    lower = result.lower()
    assert "step by step" in lower or "逐步" in result


# ---------------------------------------------------------------------------
# Test 3 – Weak tool_use: adds ReAct prefix
# ---------------------------------------------------------------------------

def test_weak_tool_use_adds_react(weak_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(weak_profile)
    result = compensator.compensate_prompt("Search for the weather.", task_type="tool_use")
    # Should mention Thought/思考 pattern
    assert "思考" in result or "Thought" in result or "thought" in result.lower()


# ---------------------------------------------------------------------------
# Test 4 – Weak chinese: adds English-then-Chinese hint
# ---------------------------------------------------------------------------

def test_weak_chinese_adds_language_hint(weak_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(weak_profile)
    result = compensator.compensate_prompt("写一篇文章", task_type="chinese")
    lower = result.lower()
    assert "english" in lower or "英文" in result


# ---------------------------------------------------------------------------
# Test 5 – get_strategies returns only active (True) strategies
# ---------------------------------------------------------------------------

def test_get_strategies_only_active(weak_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(weak_profile)
    strategies = compensator.get_strategies()
    # tool_use=2 and chinese=2 are weak → active
    assert strategies.get("tool_use") is True
    assert strategies.get("chinese") is True
    # reasoning=3 and instruction=3 are NOT weak (threshold is strictly < 3)
    assert "reasoning" not in strategies
    assert "instruction" not in strategies
    # All values in the returned dict must be True
    assert all(v is True for v in strategies.values())


def test_get_strategies_empty_for_strong_model(strong_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(strong_profile)
    strategies = compensator.get_strategies()
    assert strategies == {}


# ---------------------------------------------------------------------------
# Test 6 – parse_react_output with valid ReAct text
# ---------------------------------------------------------------------------

def test_parse_react_output_valid() -> None:
    # Use a minimal profile; parse_react_output is profile-independent
    profile = CapabilityProfile(
        name="x", provider="y", reasoning=1, tool_use=1, chinese=1,
        creative=1, instruction=1, max_context=1000, cost_per_1k_tokens=0.0,
    )
    compensator = QualityCompensator(profile)

    text = (
        "思考：I need to search for weather.\n"
        "工具：web_search\n"
        '参数：{"query": "Beijing weather today"}'
    )
    result = compensator.parse_react_output(text)
    assert result is not None
    assert result["tool"] == "web_search"
    assert result["params"] == {"query": "Beijing weather today"}


def test_parse_react_output_valid_colon_variants() -> None:
    """Support both full-width ： and ASCII : separators."""
    profile = CapabilityProfile(
        name="x", provider="y", reasoning=1, tool_use=1, chinese=1,
        creative=1, instruction=1, max_context=1000, cost_per_1k_tokens=0.0,
    )
    compensator = QualityCompensator(profile)

    text = (
        "工具: search_tool\n"
        '参数: {"q": "test"}'
    )
    result = compensator.parse_react_output(text)
    assert result is not None
    assert result["tool"] == "search_tool"
    assert result["params"] == {"q": "test"}


# ---------------------------------------------------------------------------
# Test 7 – parse_react_output with no tool reference returns None
# ---------------------------------------------------------------------------

def test_parse_react_output_no_tool() -> None:
    profile = CapabilityProfile(
        name="x", provider="y", reasoning=1, tool_use=1, chinese=1,
        creative=1, instruction=1, max_context=1000, cost_per_1k_tokens=0.0,
    )
    compensator = QualityCompensator(profile)

    result = compensator.parse_react_output("Just a regular response with no tool calls.")
    assert result is None


# ---------------------------------------------------------------------------
# Test 8 – parse_react_output with invalid JSON params falls back to raw
# ---------------------------------------------------------------------------

def test_parse_react_output_invalid_json_params() -> None:
    profile = CapabilityProfile(
        name="x", provider="y", reasoning=1, tool_use=1, chinese=1,
        creative=1, instruction=1, max_context=1000, cost_per_1k_tokens=0.0,
    )
    compensator = QualityCompensator(profile)

    text = (
        "工具：my_tool\n"
        "参数：not valid json at all"
    )
    result = compensator.parse_react_output(text)
    assert result is not None
    assert result["tool"] == "my_tool"
    assert result["params"] == {"raw": "not valid json at all"}


# ---------------------------------------------------------------------------
# Test 9 – Weak instruction wraps prompt in emphasis markers
# ---------------------------------------------------------------------------

def test_weak_instruction_wraps_prompt(fully_weak_profile: CapabilityProfile) -> None:
    compensator = QualityCompensator(fully_weak_profile)
    prompt = "Do the task carefully."
    result = compensator.compensate_prompt(prompt, task_type="general")
    # Must contain the original prompt AND some emphasis wrapper
    assert prompt in result
    assert result != prompt  # something was added
