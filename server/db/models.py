"""SQLAlchemy ORM models for the Arslan server."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
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
    is_default = Column(Boolean, nullable=False, default=False, server_default="0")  # built-in agent: shipped + undeletable
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
    archived = Column(Boolean, nullable=False, default=False, server_default="0")

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


class DistilledSession(Base):
    """Idempotency marker: a (conversation, spawn) pair already distilled into prefs."""

    __tablename__ = "distilled_sessions"
    __table_args__ = (UniqueConstraint("conversation_id", "spawn_id", name="uq_distilled_conv_spawn"),)

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    spawn_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)


class ArslanMessage(Base):
    """The orchestrator conversation (Layer 1). display != memory at the row level."""

    __tablename__ = "arslan_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "arslan" | "spawn_summary"
    content = Column(Text, nullable=False)          # CONTEXT copy fed to Arslan's LLM
    display_content = Column(Text, nullable=True)   # DISPLAY copy rendered in the UI (full spawn output)
    spawn_id = Column(Integer, ForeignKey("spawns.id"), nullable=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
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
    category = Column(String(30), nullable=True)
    label = Column(String(40), nullable=True)
    confidence = Column(Float, default=0.6)
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
    external_name = Column(String(120), nullable=True)   # original MCP tool name (NULL for built-ins)
    host_enabled = Column(Boolean, nullable=False, default=False, server_default="0")  # Arslan (host) may use this MCP tool


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


class SkillCandidate(Base):
    """An authored-but-not-yet-live skill draft awaiting human confirm.

    Slice 1 lifecycle: observing -> promoted | rejected (Slice 2 adds an eval
    gate before "proposed"; observing -> proposed -> promoted/rejected/retired).
    On promote we INSERT a live SkillPack row (tier=safe, status=registered) which
    is what makes the skill listed + equippable via the registry choke point.
    """

    __tablename__ = "skill_candidates"

    id = Column(Integer, primary_key=True)
    key = Column(String(60), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(40), nullable=False)
    description = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    source = Column(String(20), nullable=False, default="skill_creator")  # "skill_creator" | "user"
    status = Column(String(20), nullable=False, default="observing")
    # "observing" | "proposed" | "promoted" | "rejected" | "retired"
    samples = Column(JSON, default=list)   # reserved: Slice-2 observation refs
    evidence = Column(JSON, default=dict)  # reserved: Slice-2 eval evidence
    created_at = Column(DateTime, default=datetime.utcnow)
    promoted_at = Column(DateTime, nullable=True)


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


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True)
    label = Column(String(80), nullable=False)
    transport = Column(String(20), nullable=False, default="stdio")
    command = Column(String(255), nullable=False)
    args = Column(JSON, nullable=False, default=list)
    env = Column(Text, nullable=True)                    # encrypted JSON string (dict[str,str])
    url = Column(String(500), nullable=True)   # streamable-HTTP endpoint (transport="http")
    status = Column(String(20), nullable=False, default="registered")  # registered|connected|error
    last_error = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)    # PB-4: last on-demand health probe
    health_status = Column(String(20), nullable=True)    # PB-4: ok|failing|NULL=never checked
    created_at = Column(DateTime, default=datetime.utcnow)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(140), nullable=False, unique=True)   # owner/repo
    html_url = Column(String(500), nullable=True)
    snapshot = Column(JSON, nullable=False)                        # {repo, trust, suggestion}
    saved_at = Column(DateTime, default=datetime.utcnow)


class ProviderConfig(Base):
    """Multi-key BYOK provider configuration (one row per configured LLM provider key)."""

    __tablename__ = "provider_configs"

    id = Column(Integer, primary_key=True)
    label = Column(String(80), nullable=False)
    provider = Column(String(40), nullable=False)   # catalog key
    model = Column(String(120), nullable=False)
    base_url = Column(String(255), nullable=True)
    api_key = Column(Text, nullable=False)           # encrypted
    is_primary = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Run(Base):
    """One route→dispatch turn, recorded for replay + evaluation."""

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    # nullable + SET NULL: a replay must survive spawn deletion (spawn_name kept below).
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="SET NULL"), nullable=True)
    spawn_name = Column(String(100), nullable=True)
    user_message = Column(Text, nullable=False, default="")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    total_ms = Column(Integer, nullable=True)
    task_tokens = Column(Integer, nullable=False, default=0)   # router+dispatch+tools (NOT judge)
    status = Column(String(20), nullable=False, default="recording")
    # "recording" | "recorded" | "scored" | "score_failed"
    overall_score = Column(Float, nullable=True)   # /10
    overall_badge = Column(String(10), nullable=True)  # "good" | "ok" | "bad"
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- detailed replay (P2), all nullable for backward compat ---
    model = Column(String(80), nullable=True)         # model the spawn actually used
    provider = Column(String(40), nullable=True)      # openai|anthropic|gemini|zhipu…
    tokens_in = Column(Integer, nullable=True)        # real provider input tokens (usually NULL: spawn streams)
    tokens_out = Column(Integer, nullable=True)       # real provider output tokens
    tokens_estimated = Column(Boolean, nullable=False, default=False)  # true → task_tokens is an estimate
    error_kind = Column(String(60), nullable=True)    # structured error class/category
    error_text = Column(Text, nullable=True)          # error message (truncated by the recorder)
    system_prompt = Column(Text, nullable=True)       # SENSITIVE: assembled system prompt (retention-governed)
    injected_kb = Column(Text, nullable=True)         # SENSITIVE: injected knowledge (retention-governed)
    injected_kb_sources = Column(JSON, nullable=True)  # SENSITIVE: source labels for detail-page chips (retention-governed)

    # --- S2 evolution-real (0028) ---
    # kind distinguishes a real turn from a hermetic evolution replay arm; epoch is what
    # quarantines the old corpus (existing rows are pre-baseline epoch=0 via DEFAULT; the
    # recorder writes epoch=1 for new live runs). Replay runs never enter the win-rate.
    kind = Column(String(10), nullable=False, default="live", server_default="live")  # "live" | "replay"
    epoch = Column(Integer, nullable=False, default=0, server_default="0")  # 0 = pre-baseline; live runs = 1
    continuation = Column(Boolean, nullable=False, default=False, server_default="0")  # auto-continue (E1) round
    final_output = Column(Text, nullable=True)  # replay arm's persisted output (E3) — judge-comparable, traceable


class RunStep(Base):
    """One ordered step inside a Run (for the 'what it did' waterfall + gantt)."""

    __tablename__ = "run_steps"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    kind = Column(String(30), nullable=False)  # route|dispatch|tool_call|escalation (jargon lives ONLY here)
    ref = Column(JSON, default=dict)           # render keys: spawn_name, tool, ok, kind, need
    detail = Column(JSON, default=dict)        # progressive-disclosure: args_summary, summary, output_preview
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)


class RunEvaluation(Base):
    """One judge dimension verdict for a Run (the 'how well it did' rows)."""

    __tablename__ = "run_evaluations"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dimension = Column(String(20), nullable=False)  # routing|fabrication|identity|completion
    status = Column(String(10), nullable=False)     # pass|warn|fail
    score = Column(Float, nullable=False)           # /10
    comment = Column(Text, nullable=False, default="")


class EvolutionProposal(Base):
    """An offline-evolution candidate prompt + its gate verdict, awaiting human confirm."""

    __tablename__ = "evolution_proposals"

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_prompt = Column(Text, nullable=False)
    gate_passed = Column(Boolean, nullable=False, default=False)
    evidence = Column(JSON, default=dict)   # aggregate + per-item summary; S2 stores protected_run_ids here
    # S2 (0028) widens the allowed value set to: proposed|promoted|rejected|open|stale.
    # 'open' = a living proposal accumulating evidence; 'stale' = base prompt drifted from base_prompt_sha.
    status = Column(String(20), nullable=False, default="proposed")
    base_prompt_sha = Column(String(64), nullable=True)  # S2: sha256 of the base prompt the gate ran against
    created_at = Column(DateTime, default=datetime.utcnow)
    promoted_at = Column(DateTime, nullable=True)


class SyntheticTask(Base):
    """A versioned synthetic evaluation task for the cold-start replay corpus (S2 E6).

    source='domain' (generated from the spawn's domain profile) or 'variant' (a variant of a
    real run's task, carrying source_run_id). split_side is inherited from the source task so a
    holdout task's variant can never leak into the propose set. status supports E6's
    first-replay invalid-task exclusion."""

    __tablename__ = "synthetic_tasks"

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    task = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)          # "domain" | "variant"
    source_run_id = Column(Integer, nullable=True)       # the real run a variant derives from
    split_side = Column(String(10), nullable=False)      # "propose" | "holdout"
    status = Column(String(10), nullable=False, default="active", server_default="active")  # "active" | "invalid"
    created_at = Column(DateTime, default=datetime.utcnow)


class EvolutionAttempt(Base):
    """One background evolution attempt for a spawn (S2 E5, audit CRITICAL-4).

    Records the estimate (pre-run cost) and the actual (post-run), the outcome, the resulting
    proposal (if any), and a human-readable reason. Trigger cadence keys off the last attempt,
    not the last proposal — so a failing gate can back off deterministically."""

    __tablename__ = "evolution_attempts"

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    outcome = Column(String(20), nullable=True)  # "passed" | "failed" | "error" | "skipped_budget"
    estimate = Column(JSON, default=dict)
    actual = Column(JSON, nullable=True)
    proposal_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=False, default="", server_default="")


class Collection(Base):
    """A shared, named knowledge collection (layer A). Spawn wells stay on
    knowledge_chunks.spawn_id; shared material lives under collection_id."""

    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SpawnCollection(Base):
    """spawn ↔ collection binding (binding IS the retrieval routing)."""

    __tablename__ = "spawn_collections"
    __table_args__ = (UniqueConstraint("spawn_id", "collection_id"),)

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)


class KnowledgeChunk(Base):
    """One chunk of ingested knowledge. Exactly one of spawn_id (private well)
    / collection_id (shared collection) is set — enforced by CHECK."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("(spawn_id IS NULL) != (collection_id IS NULL)",
                        name="ck_chunk_exactly_one_scope"),
    )

    id = Column(Integer, primary_key=True)
    spawn_id = Column(Integer, ForeignKey("spawns.id", ondelete="CASCADE"), nullable=True, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True)
    source = Column(String(200), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=True)          # float32 LE bytes
    embedding_model = Column(String(80), nullable=True)     # provider model id
    created_at = Column(DateTime, default=datetime.utcnow)


class PersonaSeed(Base):
    """A seed persona definition (e.g. from agency-agents) used to bootstrap spawns."""

    __tablename__ = "persona_seeds"

    id = Column(Integer, primary_key=True)
    slug = Column(String(120), nullable=False, unique=True)
    division = Column(String(80), nullable=True)
    name = Column(String(160), nullable=True)
    identity = Column(Text, nullable=True)
    mission = Column(Text, nullable=True)
    rules = Column(Text, nullable=True)
    deliverables = Column(Text, nullable=True)
    workflow = Column(Text, nullable=True)
    success_metrics = Column(Text, nullable=True)
    raw = Column(Text, nullable=False)
    source = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationEvent(Base):
    """A growth/learning event during a conversation (distill, memory, skill, evolution,
    invite) for the in-rail recap timeline. Runs live in `runs` and are merged at read time,
    NOT duplicated here."""

    __tablename__ = "conversation_events"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    ref = Column(JSON, nullable=True)
    summary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Learning(Base):
    """心得 (know-how) distilled from concrete signals (a distill event, a user
    correction, or a repeated run pattern). Always carries a traceable source_ref."""

    __tablename__ = "learnings"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    label = Column(String(60), nullable=True)
    source_kind = Column(String(20), nullable=False)   # distill|feedback|run_pattern
    source_ref = Column(JSON, nullable=False)
    spawn_id = Column(Integer, nullable=True, index=True)
    confidence = Column(Float, default=0.6)
    created_at = Column(DateTime, default=datetime.utcnow)


class Note(Base):
    """A hand-written markdown note — the human-authored Second-Brain type. Linked
    to other entries via [[wiki links]] parsed at read time (no link table)."""

    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrainUsage(Base):
    """Unified cross-cutting usage for the Second Brain: one row per used entity
    (material/learning/profile), incremented when retrieval injects it."""

    __tablename__ = "brain_usage"
    __table_args__ = (UniqueConstraint("kind", "ref_key", name="ux_brain_usage_kind_ref"),)

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)          # material|learning|profile
    ref_key = Column(String(300), nullable=False)
    usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    last_used_ref = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
