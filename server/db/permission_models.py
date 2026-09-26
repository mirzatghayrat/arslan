"""Credential-free connection metadata and single-action approval fences."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, CheckConstraint

from server.db.base import Base


class CompanionConnection(Base):
    __tablename__ = "companion_connections"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_connection_version"),
        CheckConstraint("status IN ('disconnected','connected','needs_attention')", name="ck_connection_status"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    # Broker-generated opaque identity, NEVER a key, file path or URL.
    credential_ref = Column(String(36), nullable=False)
    status = Column(String(30), nullable=False, default="disconnected")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ActionGrantRecord(Base):
    __tablename__ = "action_grants"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="ck_action_grant_window"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(100), nullable=False, index=True)
    connection_id = Column(String(36), ForeignKey("companion_connections.id"), nullable=False)
    connection_version = Column(Integer, nullable=False)
    task_id = Column(String(200), ForeignKey("companion_tasks.id"), nullable=False, index=True)
    attempt_id = Column(String(36), ForeignKey("task_attempts.id"), nullable=False)
    spec_revision = Column(Integer, nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    project_version = Column(Integer, nullable=False)
    target_hash = Column(String(64), nullable=False)
    action_id = Column(String(36), ForeignKey("task_actions.id"), nullable=False)
    action_version = Column(Integer, nullable=False)
    action = Column(String(200), nullable=False)
    diff_hash = Column(String(64), nullable=False)
    confirmation_ref = Column(String(36), nullable=False, unique=True)
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
