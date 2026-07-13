"""Synthetic cold-start corpus (S2 E6).

When a spawn has too few real, replayable runs to gate on, the ReplayGate needs
extra evaluation tasks. This module GENERATES them (never merged with real
win-rates — see spec §2 ruling 2 / replay_gate) from two sources:

  - source='domain'  : representative tasks built from the spawn's persona
                       (domain_category, persona_role, capabilities).
                       source_run_id is NULL.
  - source='variant' : rewrites of the spawn's real tasks (from scored epoch>=1
                       live runs via replay_set). Each variant records the
                       source_run_id it was derived from.

USER-LOCKED INVARIANT (split inheritance, spec audit CRITICAL-8): a 'variant'
inherits the propose/holdout side of its SOURCE real task, computed with the
EXACT SAME function build_corpus uses to split real tasks — `replay_gate._split_side`.
It is imported and reused verbatim here (never reimplemented) so a holdout task's
variant can NEVER leak into the propose set. A 'domain' task has no source, so it
is split by that same hash of its own (spawn_id, task_text).

Versioning: each generate() call writes a NEW version = max(existing)+1. Older
versions are kept for provenance; build_corpus only ever reads the current
(max) version's status='active' rows.

First-replay validation: validate_and_prune() replays each active task once with
the spawn's current prompt; if the trace shows a call to a tool OUTSIDE the
replay-safe builtin set (the task needed a disabled tool), the task is marked
status='invalid' — which drops it from build_corpus's status='active' filter.

Defensive throughout: a malformed / over-length / empty LLM item is skipped, never
raised; a whole-source LLM failure yields no rows for that source; zero valid → [].
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select

from server.db.models import Spawn, SyntheticTask
from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import wrap_external
from server.services import replay_gate, replay_run, replay_set
from server.services.llm_factory import build_adapter
from server.services.prompts import synthetic_corpus as prompts
from server.services.replay_safety import REPLAY_SAFE_BUILTINS

logger = logging.getLogger(__name__)

MAX_TASK_LEN = prompts.MAX_TASK_LEN
_REAL_TASK_CAP = 12   # newest real tasks considered as variant sources


def _valid_task(text) -> str | None:
    """Normalize one candidate task string, or None if it must be skipped.

    A task is kept only if it is a non-empty string of <= MAX_TASK_LEN chars
    after stripping. Everything else (non-str, empty, over-length) is dropped."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or len(t) > MAX_TASK_LEN:
        return None
    return t


def _parse_tasks(content: str | None) -> list[str]:
    """Lift a {"tasks": [...]} list of strings out of a raw LLM response.
    Any parse problem or non-list payload yields [] (never raises)."""
    try:
        parsed = parse_json_object(content or "") or {}
        raw = parsed.get("tasks")
        return [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    except Exception as exc:  # noqa: BLE001 — a malformed batch must not break generation
        logger.warning("synthetic_corpus: failed to parse task batch: %s", exc)
        return []


async def _gen_domain(adapter, spawn: Spawn, budget: int) -> list[str]:
    """Generate up to `budget` domain-representative task strings (raw, unvalidated)."""
    if budget <= 0:
        return []
    domain = spawn.domain_category or ""
    if spawn.domain_subcategory:
        domain = f"{domain}.{spawn.domain_subcategory}"
    caps = ", ".join(spawn.capabilities or []) if isinstance(spawn.capabilities, list) else ""
    try:
        resp = await adapter.chat(
            system=prompts.build_domain_system(REPLAY_SAFE_BUILTINS),
            user=prompts.build_domain_prompt(
                name=spawn.name or "", domain=domain,
                persona_role=spawn.persona_role or "", capabilities=caps, n=budget),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("synthetic_corpus: domain generation failed: %s", exc)
        return []
    return _parse_tasks(getattr(resp, "content", None))


async def _gen_variants(adapter, spawn: Spawn, real_items: list[dict],
                        budget: int) -> list[tuple[str, int, str]]:
    """Generate up to `budget` variant tuples (variant_text, source_run_id, source_task).

    One LLM call PER source real task so every returned variant is unambiguously
    attributable to its source (required for source_run_id + split inheritance)."""
    out: list[tuple[str, int, str]] = []
    if budget <= 0 or not real_items:
        return out
    per = max(1, -(-budget // len(real_items)))   # ceil(budget / #sources)
    variant_system = prompts.build_variant_system(REPLAY_SAFE_BUILTINS)
    for it in real_items:
        if len(out) >= budget:
            break
        src_task = it.get("task") or ""
        src_run_id = it.get("run_id")
        if not src_task or src_run_id is None:
            continue
        try:
            resp = await adapter.chat(
                system=variant_system,
                user=prompts.build_variant_prompt(
                    name=spawn.name or "",
                    source_task=wrap_external(src_task), n=per),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("synthetic_corpus: variant generation failed: %s", exc)
            continue
        for v in _parse_tasks(getattr(resp, "content", None)):
            out.append((v, src_run_id, src_task))
            if len(out) >= budget:
                break
    return out


async def generate(db, spawn_id: int, *, n: int = 24, adapter=None) -> list[SyntheticTask]:
    """Generate a NEW version of synthetic tasks for `spawn_id` and persist them.

    Builds up to `n` tasks from the domain persona + rewrites of real tasks, writes
    them as a fresh version (max+1), and returns the created rows. Split inheritance
    is enforced by reusing `replay_gate._split_side` (variants inherit their source
    real task's side; domain tasks split by their own text). Defensive: skips
    malformed/over-length/empty items; zero valid → [] (logged, no version written)."""
    spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        logger.warning("synthetic_corpus.generate: spawn %s not found", spawn_id)
        return []
    if adapter is None:
        adapter = await build_adapter(role="judgment")

    real_items = await replay_set.build(spawn_id, cap=_REAL_TASK_CAP)
    n_variant = min(len(real_items), n // 2)
    n_domain = n - n_variant

    variants = await _gen_variants(adapter, spawn, real_items, n_variant)
    domain_tasks = await _gen_domain(adapter, spawn, n_domain)

    # New version = current max + 1 (older versions kept for provenance).
    cur = (await db.execute(
        select(func.max(SyntheticTask.version)).where(SyntheticTask.spawn_id == spawn_id)
    )).scalar()
    new_version = (cur or 0) + 1

    rows: list[SyntheticTask] = []
    # Variants first (real-derived, most valuable); each inherits its SOURCE's side.
    for text, src_run_id, src_task in variants:
        task = _valid_task(text)
        if task is None:
            continue
        rows.append(SyntheticTask(
            spawn_id=spawn_id, version=new_version, task=task, source="variant",
            source_run_id=src_run_id,
            split_side=replay_gate._split_side(spawn_id, src_task),   # INHERIT source side
            status="active",
        ))
        if len(rows) >= n:
            break
    for text in domain_tasks:
        if len(rows) >= n:
            break
        task = _valid_task(text)
        if task is None:
            continue
        rows.append(SyntheticTask(
            spawn_id=spawn_id, version=new_version, task=task, source="domain",
            source_run_id=None,
            split_side=replay_gate._split_side(spawn_id, task),       # own-text hash
            status="active",
        ))

    if not rows:
        logger.info("synthetic_corpus.generate: no valid tasks for spawn %s", spawn_id)
        return []

    db.add_all(rows)
    await db.commit()
    return rows


async def mint_domain_holdout(db, spawn_id: int, n: int, *, adapter=None) -> list[SyntheticTask]:
    """E9-b: mint `n` fresh DOMAIN synthetic tasks FORCED to the holdout side, persisted at the
    current version (or version 1 if the spawn has none yet). Domain tasks have source_run_id=None
    (their own independence root) so forcing them to holdout never violates split inheritance
    (only a variant would need its source's side). Used to top the holdout side up to the gate
    floor when the real holdout is too thin — provenance stays honest (corpus_label='synthetic')."""
    if n <= 0:
        return []
    spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        logger.warning("mint_domain_holdout: spawn %s not found", spawn_id)
        return []
    if adapter is None:
        adapter = await build_adapter(role="judgment")
    domain_tasks = await _gen_domain(adapter, spawn, n)
    cur = (await db.execute(
        select(func.max(SyntheticTask.version)).where(SyntheticTask.spawn_id == spawn_id)
    )).scalar()
    version = cur or 1   # append to the current active version so build_corpus reads them
    rows: list[SyntheticTask] = []
    for text in domain_tasks:
        task = _valid_task(text)
        if task is None:
            continue
        rows.append(SyntheticTask(
            spawn_id=spawn_id, version=version, task=task, source="domain",
            source_run_id=None, split_side="holdout", status="active"))
        if len(rows) >= n:
            break
    if not rows:
        logger.info("mint_domain_holdout: no valid domain tasks for spawn %s", spawn_id)
        return []
    db.add_all(rows)
    await db.commit()
    return rows


async def mark_invalid(db, task_id: int) -> None:
    """Mark one synthetic task status='invalid' (idempotent) so build_corpus drops it."""
    st = await db.get(SyntheticTask, task_id)
    if st is not None and st.status != "invalid":
        st.status = "invalid"
        await db.commit()


async def validate_and_prune(db, spawn_id: int, *, run_arm=None) -> int:
    """First-replay validation: replay each active current-version synthetic task once
    with the spawn's CURRENT prompt; if that replay's trace calls a tool OUTSIDE the
    replay-safe builtin set (the task needed a disabled tool), mark it status='invalid'.
    Returns the number pruned. Cheap/optional: bounded by the active-task count.

    `run_arm` is injectable for tests; defaults to replay_run.run_arm."""
    run_arm = run_arm or replay_run.run_arm
    spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        return 0

    cur = (await db.execute(
        select(func.max(SyntheticTask.version)).where(SyntheticTask.spawn_id == spawn_id)
    )).scalar()
    if cur is None:
        return 0
    tasks = (await db.execute(
        select(SyntheticTask).where(
            SyntheticTask.spawn_id == spawn_id,
            SyntheticTask.version == cur,
            SyntheticTask.status == "active",
        )
    )).scalars().all()

    pruned = 0
    for st in tasks:
        try:
            ambient = await replay_run.snapshot_ambient(
                db, spawn_id=spawn_id,
                conversation_id=replay_run.REPLAY_CONVERSATION_ID, task=st.task)
            arm = await run_arm(
                db, spawn_id=spawn_id, task=st.task,
                system_prompt=spawn.system_prompt or "", ambient=ambient)
        except Exception as exc:  # noqa: BLE001 — a bad replay must not break the sweep
            logger.warning("synthetic_corpus.validate: replay failed for task %s: %s",
                           st.id, exc)
            continue
        run_id = (arm or {}).get("run_id")
        if run_id is None:
            continue
        # is_replayable == "every tool_call used a replay-safe builtin"; a False here means
        # the replay tried a disabled tool → the task is not completable safely → invalid.
        if not await replay_run.is_replayable(db, run_id):
            await mark_invalid(db, st.id)
            pruned += 1
    return pruned
