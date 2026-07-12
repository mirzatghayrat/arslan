"""Tests for arslan.models — written TDD before implementation."""

from arslan.models import (
    DomainInfo,
    EvolutionRule,
    FeedbackEntry,
    LLMResponse,
    PersonaSpec,
    RuntimeSpec,
    SpawnBlueprint,
    SpawnRequirements,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

class TestToolSpec:
    def test_minimal_creation(self):
        tool = ToolSpec(
            name="echo",
            description="Echoes input",
            input_schema={},
            output_schema={},
        )
        assert tool.name == "echo"
        assert tool.tags == []
        assert tool.source is None
        assert tool.config == {}

    def test_full_creation(self):
        tool = ToolSpec(
            name="web_search",
            description="Search the web",
            tags=["search", "web"],
            source="serpapi",
            config={"api_key_env": "SERP_API_KEY"},
            input_schema={"query": {"type": "string"}},
            output_schema={"results": {"type": "array"}},
        )
        assert tool.name == "web_search"
        assert "search" in tool.tags
        assert tool.source == "serpapi"
        assert tool.config["api_key_env"] == "SERP_API_KEY"


# ---------------------------------------------------------------------------
# DomainInfo
# ---------------------------------------------------------------------------

class TestDomainInfo:
    def test_full_domain_with_subcategory(self):
        domain = DomainInfo(category="content-creator", subcategory="xiaohongshu")
        assert domain.full_domain == "content-creator.xiaohongshu"

    def test_full_domain_without_subcategory(self):
        domain = DomainInfo(category="customer-service")
        assert domain.full_domain == "customer-service"

    def test_subcategory_defaults_to_none(self):
        domain = DomainInfo(category="data-analysis")
        assert domain.subcategory is None


# ---------------------------------------------------------------------------
# PersonaSpec
# ---------------------------------------------------------------------------

class TestPersonaSpec:
    def test_creation_with_defaults(self):
        persona = PersonaSpec(role="Assistant")
        assert persona.role == "Assistant"
        assert persona.tone == ""
        assert persona.constraints == []

    def test_full_creation(self, sample_persona):
        assert sample_persona.role == "资深美妆博主"
        assert sample_persona.tone == "数据实测型"
        assert "不推荐未经验证的产品" in sample_persona.constraints


# ---------------------------------------------------------------------------
# RuntimeSpec
# ---------------------------------------------------------------------------

class TestRuntimeSpec:
    def test_defaults(self):
        runtime = RuntimeSpec()
        assert runtime.platform == "web"
        assert runtime.trigger == "user"
        assert runtime.schedule is None

    def test_custom_values(self):
        runtime = RuntimeSpec(platform="cli", trigger="schedule", schedule="0 9 * * *")
        assert runtime.platform == "cli"
        assert runtime.schedule == "0 9 * * *"


# ---------------------------------------------------------------------------
# SpawnRequirements
# ---------------------------------------------------------------------------

class TestSpawnRequirements:
    def test_is_complete_when_all_fields_present(self, sample_requirements):
        assert sample_requirements.is_complete is True

    def test_is_complete_missing_spawn_name(self, sample_domain, sample_persona):
        req = SpawnRequirements(
            domain=sample_domain,
            capabilities=["content-generation"],
            persona=sample_persona,
        )
        assert req.is_complete is False

    def test_is_complete_missing_domain(self, sample_persona):
        req = SpawnRequirements(
            spawn_name="My Agent",
            capabilities=["content-generation"],
            persona=sample_persona,
        )
        assert req.is_complete is False

    def test_is_complete_empty_capabilities(self, sample_domain, sample_persona):
        req = SpawnRequirements(
            spawn_name="My Agent",
            domain=sample_domain,
            capabilities=[],
            persona=sample_persona,
        )
        assert req.is_complete is False

    def test_is_complete_missing_persona(self, sample_domain):
        req = SpawnRequirements(
            spawn_name="My Agent",
            domain=sample_domain,
            capabilities=["content-generation"],
        )
        assert req.is_complete is False

    def test_defaults(self):
        req = SpawnRequirements()
        assert req.spawn_name is None
        assert req.domain is None
        assert req.capabilities == []
        assert req.persona is None
        assert req.research_results == {}
        assert req.is_complete is False


# ---------------------------------------------------------------------------
# SpawnBlueprint
# ---------------------------------------------------------------------------

class TestSpawnBlueprint:
    def test_creation(self, sample_requirements, sample_tool):
        blueprint = SpawnBlueprint(
            requirements=sample_requirements,
            tools=[sample_tool],
            system_prompt="You are a helpful assistant.",
            workflow_steps=[{"step": 1, "action": "greet"}],
        )
        assert blueprint.generation_level == 1
        assert blueprint.template_used is None
        assert len(blueprint.tools) == 1
        assert blueprint.system_prompt == "You are a helpful assistant."


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------

class TestLLMResponse:
    def test_text_response(self):
        resp = LLMResponse(content="Hello!", usage={"input_tokens": 10, "output_tokens": 5})
        assert resp.role == "assistant"
        assert resp.content == "Hello!"
        assert resp.tool_calls == []

    def test_tool_call_response(self):
        tool_call = {"id": "call_1", "name": "web_search", "input": {"query": "test"}}
        resp = LLMResponse(
            tool_calls=[tool_call],
            usage={"input_tokens": 20, "output_tokens": 15},
        )
        assert resp.content is None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["name"] == "web_search"


# ---------------------------------------------------------------------------
# EvolutionRule
# ---------------------------------------------------------------------------

class TestEvolutionRule:
    def _make_rule(self, confidence: float, sample_size: int) -> EvolutionRule:
        return EvolutionRule(
            rule_type="tone",
            rule="Use formal language",
            confidence=confidence,
            sample_size=sample_size,
            examples_good=["Example A"],
            examples_bad=["Example B"],
            learned_at="2024-01-01T00:00:00Z",
        )

    def test_is_active_when_conditions_met(self):
        rule = self._make_rule(confidence=0.7, sample_size=25)
        assert rule.is_active is True

    def test_is_active_exact_boundary(self):
        rule = self._make_rule(confidence=0.5, sample_size=20)
        assert rule.is_active is True

    def test_not_active_low_confidence(self):
        rule = self._make_rule(confidence=0.4, sample_size=25)
        assert rule.is_active is False

    def test_not_active_low_sample_size(self):
        rule = self._make_rule(confidence=0.8, sample_size=15)
        assert rule.is_active is False

    def test_not_active_both_low(self):
        rule = self._make_rule(confidence=0.3, sample_size=5)
        assert rule.is_active is False


# ---------------------------------------------------------------------------
# FeedbackEntry
# ---------------------------------------------------------------------------

class TestFeedbackEntry:
    def test_creation(self):
        entry = FeedbackEntry(
            session_id="sess_001",
            user_input="Build me a chatbot",
            agent_output="Here is your chatbot spec...",
            user_action="accepted",
            edits={},
            timestamp="2024-01-01T12:00:00Z",
        )
        assert entry.session_id == "sess_001"
        assert entry.user_action == "accepted"
        assert entry.edits == {}
