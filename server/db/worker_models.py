"""Versioned professional methods and task-local ephemeral worker records."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from server.db.base import Base


class ProfessionalMethod(Base):
    __tablename__ = "professional_methods"
    key = Column(String(40), primary_key=True)
    current_revision = Column(Integer, nullable=False, default=1)


class ProfessionalMethodVersion(Base):
    __tablename__ = "professional_method_versions"
    key = Column(String(40), ForeignKey("professional_methods.key"), primary_key=True)
    revision = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    instructions = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TaskWorker(Base):
    __tablename__ = "task_workers"
    __table_args__ = (
        UniqueConstraint("task_id", "spec_revision", "fingerprint", "attempt_id", name="uq_task_worker_request"),
        CheckConstraint("status IN ('queued','running','completed','partial','failed','cancelled','interrupted')",
                        name="ck_task_worker_status"),
    )
    id = Column(String(36), primary_key=True)
    task_id = Column(String(200), ForeignKey("companion_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(String(36), ForeignKey("task_attempts.id"), nullable=False)
    spec_revision = Column(Integer, nullable=False)
    method_key = Column(String(40), nullable=False)
    method_revision = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    brief = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    result = Column(JSON, nullable=True)
    progress = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
