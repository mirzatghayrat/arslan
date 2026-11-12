"""Versioned professional methods. (The helpers' task_workers table has no model since v0.1.64 SUB6:
migration 0052 creates it from its own definition, and SUB7 drops it.)"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from server.db.base import Base


# DELETE-BY: v0.1.65, when professional methods have folded into skills under SUB
# (CAP3b, docs/plans/0164/CAP-capabilities.md). Both models below.
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
