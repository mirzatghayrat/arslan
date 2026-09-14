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
    receipt = Column(JSON, nullable=False)  # IDs, revisions, reason codes and token estimate only.
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
