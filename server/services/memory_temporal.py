"""Supersede and undo on the v1 memory tables (user_facts, learnings): what is left of them.

Every boot activates memory v2, where an entry is replaced or restored only through versioned memory review.
So both entry points keep their checks on the caller (provenance is mandatory, a programmer guard) and then
refuse with `versioned_review_required`. 0.1.63 C2a-2 removed the v1 pointer rewrite (single-pointer write,
guards, bounded cycle walk), which no boot reached. The v1 tables themselves go with the v0.1.64 migration
(C7's third step); this module goes with them.
"""
from __future__ import annotations


class SupersedeError(ValueError):
    """结构化拒绝:reason 供 API 层转 4xx,不落 500。"""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


async def execute_supersede(
    table: str, new_id: int, old_id: int, *, provenance: dict, db=None
) -> None:
    if not provenance:
        raise SupersedeError("missing_provenance", "provenance is mandatory (programmer guard)")
    raise SupersedeError("versioned_review_required", "Use versioned memory review to replace an entry")


async def undo_supersede(table: str, old_id: int, *, provenance: dict, db=None) -> None:
    if not provenance:
        raise SupersedeError("missing_provenance", "provenance is mandatory (programmer guard)")
    raise SupersedeError("versioned_review_required", "Use versioned memory review to restore an entry")
