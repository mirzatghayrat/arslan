"""Pydantic DTOs for request bodies and responses."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class SettingsIn(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    language: str | None = None
    search_provider: str | None = None
    search_api_key: str | None = None
    llm_strategy: str | None = None
    distill_on_session_end: bool | None = None
    orchestrator_shell_enabled: str | None = None
    shell_confirm_policy: str | None = None


class SettingsOut(BaseModel):
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""  # masked
    language: str = "en"
    search_provider: str = "tavily"
    search_api_key: str = ""  # masked
    llm_strategy: str = "single"
    distill_on_session_end: bool = True
    orchestrator_shell_enabled: str = ""
    shell_confirm_policy: str = ""


class ProviderOption(BaseModel):
    """One entry in the Settings provider dropdown (Tier-0 preset or native)."""

    key: str
    label: str
    base_url: str = ""
    default_model: str = ""
    native: bool = False
    models: list[str] = []


class ProviderConfigIn(BaseModel):
    label: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""


class ProviderConfigUpdateIn(BaseModel):
    label: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class ProviderConfigOut(BaseModel):
    id: int
    label: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""   # masked
    is_primary: bool = False


class EquipmentItemOut(BaseModel):
    key: str
    name: str
    status: str
    grant: str = "permanent"
    granted_by: str = "create"
    expires_turn: int | None = None


class EquipmentOut(BaseModel):
    toolsets: list[EquipmentItemOut] = []
    skills: list[EquipmentItemOut] = []

    @classmethod
    def from_dict(cls, eq: dict) -> "EquipmentOut":
        def items(rows):
            return [
                EquipmentItemOut(
                    key=r["key"], name=r["name"], status=r["status"],
                    grant=r.get("grant", "permanent"),
                    granted_by=r.get("granted_by", "create"),
                    expires_turn=r.get("expires_turn"),
                )
                for r in rows
            ]
        return cls(toolsets=items(eq.get("toolsets", [])), skills=items(eq.get("skills", [])))


class SpawnOut(BaseModel):
    id: int
    name: str
    domain: str
    capabilities: list[str]
    template_used: str | None = None
    generation_level: int = 1
    created_at: str
    updated_at: str
    equipment: EquipmentOut = EquipmentOut()
    has_active_chat: bool = False
    is_default: bool = False   # built-in agent: shipped with the app, cannot be deleted


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    timestamp: str


class SeedRefOut(BaseModel):
    """A persona seed (one of the 249 in the library), resolved for display."""
    slug: str
    name: str | None = None
    division: str | None = None
    summary: str | None = None


class SpawnDetailOut(SpawnOut):
    persona_role: str | None = None
    persona_tone: str | None = None
    system_prompt: str = ""
    messages: list[ChatMessageOut] = []
    # The persona seeds this spawn was composed from (resolved from config.seed_refs).
    seeds: list[SeedRefOut] = []


class DraftIn(BaseModel):
    description: str


class SpawnCreateIn(BaseModel):
    name: str
    domain: str  # free-form "category.subcategory"
    capabilities: list[str] = []
    seed_refs: list[str] = []   # persona-seed slugs this spawn is composed from
    persona_role: str | None = None
    persona_tone: str | None = None
    equipment: dict | None = None


class EquipmentUpdateIn(BaseModel):
    toolsets: list[str] = []
    skills: list[str] = []


class ConfigUpdateIn(BaseModel):
    system_prompt: str | None = None
    persona_tone: str | None = None
    persona_role: str | None = None
    config: dict[str, Any] | None = None


class TemplateOut(BaseModel):
    name: str
    domain: str
    description: str = ""
    tags: list[str] = []


class FeedbackIn(BaseModel):
    message_id: int | None = None
    user_action: Literal["thumbs_up", "thumbs_down", "edit", "regenerate", "redo", "refine"]
    edits: dict[str, Any] = {}


class EvolutionRuleOut(BaseModel):
    rule_type: str
    rule: str
    confidence: float
    sample_size: int


class EvolutionOut(BaseModel):
    feedback_count: int
    active_rules: list[EvolutionRuleOut]


class FactIn(BaseModel):
    content: str
    sensitive: bool = False


class FactUpdate(BaseModel):
    content: str | None = None
    sensitive: bool | None = None


class FactOut(BaseModel):
    id: int
    content: str
    source: str
    sensitive: bool
    category: str | None = None


class ToolOut(BaseModel):
    key: str
    description: str
    tier: str
    status: str


class ToolsetOut(BaseModel):
    key: str
    name: str
    description: str
    tier: str
    status: str
    assignable: bool
    tools: list[ToolOut] = []


class SkillPackOut(BaseModel):
    key: str
    name: str
    category: str
    description: str
    tier: str
    status: str
    assignable: bool


class RegistryOut(BaseModel):
    toolsets: list[ToolsetOut]
    skills: list[SkillPackOut]


class SuggestPrimaryOut(BaseModel):
    id: int
    provider: str
    rationale: str


class TestLLMIn(BaseModel):
    """Body for POST /settings/test-llm."""

    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str = ""


class TestLLMOut(BaseModel):
    """Response from both test-connection endpoints."""

    ok: bool
    error: str | None = None
    latency_ms: int | None = None


class CatalogCapabilities(BaseModel):
    cost: int
    speed: int
    tool_calling: int
    reasoning: int
    long_context: int


class CatalogEntryOut(BaseModel):
    provider: str
    capabilities: CatalogCapabilities
    languages: dict[str, int]


class TitleIn(BaseModel):
    """Request body for POST /orchestrator/title."""

    first_message: str
    first_reply: str | None = None


class TitleOut(BaseModel):
    """Response from POST /orchestrator/title."""

    title: str


class RunStepOut(BaseModel):
    seq: int
    kind: str
    ref: dict
    detail: dict
    duration_ms: int | None


class RunEvaluationOut(BaseModel):
    dimension: str
    status: str
    score: float
    comment: str


class RunOut(BaseModel):
    id: int
    conversation_id: str
    spawn_id: int | None
    spawn_name: str | None
    user_message: str
    total_ms: int | None
    task_tokens: int
    status: str
    overall_score: float | None
    overall_badge: str | None


class RunDetailOut(BaseModel):
    run: RunOut
    steps: list[RunStepOut]
    evaluations: list[RunEvaluationOut]


class GateOut(BaseModel):
    passed: bool
    reason: str
    aggregate: dict | None = None


class EvolveProposalOut(BaseModel):
    proposal_id: int | None
    candidate_prompt: str | None
    gate: GateOut
    evidence: dict | None = None


class ConfirmProposalOut(BaseModel):
    ok: bool
    reason: str | None = None
    spawn_id: int | None = None
    generation_level: int | None = None


class KnowledgeIn(BaseModel):
    source: str | None = None
    text: str | None = None
    url: str | None = None
    compress: bool = False


class IngestOut(BaseModel):
    source: str
    chunks_added: int


class KnowledgeSourceOut(BaseModel):
    source: str
    chunks: int


class CollectionIn(BaseModel):
    name: str
    description: str | None = None


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None


class CollectionOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    chunks: int = 0
    sources: int = 0
    spawn_ids: list[int] = []


class RunListItemOut(BaseModel):
    id: int
    spawn_name: str | None
    status: str
    overall_score: float | None
    overall_badge: str | None
    total_ms: int | None
    user_message: str
    created_at: str | None = None


class RunSpawnSummaryOut(BaseModel):
    """Per-spawn aggregate over scored runs (GET /runs/summary)."""

    spawn_name: str
    scored_count: int
    avg_score: float | None
    pass_rate: int | None  # % of scored runs with overall_score >= 7


class RunTrendPointOut(BaseModel):
    """One recent run for the score-trend chart (null score = unscored)."""

    id: int
    overall_score: float | None
    created_at: str | None = None


class RunSummaryOut(BaseModel):
    """Aggregates for the evaluation-summary charts (GET /runs/summary)."""

    scored_count: int
    avg_score: float | None
    pass_rate: int | None  # 0-100, null when nothing scored
    dimension_averages: dict[str, float | None]
    per_spawn: list[RunSpawnSummaryOut]
    recent: list[RunTrendPointOut]


class SkillForgeIn(BaseModel):
    key: str
    name: str
    category: str = "meta"
    description: str
    body: str
    source: str = "skill_creator"


class SkillEvaluateIn(BaseModel):
    target_spawn_id: int
    min_samples: int = 8


class SkillCandidateOut(BaseModel):
    id: int
    key: str
    name: str
    category: str
    description: str
    status: str
    source: str
    created_at: str | None = None
    promoted_at: str | None = None


class PreferencesOut(BaseModel):
    preferences: list[str] = []


class PreferenceDeleteIn(BaseModel):
    fact: str
