"""Durable goals and attempts; execution authority is never encoded in text."""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String,
    UniqueConstraint, text,
)

from server.db.base import Base


class CompanionTask(Base):
    __tablename__ = "companion_tasks"
    __table_args__ = (
        CheckConstraint("version > 0 AND spec_revision > 0 AND sequence >= 0", name="ck_task_versions"),
        CheckConstraint("phase IN ('queued','running','waiting_user','verifying','succeeded','failed','cancelled')",
                        name="ck_task_phase"),
        Index("uq_companion_active_conversation", "owner_id", "conversation_id", unique=True,
              sqlite_where=text("phase IN ('running','verifying')")),
    )
    id = Column(String(200), primary_key=True)
    owner_id = Column(String(100), nullable=False, default="local", index=True)
    conversation_id = Column(String(100), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    project_version = Column(Integer, nullable=True)
    spec_revision = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    sequence = Column(Integer, nullable=False, default=0)
    phase = Column(String(20), nullable=False, default="queued", index=True)
    attempt_id = Column(String(200), nullable=False)
    checkpoint_id = Column(String(36), nullable=True)
    budget = Column(JSON, nullable=False)
    privacy = Column(JSON, nullable=False, default=dict)
    results = Column(JSON, nullable=False, default=list)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    pause_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TaskRevision(Base):
    __tablename__ = "task_revisions"
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), primary_key=True)
    revision = Column(Integer, primary_key=True)
    spec = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TaskAttempt(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (UniqueConstraint("task_id", "number", name="uq_task_attempt_number"),)
    id = Column(String(36), primary_key=True)
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    spec_revision = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="running")
    run_ids = Column(JSON, nullable=False, default=list)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)


class TaskCheckpoint(Base):
    __tablename__ = "task_checkpoints"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_task_checkpoint_sequence"),)
    id = Column(String(36), primary_key=True)
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(String(36), ForeignKey("task_attempts.id"), nullable=False)
    spec_revision = Column(Integer, nullable=False)
    sequence = Column(Integer, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TaskEvent(Base):
    __tablename__ = "task_events"
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), primary_key=True)
    sequence = Column(Integer, primary_key=True)
    attempt_id = Column(String(200), nullable=False)
    kind = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TaskAction(Base):
    __tablename__ = "task_actions"
    __table_args__ = (
        UniqueConstraint("task_id", "spec_revision", "intent_hash", name="uq_task_action_intent"),
        CheckConstraint("status IN ('prepared','in_flight','succeeded','failed','uncertain','denied','not_applied')",
                        name="ck_task_action_status"),
        CheckConstraint("effect IN ('read','local_write','external_write','destructive')", name="ck_task_action_effect"),
    )
    id = Column(String(36), primary_key=True)
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(String(36), ForeignKey("task_attempts.id"), nullable=False)
    spec_revision = Column(Integer, nullable=False)
    tool_key = Column(String(200), nullable=False)
    intent_hash = Column(String(64), nullable=False)
    effect = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="prepared")
    version = Column(Integer, nullable=False, default=1)
    evidence = Column(JSON, nullable=False, default=list)
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
