"""One transactional repository for v2 personal memory.

Methods stage changes in the supplied session. API/task boundaries commit once;
they must roll back on errors. No LLM, embedding service, or network is used here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError

from arslan.companion.content_policy import normalized_memory
from arslan.companion.design import reference_data
from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite, decide_write, naive_utc
from server.db import session as db_session
from server.db.models import (
    ArslanSummary, MemoryDeletion, MemoryEntry, MemoryLegacyMap, MemoryProposal,
    MemoryRevision, MemorySource, MemoryStoreState, MemorySuppression, Project, Run,
)


def _id() -> str:
    return str(uuid.uuid4())


def _iso(value):
    return value.isoformat() + "Z" if value else None


def _structured(write: MemoryWrite) -> dict:
    value = {"topic": write.topic, "style_reference": reference_data(write.style_reference)}
    if write.core:
        value["core"] = write.core
    return value


async def is_active(db=None) -> bool:
    if db is None:
        async with db_session.AsyncSessionLocal() as own:
            return await is_active(own)
    return await db.scalar(select(MemoryStoreState.phase).where(MemoryStoreState.id == 1)) == "active"


_SENSITIVITY = ("normal", "unknown", "sensitive", "secret")
_USE = ("cloud_allowed", "local_only", "never")


def _stricter(order: tuple[str, ...], kept: str | None, new: str) -> str:
    """The stricter of an entry's value and a new one; a value outside `order` counts as the strictest."""
    rank = {value: i for i, value in enumerate(order)}
    return kept if rank.get(kept, len(order)) > rank.get(new, len(order)) else new


@asynccontextmanager
async def repository():
    async with db_session.AsyncSessionLocal() as db:
        repo = MemoryRepository(db)
        try:
            yield repo
            await db.commit()
        except OperationalError as exc:
            await db.rollback()
            # Concurrent SQLite read→write upgrades may lose their snapshot even
            # with a busy timeout. Never leak SQL or silently overwrite/retry a CAS.
            if any(code in str(exc.orig).lower() for code in ("locked", "busy")):
                raise MemoryError("memory_version_conflict") from exc
            raise
        except BaseException:
            await db.rollback()
            raise
        if repo.deletions_changed:
            from server.services.memory_deletion_ledger import sync
            await sync(db)


class MemoryRepository:
    def __init__(self, db):
        self.db = db
        self.deletions_changed = False

    async def state(self) -> MemoryStoreState:
        state = await self.db.get(MemoryStoreState, 1)
        if state is None:
            state = MemoryStoreState(id=1, instance_id=_id(), phase="prepared",
                                     deletion_epoch=0, digest_key=secrets.token_hex(32))
            self.db.add(state)
            await self.db.flush()
        return state

    async def digest(self, content: str) -> str:
        state = await self.state()
        return hmac.new(bytes.fromhex(state.digest_key), normalized_memory(content).encode(),
                        hashlib.sha256).hexdigest()

    async def compatibility_id(self, entry, table: str | None = None) -> int | None:
        mapping = await self.db.scalar(select(MemoryLegacyMap).where(MemoryLegacyMap.entry_id == entry.id))
        if mapping:
            return int(mapping.source_key) if mapping.source_table in {"user_facts", "learnings"} else None
        table = table or ("learnings" if entry.kind == "experience" else "user_facts")
        maximum = await self.db.scalar(text(
            "SELECT COALESCE(MAX(CAST(source_key AS INTEGER)),0) FROM memory_legacy_map WHERE source_table=:t"),
            {"t": table})
        alias = int(maximum) + 1
        self.db.add(MemoryLegacyMap(
            source_table=table, source_key=str(alias), entry_id=entry.id,
            source_sha256=hashlib.sha256(entry.id.encode()).hexdigest(), migration_note="v2_alias",
        ))
        await self.db.flush()
        return alias

    async def by_compatibility_id(self, table: str, alias: int):
        mapping = await self.db.get(MemoryLegacyMap, (table, str(alias)))
        if mapping is None:
            raise MemoryError("memory_not_found")
        return await self.get(mapping.entry_id)

    async def _sync_index(self, entry_id: str):
        # A schema-only test/prepare database may not have FTS; production activation does.
        exists = await self.db.scalar(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_entries_fts'"))
        if not exists:
            return
        await self.db.execute(text("DELETE FROM memory_entries_fts WHERE entry_id=:id"), {"id": entry_id})
        await self.db.execute(text("""
            INSERT INTO memory_entries_fts(entry_id,content)
            SELECT e.id,r.content FROM memory_entries e JOIN memory_revisions r ON r.id=e.current_revision_id
            WHERE e.id=:id AND e.status!='deleted' AND e.sensitivity!='secret' AND r.content IS NOT NULL
        """), {"id": entry_id})

    async def _scope_exists(self, scope: MemoryScope, actor: MemoryActor):
        if scope.kind == "project":
            project = await self.db.get(Project, scope.id)
            if project is None or project.owner_id != actor.owner_id or project.status != "active":
                raise MemoryError("project_not_available")

    async def get(self, entry_id: str, *, owner_id: str = "local") -> MemoryEntry:
        entry = await self.db.get(MemoryEntry, entry_id)
        if entry is None or entry.owner_id != owner_id:
            raise MemoryError("memory_not_found")
        return entry

    async def _source(self, entry, revision_id, actor: MemoryActor, decision=None):
        ref = {key: value for key, value in {
            "task_id": actor.task_id, "project_id": actor.project_id,
            "expert_id": actor.expert_id, "message_id": actor.source_message_id,
            "run_id": actor.source_run_id, "explicit_save_ref": actor.explicit_save_ref,
            "conversation_id": actor.conversation_id,
        }.items() if value is not None}
        # #475 recheck, J1: the user's own words only when this write is the save the user asked for, word for word
        # (decide_write's explicit_user_request); any other write in that turn stays Arslan's. The decision is
        # passed in because `entry` is stale inside revise.
        source_kind = "manual" if actor.origin == "user" else (
            "user_message" if decision is not None and decision.confirmation_kind == "explicit_user_request"
            else actor.origin)
        self.db.add(MemorySource(
            id=_id(), entry_id=entry.id, revision_id=revision_id, source_kind=source_kind,
            source_ref=ref, author="user" if source_kind in {"manual", "user_message"} else actor.origin,
            observed_at=datetime.utcnow(),
        ))

    async def _not_suppressed(self, write: MemoryWrite, actor: MemoryActor):
        digest = await self.digest(write.content)
        suppressed = await self.db.scalar(select(MemoryDeletion.id).where(
            MemoryDeletion.content_digest == digest,
            MemoryDeletion.scope_kind == write.scope.kind,
            MemoryDeletion.scope_key == (write.scope.id or ""),
        ).limit(1))
        if suppressed:
            raise MemoryError("memory_previously_deleted")
        if actor.origin != "user":
            source_tests = []
            for kind, value in (("message_id", actor.source_message_id), ("task_id", actor.task_id),
                                ("run_id", actor.source_run_id), ("conversation_id", actor.conversation_id)):
                if value is not None:
                    source_tests.append((MemorySuppression.source_kind == kind)
                                        & (MemorySuppression.source_id == str(value)))
            if source_tests and await self.db.scalar(select(MemorySuppression.entry_id).where(
                or_(*source_tests)).limit(1)):
                raise MemoryError("memory_source_deleted")
        return digest

    @staticmethod
    def _dedup_key(write: MemoryWrite, owner_id: str, digest: str) -> str:
        return hashlib.sha256(json.dumps([owner_id, write.kind, write.scope.kind,
                                         write.scope.id, digest]).encode()).hexdigest()

    async def create(self, write: MemoryWrite, actor: MemoryActor) -> dict:
        decision = decide_write(write, actor)
        await self._scope_exists(write.scope, actor)
        digest = await self._not_suppressed(write, actor)
        duplicate = await self.db.scalar(select(MemoryEntry).where(
            MemoryEntry.owner_id == actor.owner_id, MemoryEntry.kind == write.kind,
            MemoryEntry.scope_kind == write.scope.kind, MemoryEntry.scope_id == write.scope.id,
            MemoryEntry.normalized_hash == digest, MemoryEntry.status != "deleted",
        ).order_by(MemoryEntry.created_at).limit(1))
        if duplicate is not None:
            if write.style_reference:
                previous = await self.db.get(MemoryRevision, duplicate.current_revision_id)
                if (previous.structured_value or {}).get("style_reference") != reference_data(write.style_reference):
                    raise MemoryError("style_reference_conflict")
            previous = await self.db.get(MemoryRevision, duplicate.current_revision_id)
            core_changed = "core" in write.model_fields_set and (previous.structured_value or {}).get("core") != write.core
            # #475 review, F3: the same words again are never a way round the user's answer or a wait. A paused
            # entry (the user said no) comes back only with the user's own confirmation, and "about you" taking
            # effect directly (INB2) is for a new entry only: a waiting one keeps waiting for its own proposal.
            user_confirmed = decision.confirmation_kind in ("user_form", "explicit_user_request")
            if (duplicate.status == "paused" and not user_confirmed) or (
                    decision.confirmation_kind == "arslan_about_you" and duplicate.status != "active"):
                return await self.present(duplicate, deduplicated=True)
            if (decision.status == "active" and duplicate.status != "active") or core_changed:
                return await self.revise(duplicate.id, duplicate.version, write, actor)
            return await self.present(duplicate, deduplicated=True)
        status = decision.status
        if write.topic and status == "active":
            # Same-scope conflicts never silently replace an existing confirmed rule.
            candidates = (await self.db.execute(select(MemoryEntry, MemoryRevision).join(
                MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id,
            ).where(MemoryEntry.owner_id == actor.owner_id, MemoryEntry.scope_kind == write.scope.kind,
                    MemoryEntry.scope_id == write.scope.id, MemoryEntry.status == "active"))).all()
            if any((revision.structured_value or {}).get("topic") == write.topic for _, revision in candidates):
                status = "proposed"
        entry_id, revision_id = _id(), _id()
        now = datetime.utcnow()
        entry = MemoryEntry(
            id=entry_id, owner_id=actor.owner_id, kind=write.kind,
            scope_kind=write.scope.kind, scope_id=write.scope.id, status=status,
            current_revision_id=revision_id, version=1, normalized_hash=digest,
            dedup_key=self._dedup_key(write, actor.owner_id, digest),
            sensitivity=decision.sensitivity, use_policy=decision.use_policy,
            confirmation_kind=decision.confirmation_kind if status == "active" else None,
            confirmed_at=now if status == "active" else None,
            valid_from=naive_utc(write.valid_from), review_at=naive_utc(write.review_at),
            expires_at=naive_utc(write.expires_at), created_at=now, updated_at=now,
        )
        self.db.add(entry)
        await self.db.flush()
        self.db.add(MemoryRevision(
            id=revision_id, entry_id=entry_id, version=1, content=write.content.strip(),
            structured_value=_structured(write), previous_version=None, change_reason="created",
        ))
        await self.db.flush()
        await self._source(entry, revision_id, actor, decision)
        proposal_id, reason = None, None
        if status == "proposed":
            # INB2: why it waits (decision.reason; a topic clash with a confirmed rule is still "confirmation_required").
            reason = decision.reason if decision.status == "proposed" and decision.reason else "confirmation_required"
            proposal_id = await self._proposal(entry, actor, candidate=None, reason=reason)
        await self.db.flush()
        await self.compatibility_id(entry)
        await self._sync_index(entry.id)
        return await self.present(entry, **({"proposal_id": proposal_id, "reason": reason} if proposal_id else {}))

    async def _proposal(self, entry, actor, candidate, reason: str = "confirmation_required"):
        proposal = MemoryProposal(
            kind="memory_v2", table_name="memory_entries", old_id=None, new_id=None,
            target_entry_id=entry.id, target_version=entry.version, candidate=candidate,
            reason=reason, status="pending",
            provenance={"source_kind": actor.origin, "task_id": actor.task_id},
            conversation_id=actor.task_id,
        )
        self.db.add(proposal)
        await self.db.flush()
        return proposal.id

    async def merge_into(self, entry_id: str, expected_version: int, write: MemoryWrite, actor: MemoryActor) -> dict | None:
        """MEM1: `write` says the same as this entry (memory_merge.same_meaning). None when the entry moved on
        since (another version, deleted): the caller stores the write as a new entry. Otherwise the entry stays:
        - paused (the user said no): nothing changes, as the same words again (#475 F3);
        - active, and the write would wait (INB2: not present, a conversation off the list, sensitive): the
          active entry is not touched; the write waits as a proposal against it, or joins the one already
          pending (②Main's review: refreshing an active entry is a write that takes effect);
        - otherwise (active and the write may take effect, or a proposal waiting anyway): the date is refreshed,
          the stricter sensitivity and narrower use are kept, and the write's source is added to the current
          revision, so a turn off the list stays traceable (#475 H1, as J2 for lessons). The words stay."""
        if actor.origin == "user":
            raise MemoryError("invalid_memory_actor")         # the user's own words are never folded away
        entry = await self.db.get(MemoryEntry, entry_id)
        if (entry is None or entry.owner_id != actor.owner_id or entry.version != expected_version
                or entry.status not in ("active", "proposed", "paused")):
            return None
        decision = decide_write(write, actor)
        await self._not_suppressed(write, actor)
        if entry.status == "paused":
            return await self.present(entry, deduplicated=True)
        pending = None
        if entry.status == "active" and decision.status != "active":
            pending = await self.db.scalar(select(MemoryProposal).where(
                MemoryProposal.target_entry_id == entry.id, MemoryProposal.status == "pending").limit(1))
            proposal_id = pending.id if pending is not None else await self._proposal(
                entry, actor, write.model_dump(mode="json"), reason=decision.reason or "confirmation_required")
            return {"proposal_id": proposal_id, "status": "proposed", "target_id": entry.id,
                    "target_version": entry.version, "merged": True,
                    "reason": pending.reason if pending is not None else decision.reason}
        entry.sensitivity = _stricter(_SENSITIVITY, entry.sensitivity, decision.sensitivity)
        entry.use_policy = _stricter(_USE, entry.use_policy, decision.use_policy)
        entry.updated_at = datetime.utcnow()
        await self._source(entry, entry.current_revision_id, actor, decision)
        await self.db.flush()
        await self._sync_index(entry.id)
        return await self.present(entry, merged=True)

    async def revise(self, entry_id: str, expected_version: int, write: MemoryWrite,
                     actor: MemoryActor, *, confirm_scope_change: bool = False) -> dict:
        entry = await self.get(entry_id, owner_id=actor.owner_id)
        if entry.status == "deleted":
            raise MemoryError("memory_deleted")
        if entry.version != expected_version:
            raise MemoryError("memory_version_conflict")
        previous = await self.db.get(MemoryRevision, entry.current_revision_id)
        reference = (previous.structured_value or {}).get("style_reference")
        if "style_reference" not in write.model_fields_set:
            if reference:
                if write.kind != "style_rule" or write.scope.kind != "project":
                    raise MemoryError("style_reference_project_required")
                write = MemoryWrite.model_validate({**write.model_dump(), "style_reference": reference})
        if "core" not in write.model_fields_set and (previous.structured_value or {}).get("core"):
            try:
                write = MemoryWrite.model_validate({**write.model_dump(exclude_unset=True),
                                                    "core": previous.structured_value["core"]})
            except ValueError:
                pass  # a kind or scope change leaves the always-in-view set
        if actor.origin != "user":
            # #475 review, F3: "about you" taking effect directly is for a new entry (INB2), never an edit.
            actor = replace(actor, user_present=False, conversation_clean=False)
            # #475 recheck, G1: the write carries the entry's stricter sensitivity (as the edit paths spell it:
            # secret → unknown), so a proposal made here asks about what the entry already is, and the user's yes
            # keeps it so. Use needs no fold: Arslan's writes never ask for cloud use, and the update below keeps
            # the narrower use when an automatic path takes the entry into effect.
            write = MemoryWrite.model_validate({**write.model_dump(), "sensitivity": _stricter(
                _SENSITIVITY, {"secret": "unknown"}.get(entry.sensitivity, entry.sensitivity), write.sensitivity)})
        decision = decide_write(write, actor)
        await self._scope_exists(write.scope, actor)
        digest = await self._not_suppressed(write, actor)
        scope_changed = (entry.scope_kind, entry.scope_id) != (write.scope.kind, write.scope.id)
        if scope_changed and not (actor.origin == "user" and confirm_scope_change):
            raise MemoryError("memory_scope_confirmation_required")
        if decision.status != "active" or (actor.origin != "user" and reference != reference_data(write.style_reference)):
            proposal_id = await self._proposal(entry, actor, write.model_dump(mode="json"))
            return {"proposal_id": proposal_id, "status": "proposed", "target_id": entry.id,
                    "target_version": entry.version}
        revision_id = _id()
        version = expected_version + 1
        now = datetime.utcnow()
        result = await self.db.execute(update(MemoryEntry).where(
            MemoryEntry.id == entry_id, MemoryEntry.version == expected_version,
            MemoryEntry.status != "deleted",
        ).values(
            current_revision_id=revision_id, version=version, kind=write.kind,
            normalized_hash=digest, dedup_key=self._dedup_key(write, actor.owner_id, digest),
            scope_kind=write.scope.kind, scope_id=write.scope.id,
            # #475 review, F3: only the user widens an entry's use (the automatic paths set it from the setting,
            # whatever the write says); its sensitivity already came in with the write (G1).
            sensitivity=decision.sensitivity,
            use_policy=decision.use_policy if actor.origin == "user" else _stricter(
                _USE, entry.use_policy, decision.use_policy),
            status="active", superseded_by=None, confirmation_kind=decision.confirmation_kind, confirmed_at=now,
            valid_from=naive_utc(write.valid_from), review_at=naive_utc(write.review_at),
            expires_at=naive_utc(write.expires_at), updated_at=now,
        ).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise MemoryError("memory_version_conflict")
        self.db.add(MemoryRevision(
            id=revision_id, entry_id=entry_id, version=version, content=write.content.strip(),
            structured_value=_structured(write), previous_version=expected_version, change_reason="user_confirmed",
        ))
        await self.db.flush()
        await self._source(entry, revision_id, actor, decision)
        await self.db.refresh(entry)
        await self._sync_index(entry.id)
        return await self.present(entry)

    async def resolve_proposal(self, proposal_id: int, *, accept: bool, actor: MemoryActor,
                               sensitive_acknowledged: bool = False,
                               use_policy: str = "local_only", expected_version: int | None = None) -> dict:
        if actor.origin != "user":
            raise MemoryError("user_confirmation_required")
        proposal = await self.db.get(MemoryProposal, proposal_id)
        if proposal is None or proposal.kind != "memory_v2":
            raise MemoryError("proposal_not_found")
        if proposal.status != "pending":
            raise MemoryError("proposal_already_resolved")
        entry = await self.get(proposal.target_entry_id, owner_id=actor.owner_id)
        # The chat line names the version it showed (INB2, #475 review): its "No" for an entry that changed
        # since is refused too, so the line never says "not remembered" about one that took effect.
        if expected_version is not None and entry.version != expected_version:
            raise MemoryError("memory_version_conflict")
        if accept and entry.version != proposal.target_version:       # in addition, never instead (#475 recheck, G3)
            raise MemoryError("memory_version_conflict")
        if entry.status == "deleted":
            raise MemoryError("memory_deleted")
        if accept:
            if proposal.candidate:
                data = dict(proposal.candidate)
            else:
                revision = await self.db.get(MemoryRevision, entry.current_revision_id)
                data = {"content": revision.content or "", "kind": entry.kind,
                        "scope": {"kind": entry.scope_kind, "id": entry.scope_id},
                        "sensitivity": entry.sensitivity if entry.sensitivity != "secret" else "unknown",
                        "topic": (revision.structured_value or {}).get("topic"),
                        "style_reference": (revision.structured_value or {}).get("style_reference"),
                        "core": (revision.structured_value or {}).get("core"),
                        "valid_from": _iso(entry.valid_from), "review_at": _iso(entry.review_at),
                        "expires_at": _iso(entry.expires_at)}
            data.update(sensitive_acknowledged=sensitive_acknowledged, use_policy=use_policy)
            if data.get("style_reference"):
                data["style_reference"] = {**data["style_reference"], "interpretation": "confirmed"}
            write = MemoryWrite.model_validate(data)
            if decide_write(write, actor).status != "active":
                raise MemoryError("sensitive_confirmation_required")
            result = await self.revise(entry.id, entry.version, write, actor)
        else:
            result = {"id": entry.id, "status": "dismissed"}
            if entry.status == "proposed" and proposal.candidate is None and entry.version == proposal.target_version:
                await self.set_status(entry.id, entry.version, "paused", actor)
        proposal.status = "accepted" if accept else "dismissed"
        proposal.resolved_at = datetime.utcnow()
        # Resolved proposals need no second copy of the proposed content.
        proposal.candidate = None
        await self.db.flush()
        return result

    async def set_status(self, entry_id: str, expected_version: int, status: str, actor: MemoryActor) -> dict:
        if actor.origin != "user" or status not in {"active", "paused"}:
            raise MemoryError("user_confirmation_required")
        entry = await self.get(entry_id, owner_id=actor.owner_id)
        if entry.status == "deleted":
            raise MemoryError("memory_deleted")
        if status == "active" and not entry.confirmation_kind:
            raise MemoryError("memory_confirmation_required")
        if status == "active" and (entry.sensitivity == "secret" or entry.use_policy == "never"):
            raise MemoryError("restricted_memory")
        if status == "active" and entry.expires_at and entry.expires_at <= datetime.utcnow():
            raise MemoryError("memory_expired")
        previous = await self.db.get(MemoryRevision, entry.current_revision_id)
        revision_id = _id()
        result = await self.db.execute(update(MemoryEntry).where(
            MemoryEntry.id == entry_id, MemoryEntry.version == expected_version,
        ).values(status=status, version=expected_version + 1, current_revision_id=revision_id,
                 updated_at=datetime.utcnow())
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise MemoryError("memory_version_conflict")
        self.db.add(MemoryRevision(
            id=revision_id, entry_id=entry_id, version=expected_version + 1, content=previous.content,
            structured_value=previous.structured_value, previous_version=expected_version,
            change_reason=f"status_{status}",
        ))
        await self.db.flush()
        await self._source(entry, revision_id, actor)
        await self.db.refresh(entry)
        await self._sync_index(entry.id)
        return await self.present(entry)

    async def present(self, entry, **extra) -> dict:
        revision = await self.db.get(MemoryRevision, entry.current_revision_id)
        sources = (await self.db.execute(select(MemorySource).where(
            MemorySource.entry_id == entry.id,
        ))).scalars().all()
        return {
            "id": entry.id, "kind": entry.kind,
            "scope": {"kind": entry.scope_kind, "id": entry.scope_id},
            "status": entry.status, "version": entry.version,
            "revision_id": entry.current_revision_id,
            "content": revision.content if revision and entry.status != "deleted" else None,
            "topic": (revision.structured_value or {}).get("topic") if revision else None,
            "style_reference": (revision.structured_value or {}).get("style_reference") if revision and entry.status != "deleted" else None,
            "core": (revision.structured_value or {}).get("core") if revision and entry.status != "deleted" else None,
            "sensitivity": entry.sensitivity, "use_policy": entry.use_policy,
            "confirmation_kind": entry.confirmation_kind, "confirmed_at": _iso(entry.confirmed_at),
            "valid_from": _iso(entry.valid_from), "review_at": _iso(entry.review_at),
            "expires_at": _iso(entry.expires_at), "created_at": _iso(entry.created_at),
            "updated_at": _iso(entry.updated_at),
            "sources": [{"id": row.id, "revision_id": row.revision_id, "kind": row.source_kind, "reference": row.source_ref,
                         "author": row.author, "observed_at": _iso(row.observed_at)} for row in sources],
            **extra,
        }

    async def list_entries(self, *, owner_id="local", scope: MemoryScope | None = None,
                           include_deleted=False, limit=200, offset=0) -> list[dict]:
        query = select(MemoryEntry).where(MemoryEntry.owner_id == owner_id)
        if not include_deleted:
            query = query.where(MemoryEntry.status != "deleted")
        if scope:
            query = query.where(MemoryEntry.scope_kind == scope.kind, MemoryEntry.scope_id == scope.id)
        entries = (await self.db.execute(query.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id)
                                        .limit(min(max(limit, 1), 500)).offset(max(offset, 0)))).scalars().all()
        # 0.1.55 §13: "used N times this week", counted from the turn receipts.
        from server.services.memory_stats import usage
        used, _totals = await usage(self.db, owner_id=owner_id)
        return [await self.present(entry, **self._usage(used.get(entry.id))) for entry in entries]

    @staticmethod
    def _usage(seen: dict | None) -> dict:
        return {"uses_this_week": (seen or {}).get("uses", 0), "last_used_at": (seen or {}).get("last_used_at")}

    async def history(self, entry_id: str, *, owner_id="local") -> list[dict]:
        entry = await self.get(entry_id, owner_id=owner_id)
        revisions = (await self.db.execute(select(MemoryRevision).where(
            MemoryRevision.entry_id == entry_id,
        ).order_by(MemoryRevision.version.desc()))).scalars().all()
        return [{"id": row.id, "version": row.version, "content": row.content,
                 "style_reference": (row.structured_value or {}).get("style_reference"),
                 "change_reason": row.change_reason, "created_at": _iso(row.created_at)}
                for row in revisions if entry.status != "deleted"]

    async def delete_entry(self, entry_id: str, expected_version: int, actor: MemoryActor) -> dict:
        if actor.origin != "user":
            raise MemoryError("user_confirmation_required")
        entry = await self.get(entry_id, owner_id=actor.owner_id)
        if entry.version != expected_version:
            raise MemoryError("memory_version_conflict")
        if entry.status == "deleted":
            return {"id": entry.id, "status": "deleted", "version": entry.version}
        revisions = (await self.db.execute(select(MemoryRevision).where(
            MemoryRevision.entry_id == entry_id))).scalars().all()
        sources = (await self.db.execute(select(MemorySource).where(
            MemorySource.entry_id == entry_id))).scalars().all()
        state = await self.state()
        state.deletion_epoch += 1
        digests = {await self.digest(row.content) for row in revisions if row.content}
        if entry.normalized_hash:
            digests.add(entry.normalized_hash)
        now = datetime.utcnow()
        for digest in digests:
            await self.db.execute(sqlite_insert(MemoryDeletion).values(
                id=_id(), instance_id=state.instance_id, entry_id=entry_id, epoch=state.deletion_epoch,
                content_digest=digest, scope_kind=entry.scope_kind, scope_key=entry.scope_id or "",
            ).on_conflict_do_nothing())
        suppressions = {(key, str(value)) for source in sources for key, value in source.source_ref.items()
                        if key in {"task_id", "message_id", "conversation_id", "run_id"} and value is not None}
        for kind, source_id in suppressions:
            self.db.add(MemorySuppression(source_kind=kind, source_id=source_id,
                                          entry_id=entry_id, cutoff_at=now))
        revision_id = _id()
        result = await self.db.execute(update(MemoryEntry).where(
            MemoryEntry.id == entry_id, MemoryEntry.version == expected_version,
        ).values(status="deleted", version=expected_version + 1, current_revision_id=revision_id,
                 normalized_hash=None, dedup_key=None, confirmed_at=None, confirmation_kind=None,
                 updated_at=now).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise MemoryError("memory_version_conflict")
        self.db.add(MemoryRevision(id=revision_id, entry_id=entry_id, version=expected_version + 1,
                                  content=None, previous_version=None, change_reason="deleted"))
        await self.db.flush()
        await self.db.execute(delete(MemorySource).where(MemorySource.entry_id == entry_id))
        await self.db.execute(delete(MemoryRevision).where(
            MemoryRevision.entry_id == entry_id, MemoryRevision.id != revision_id))
        await self.db.execute(update(MemoryProposal).where(MemoryProposal.target_entry_id == entry_id)
                              .values(candidate=None, status="dismissed", reason="target_deleted"))
        # Legacy derived snapshots predate receipt-level provenance. Invalidate them
        # rather than letting an old summary/prompt silently restore deleted memory.
        await self.db.execute(delete(ArslanSummary))
        await self.db.execute(update(Run).values(system_prompt=None, injected_kb=None))
        await self._erase_legacy_payload(entry_id)
        await self._sync_index(entry_id)
        await self.db.refresh(entry)
        self.deletions_changed = True
        return {"id": entry_id, "status": "deleted", "version": entry.version,
                "deletion_epoch": state.deletion_epoch}

    async def turn_entries(self, conversation_id: str, message_ids: set[int], run_ids: set[int]):
        """S3b: what undone turns of `conversation_id` taught: entries every source of which is one of those
        turns, and the entries something else backs too (the user's acceptance, another conversation's save,
        an older turn), each with those turns' sources: ([(entry, sources)], same) (⓪Plan's ruling, 🟠3)."""
        if not message_ids and not run_ids:
            return [], []
        matched = (await self.db.execute(select(MemorySource).where(
            func.json_extract(MemorySource.source_ref, "$.conversation_id") == conversation_id,
            or_(func.json_extract(MemorySource.source_ref, "$.message_id").in_(sorted(message_ids)),
                func.json_extract(MemorySource.source_ref, "$.run_id").in_(sorted(run_ids))),
        ))).scalars().all()
        mine = {source.id for source in matched}
        taught, trimmed = [], []
        for entry_id in sorted({source.entry_id for source in matched}):
            entry = await self.db.get(MemoryEntry, entry_id)   # a deleted entry has no sources left to match
            if entry is None:
                continue
            every = (await self.db.execute(select(MemorySource.id).where(
                MemorySource.entry_id == entry_id))).scalars().all()
            (taught if set(every) <= mine else trimmed).append(
                (entry, [source for source in matched if source.entry_id == entry_id]))
        return taught, trimmed

    async def forget_turns(self, conversation_id: str, message_ids: set[int], run_ids: set[int]) -> int:
        """S3b (turn_undo): take back what undone turns taught; returns how many entries went. Unlike
        `delete_entry` (Forget): no tombstone of the text, no suppression beyond these turns' own messages
        and runs, summaries and run prompts kept. An entry something else backs too loses just their sources
        (⓪Plan's Q4 and its ruling on the review)."""
        taught, trimmed = await self.turn_entries(conversation_id, message_ids, run_ids)
        now = datetime.utcnow()
        for entry, sources in taught:
            # These turns' own messages and runs, for this entry (as `delete_entry` keys them): a writer still
            # holding one is refused (`_not_suppressed`). Never the conversation or the task.
            for kind, value in {(key, source.source_ref[key]) for source in sources for key in ("message_id", "run_id")
                                if source.source_ref.get(key) in (message_ids if key == "message_id" else run_ids)}:
                await self.db.execute(sqlite_insert(MemorySuppression).values(
                    source_kind=kind, source_id=str(value), entry_id=entry.id, cutoff_at=now, created_at=now,
                ).on_conflict_do_nothing())
            revision_id = _id()
            result = await self.db.execute(update(MemoryEntry).where(
                MemoryEntry.id == entry.id, MemoryEntry.version == entry.version,
            ).values(status="deleted", version=entry.version + 1, current_revision_id=revision_id,
                     normalized_hash=None, dedup_key=None, confirmed_at=None, confirmation_kind=None,
                     updated_at=now).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise MemoryError("memory_version_conflict")
            self.db.add(MemoryRevision(id=revision_id, entry_id=entry.id, version=entry.version + 1,
                                       content=None, previous_version=None, change_reason="turn_undone"))
            await self.db.flush()
            await self.db.execute(delete(MemorySource).where(MemorySource.entry_id == entry.id))
            await self.db.execute(delete(MemoryRevision).where(
                MemoryRevision.entry_id == entry.id, MemoryRevision.id != revision_id))
            await self.db.execute(update(MemoryProposal).where(MemoryProposal.target_entry_id == entry.id)
                                  .values(candidate=None, status="dismissed", reason="turn_undone"))
            await self._sync_index(entry.id)
        for _entry, sources in trimmed:
            await self.db.execute(delete(MemorySource).where(MemorySource.id.in_([s.id for s in sources])))
        await self.db.flush()
        return len(taught)

    async def _erase_legacy_payload(self, entry_id):
        mapping = await self.db.scalar(select(MemoryLegacyMap).where(MemoryLegacyMap.entry_id == entry_id))
        if not mapping or mapping.migration_note == "v2_alias":
            return
        state = await self.state()
        previous_phase = state.phase
        state.phase = "maintenance"
        await self.db.flush()
        if mapping.source_table in {"user_facts", "learnings"}:
            table = ("legacy_" + mapping.source_table) if await self.db.scalar(text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": "legacy_" + mapping.source_table}) else mapping.source_table
            await self.db.execute(text(f"DELETE FROM {table} WHERE id=:id"),
                                  {"id": int(mapping.source_key)})
        elif mapping.source_table == "spawns":
            spawn_id, index = map(int, mapping.source_key.split(":"))
            raw = await self.db.scalar(text("SELECT memory_facts FROM spawns WHERE id=:id"), {"id": spawn_id})
            values = json.loads(raw) if isinstance(raw, str) else list(raw or [])
            if index < len(values):
                values[index] = ""
                await self.db.execute(text("UPDATE spawns SET memory_facts=:values WHERE id=:id"),
                                      {"values": json.dumps(values), "id": spawn_id})
        state.phase = previous_phase
        await self.db.flush()
