"""Companion persistence, registered through server.db.models.

Legacy personal-memory tables remain recovery inputs until the unified service
switch is verified. These tables never contain connection credential values.
"""
from datetime import datetime

from sqlalchemy import (
    JSON, CheckConstraint, Column, DateTime, Float, ForeignKey, ForeignKeyConstraint,
    Boolean, Integer, String, Text, UniqueConstraint,
)

from server.db.base import Base


class ConversationContext(Base):
    __tablename__ = "conversation_contexts"
    __table_args__ = (CheckConstraint("version > 0", name="ck_conversation_context_version"),)
    id = Column(String(100), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local")
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    no_memory = Column(Boolean, nullable=False, default=False)
    no_learning = Column(Boolean, nullable=False, default=False)
    temporary = Column(Boolean, nullable=False, default=False)
    cloud_memory_allowed = Column(Boolean, nullable=False, default=False)
    allow_sensitive = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ContextReceiptRecord(Base):
    __tablename__ = "context_receipts"
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local")
    conversation_id = Column(String(100), nullable=False, index=True)
    task_id = Column(String(100), nullable=False, index=True)
    run_id = Column(String(100), nullable=False, index=True)
    receipt = Column(JSON, nullable=False)  # IDs/revisions, reason codes, estimates and request counters; no bodies.
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_project_version"),
        CheckConstraint("status IN ('active','archived')", name="ck_project_status"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local")
    name = Column(String(200), nullable=False)
    kind = Column(String(30), nullable=False, default="general")
    summary = Column(Text, nullable=False, default="")
    workspace_ref = Column(String(200), nullable=True)
    collection_ids = Column(JSON, nullable=False, default=list)
    app_binding = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # 0.1.56 projects in two layers. Nullable, so migration 0063 only adds columns; NONE of
    # these writes bump `version` (a version bump fails every task pinned to the project).
    template = Column(String(30), nullable=True)
    finish_line = Column(Text, nullable=True)
    stage = Column(String(20), nullable=True)            # idea | active | done | dropped (NULL = idea)
    paused = Column(Boolean, nullable=True)
    done_at = Column(DateTime, nullable=True)
    plan_version = Column(Integer, nullable=True)        # the plan's own optimistic version


class ProjectLevel(Base):
    """One level of a project's plan (0.1.56). Its band says which board column it counts for."""
    __tablename__ = "project_levels"
    __table_args__ = (
        CheckConstraint("band IN ('shaping','doing','done')", name="ck_project_level_band"),
        CheckConstraint("state IN ('todo','current','cleared')", name="ck_project_level_state"),
    )
    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(String(300), nullable=False, default="")
    band = Column(String(10), nullable=False)
    clear_condition = Column(String(400), nullable=False, default="")
    state = Column(String(10), nullable=False, default="todo")
    habit = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime, nullable=True)
    cleared_at = Column(DateTime, nullable=True)


class ProjectCheckpoint(Base):
    """A checkpoint inside a level; `expects` says what evidence ticks it by itself."""
    __tablename__ = "project_checkpoints"
    __table_args__ = (
        CheckConstraint("state IN ('todo','done')", name="ck_project_checkpoint_state"),
    )
    id = Column(String(36), primary_key=True)
    level_id = Column(String(36), ForeignKey("project_levels.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    text = Column(String(200), nullable=False)
    expects = Column(JSON, nullable=True)
    state = Column(String(10), nullable=False, default="todo")
    progress = Column(String(40), nullable=True)
    evidence = Column(JSON, nullable=True)
    done_at = Column(DateTime, nullable=True)
    done_by = Column(String(10), nullable=True)          # user | arslan


class ProjectEvent(Base):
    """What happened to a project's plan: ticks, proposals and their outcome, advances,
    plan changes, stage changes. Arslan's own entries are what "Arslan 最近做的" lists and
    what Undo reverses; proposal outcomes are the shadow-mode record."""
    __tablename__ = "project_events"
    __table_args__ = (
        CheckConstraint("kind IN ('tick','untick','proposal','advance','plan_change','plan_proposal','stage','auto_ask','activity')",
                        name="ck_project_event_kind"),
        CheckConstraint("actor IN ('user','arslan')", name="ck_project_event_actor"),
    )
    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    actor = Column(String(10), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    outcome = Column(String(10), nullable=True)          # proposals: accepted|declined|undone|stale; others: undone
    undo_of = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ProjectHabit(Base):
    """How the user advances projects (0.1.56 §6): plan rules Arslan learned, and pace overrides."""
    __tablename__ = "project_habits"
    __table_args__ = (
        CheckConstraint("kind IN ('plan_rule','pace_override')", name="ck_project_habit_kind"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local")
    template = Column(String(30), nullable=True)
    kind = Column(String(20), nullable=False)
    text = Column(String(300), nullable=False)
    value = Column(JSON, nullable=True)
    sources = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('preference','project_fact','style_rule','experience')", name="ck_memory_kind"),
        CheckConstraint("scope_kind IN ('global','project','domain','expert','task')", name="ck_memory_scope"),
        CheckConstraint("(scope_kind = 'global' AND scope_id IS NULL) OR "
                        "(scope_kind != 'global' AND scope_id IS NOT NULL)", name="ck_memory_scope_id"),
        CheckConstraint("status IN ('proposed','active','paused','superseded','expired','deleted','quarantined')",
                        name="ck_memory_status"),
        CheckConstraint("sensitivity IN ('normal','sensitive','unknown','secret')", name="ck_memory_sensitivity"),
        CheckConstraint("use_policy IN ('local_only','cloud_allowed','never')", name="ck_memory_use"),
        CheckConstraint("version > 0", name="ck_memory_version"),
        ForeignKeyConstraint(
            ["id", "current_revision_id"], ["memory_revisions.entry_id", "memory_revisions.id"],
            name="fk_memory_current_revision", deferrable=True, initially="DEFERRED",
        ),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local", index=True)
    kind = Column(String(30), nullable=False)
    scope_kind = Column(String(20), nullable=False, index=True)
    scope_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, index=True)
    current_revision_id = Column(String(36), nullable=False)
    normalized_hash = Column(String(64), nullable=True, index=True)
    dedup_key = Column(String(64), nullable=True, unique=True)
    version = Column(Integer, nullable=False, default=1)
    sensitivity = Column(String(20), nullable=False, default="unknown")
    use_policy = Column(String(20), nullable=False, default="local_only")
    confidence = Column(Float, nullable=True)
    confirmation_kind = Column(String(30), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    valid_from = Column(DateTime, nullable=True)
    review_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    superseded_by = Column(String(36), ForeignKey("memory_entries.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryRevision(Base):
    __tablename__ = "memory_revisions"
    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_memory_revision_version"),
        UniqueConstraint("entry_id", "id", name="uq_memory_revision_identity"),
        CheckConstraint("version > 0", name="ck_memory_revision_version"),
    )
    id = Column(String(36), primary_key=True)
    entry_id = Column(String(36), ForeignKey("memory_entries.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=True)  # NULL only for erased/restricted revisions.
    structured_value = Column(JSON, nullable=True)
    previous_version = Column(Integer, nullable=True)
    change_reason = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemorySource(Base):
    __tablename__ = "memory_sources"
    __table_args__ = (
        ForeignKeyConstraint(["entry_id", "revision_id"],
                             ["memory_revisions.entry_id", "memory_revisions.id"]),
    )
    id = Column(String(36), primary_key=True)
    entry_id = Column(String(36), nullable=False, index=True)
    revision_id = Column(String(36), nullable=False)
    source_kind = Column(String(30), nullable=False)
    source_ref = Column(JSON, nullable=False)
    locator = Column(String(500), nullable=True)
    author = Column(String(30), nullable=False, default="unknown")
    observed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryLegacyMap(Base):
    __tablename__ = "memory_legacy_map"
    source_table = Column(String(30), primary_key=True)
    source_key = Column(String(100), primary_key=True)
    entry_id = Column(String(36), ForeignKey("memory_entries.id"), nullable=False, unique=True)
    source_sha256 = Column(String(64), nullable=False)
    migration_note = Column(String(100), nullable=False, default="")


class MemoryStoreState(Base):
    __tablename__ = "memory_store_state"
    id = Column(Integer, primary_key=True)
    instance_id = Column(String(36), nullable=False, unique=True)
    phase = Column(String(20), nullable=False, default="prepared")
    deletion_epoch = Column(Integer, nullable=False, default=0)
    digest_key = Column(String(64), nullable=False)  # Local tombstone HMAC key; never context.
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryDeletion(Base):
    __tablename__ = "memory_deletions"
    __table_args__ = (UniqueConstraint("instance_id", "content_digest", "scope_kind", "scope_key"),)
    id = Column(String(36), primary_key=True)
    instance_id = Column(String(36), nullable=False)
    entry_id = Column(String(36), nullable=False)
    epoch = Column(Integer, nullable=False)
    content_digest = Column(String(64), nullable=False)
    scope_kind = Column(String(20), nullable=False)
    scope_key = Column(String(100), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemoryMigrationReport(Base):
    __tablename__ = "memory_migration_reports"
    id = Column(Integer, primary_key=True)
    source_version = Column(String(20), nullable=False)
    summary = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemorySuppression(Base):
    """Deleted source may remain in history but must not seed memory again."""
    __tablename__ = "memory_suppressions"
    source_kind = Column(String(30), primary_key=True)
    source_id = Column(String(100), primary_key=True)
    entry_id = Column(String(36), primary_key=True)
    cutoff_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
