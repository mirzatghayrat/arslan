"""Arslan — Core Pydantic data models shared across all modules."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Specification for a single tool available to a spawn."""

    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class DomainInfo(BaseModel):
    """Domain classification for a spawn."""

    category: str
    subcategory: str | None = None

    @property
    def full_domain(self) -> str:
        """Return 'category.subcategory' or just 'category' when subcategory is absent."""
        if self.subcategory:
            return f"{self.category}.{self.subcategory}"
        return self.category


class PersonaSpec(BaseModel):
    """Persona configuration for a spawn."""

    role: str
    tone: str = ""
    constraints: list[str] = Field(default_factory=list)


class RuntimeSpec(BaseModel):
    """Runtime/deployment configuration for a spawn."""

    platform: str = "web"
    trigger: str = "user"
    schedule: str | None = None


class SpawnRequirements(BaseModel):
    """Accumulates user requirements during the dialogue phase."""

    spawn_name: str | None = None
    domain: DomainInfo | None = None
    capabilities: list[str] = Field(default_factory=list)
    persona: PersonaSpec | None = None
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    research_results: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """True when all essential fields are populated."""
        return (
            self.spawn_name is not None
            and self.domain is not None
            and len(self.capabilities) > 0
            and self.persona is not None
        )


class SpawnBlueprint(BaseModel):
    """The fully assembled blueprint for a spawn, ready for scaffolding."""

    requirements: SpawnRequirements
    tools: list[ToolSpec]
    system_prompt: str
    workflow_steps: list[dict[str, Any]]
    template_used: str | None = None
    generation_level: int = 1


class LLMResponse(BaseModel):
    """Normalised response from any LLM provider."""

    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any]


class EvolutionRule(BaseModel):
    """A learned behavioural rule produced by the evolution engine."""

    rule_type: str
    rule: str
    confidence: float = Field(ge=0.0, le=1.0)
    sample_size: int
    examples_good: list[str] = Field(default_factory=list)
    examples_bad: list[str] = Field(default_factory=list)
    learned_at: str

    @property
    def is_active(self) -> bool:
        """Active when confidence >= 0.5 AND sample_size >= 20."""
        return self.confidence >= 0.5 and self.sample_size >= 20


class FeedbackEntry(BaseModel):
    """A single user-feedback record used by the evolution engine."""

    session_id: str
    user_input: str
    agent_output: str
    user_action: str
    edits: dict[str, Any]
    timestamp: str
