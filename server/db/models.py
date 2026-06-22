"""SQLAlchemy ORM models for the Arslan server."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Spawn(Base):
    __tablename__ = "spawns"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    domain_category = Column(String(50), nullable=False)
    domain_subcategory = Column(String(50), nullable=True)
    capabilities = Column(JSON, default=list)
    persona_role = Column(String(200), nullable=True)
    persona_tone = Column(String(50), nullable=True)
    system_prompt = Column(Text, nullable=False)
    template_used = Column(String(100), nullable=True)
    generation_level = Column(Integer, default=1)
    config = Column(JSON, default=dict)
    level = Column(Integer, default=1)            # 1-10; reserved for future leveling (stays 1 in v2)
    memory_facts = Column(JSON, default=list)     # per-spawn learned preferences (reserved)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "ChatMessage", back_populates="spawn", cascade="all, delete-orphan"
    )
    feedback_entries = relationship(
        "Feedback", back_populates="spawn", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    spawn = relationship("Spawn", back_populates="messages")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id"), nullable=False)
    session_id = Column(String(50), nullable=False)
    message_id = Column(Integer, nullable=True)
    user_action = Column(String(20), nullable=False)
    edits = Column(JSON, default=dict)
    quality_signal = Column(Integer, nullable=True)  # -1 | 0 | +1 (reserved leveling signal)
    timestamp = Column(DateTime, default=datetime.utcnow)

    spawn = relationship("Spawn", back_populates="feedback_entries")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)


class BuildSession(Base):
    """Persisted in-progress spawn-build dialogue; enables WebSocket resume."""

    __tablename__ = "build_sessions"

    session_id = Column(String(50), primary_key=True)
    state_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArslanMessage(Base):
    """The orchestrator conversation (Layer 1). display != memory at the row level."""

    __tablename__ = "arslan_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "arslan" | "spawn_summary"
    content = Column(Text, nullable=False)          # CONTEXT copy fed to Arslan's LLM
    display_content = Column(Text, nullable=True)   # DISPLAY copy rendered in the UI (full spawn output)
    spawn_id = Column(Integer, ForeignKey("spawns.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ArslanSummary(Base):
    """Rolling compaction summary of older working memory."""

    __tablename__ = "arslan_summaries"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    up_to_message_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserFact(Base):
    """Long-term memory (scope 3): durable user preferences / key facts."""

    __tablename__ = "user_facts"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    source = Column(String(20), default="auto")  # "auto" | "manual"
    sensitive = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RouterDecision(Base):
    """Audit log of every router decision (logged + testable)."""

    __tablename__ = "router_decisions"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    user_message = Column(Text, nullable=False)
    action = Column(String(20), nullable=False)  # answer | route | suggest_create | fallback
    # Intentionally NOT a ForeignKey: audit log — rows must survive spawn deletion
    # with the historical id intact (dangling ids are expected; see delete_spawn).
    spawn_id = Column(Integer, nullable=True)
    task_brief = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    raw = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Toolset(Base):
    """Registry: a named executable tool group (a spawn's 'interface')."""

    __tablename__ = "toolsets"

    key = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    tier = Column(String(20), nullable=False)    # "safe" | "orchestrator"
    status = Column(String(20), nullable=False, default="registered")
    # "wired" | "registered" | "absorbed" | "infeasible"
    backend_note = Column(Text, nullable=True)


class Tool(Base):
    """Registry: one tool inside a toolset; READ/WRITE splits live at this level."""

    __tablename__ = "tools"

    key = Column(String(50), primary_key=True)
    toolset_key = Column(
        String(50), ForeignKey("toolsets.key", ondelete="CASCADE"), nullable=False, index=True
    )
    description = Column(Text, nullable=False)
    tier = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="registered")
    input_schema = Column(JSON, default=dict)


class SkillPack(Base):
    """Registry: SKILL.md-style capability pack (technique, not execution)."""

    __tablename__ = "skill_packs"

    key = Column(String(60), primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(40), nullable=False)
    description = Column(Text, nullable=False)
    tier = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="registered")
    body = Column(Text, nullable=True)


class SpawnCapability(Base):
    """Per-spawn equipment row (toolset or skill grant)."""

    __tablename__ = "spawn_capabilities"
    __table_args__ = (UniqueConstraint("spawn_id", "kind", "ref_key"),)

    id = Column(Integer, primary_key=True)
    spawn_id = Column(
        Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(10), nullable=False)   # "toolset" | "skill"
    ref_key = Column(String(60), nullable=False)
    grant = Column(String(10), nullable=False, default="permanent")  # "permanent" | "temporary"
    granted_by = Column(String(20), nullable=False, default="create")  # "create" | "escalation" | "user"
    expires_turn = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SpawnPhase(Base):
    """Staged-orchestration phase state per conversation (one pending proposal at a time)."""

    __tablename__ = "spawn_phases"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    spawn_id = Column(Integer, nullable=False)
    phase = Column(String(20), nullable=False)   # 'proposing'
    direction = Column(Text, nullable=False, default="")
    updated_at = Column(String(50), nullable=False, default="")


class ConversationSpawn(Base):
    """Per-conversation spawn roster membership (conversation-workbench #2)."""

    __tablename__ = "conversation_spawns"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id"), nullable=False)
    joined_via = Column(String(16), nullable=False)  # "routed" | "created" | "invited"
    joined_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("conversation_id", "spawn_id", name="uq_conversation_spawn"),
    )
