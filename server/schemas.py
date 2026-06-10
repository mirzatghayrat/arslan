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


class SettingsOut(BaseModel):
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""  # masked
    language: str = "en"
    search_provider: str = "tavily"
    search_api_key: str = ""  # masked


class EquipmentItemOut(BaseModel):
    key: str
    name: str
    status: str
    grant: str = "permanent"


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


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    timestamp: str


class SpawnDetailOut(SpawnOut):
    persona_role: str | None = None
    persona_tone: str | None = None
    system_prompt: str = ""
    messages: list[ChatMessageOut] = []


class DraftIn(BaseModel):
    description: str


class SpawnCreateIn(BaseModel):
    name: str
    domain: str  # free-form "category.subcategory"
    capabilities: list[str] = []
    persona_role: str | None = None
    persona_tone: str | None = None
    equipment: dict | None = None


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
