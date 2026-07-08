"""Curator (create_skill Slice 3): post-promotion hygiene for self-authored skills.

The Curator governs ONLY promoted, self-authored skills — a SkillCandidate with
status="promoted" (created by the skill forge, then human-promoted into a live
SkillPack). Built-in / ingested library skills are NOT the Curator's domain.

It does two things:

  review_promoted_skills()  — for each promoted skill, look at the REAL runs of
    the spawns it's equipped on (since promotion) and flag it `unused` (no runs
    after a grace period) or `underperforming` (enough scored runs, but a low
    average). This is a COARSE signal to prompt a human review, not a per-skill
    verdict: a spawn's run score reflects the whole spawn, not just this one
    equipped skill. Documented as a signal on purpose.

  retire_skill(key)         — HUMAN-CONFIRMED ONLY. Never automatic. Sets the
    SkillPack status="retired" (which makes it non-assignable at the registry
    choke point — server/registry/service.py ASSIGNABLE_STATUSES), marks the
    candidate retired, and DELETEs every SpawnCapability row for it (fully
    unassigns it from all spawns).

Cadence is on-demand today (a human opens the Skill Forge panel). A weekly cron
could call review_promoted_skills later — Hermes's weekly Curator — but retire is
never automatic. Self-manages its own AsyncSessionLocal sessions, like the forge.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Run, SkillCandidate, SkillPack, SpawnCapability

# Tunable thresholds (module constants).
UNDERPERF_SCORE = 5.0        # avg overall_score (out of 10) below this = underperforming
MIN_RUNS_FOR_QUALITY = 5     # need this many scored runs before a quality flag is fair
UNUSED_GRACE_DAYS = 7        # give a freshly-promoted skill this long before flagging unused


async def review_promoted_skills() -> list[dict]:
    """Review every promoted self-authored skill against its equipped spawns' real
    runs (since promotion) and return a per-skill signal row.

    Each row: {key, name, equipped_spawns, usage, avg_score, flag, reason}.
    flag ∈ {None, "unused", "underperforming"}. Coarse attribution by design.
    """
    now = datetime.utcnow()
    out: list[dict] = []
    async with db_session.AsyncSessionLocal() as db:
        cands = (await db.execute(
            select(SkillCandidate)
            .where(SkillCandidate.status == "promoted")
            .order_by(SkillCandidate.id.desc())
        )).scalars().all()

        for cand in cands:
            since = cand.promoted_at or cand.created_at or now

            spawn_ids = (await db.execute(
                select(SpawnCapability.spawn_id).where(
                    SpawnCapability.kind == "skill",
                    SpawnCapability.ref_key == cand.key,
                )
            )).scalars().all()
            spawn_ids = list(dict.fromkeys(spawn_ids))

            runs: list[Run] = []
            if spawn_ids:
                runs = list((await db.execute(
                    select(Run).where(
                        Run.spawn_id.in_(spawn_ids),
                        Run.created_at >= since,
                    )
                )).scalars().all())

            usage = len(runs)
            scores = [r.overall_score for r in runs if r.overall_score is not None]
            avg_score = round(sum(scores) / len(scores), 2) if scores else None

            age_days = (now - since).days
            flag: str | None = None
            reason: str | None = None
            if usage == 0 and age_days >= UNUSED_GRACE_DAYS:
                flag = "unused"
                reason = f"no runs in {age_days}d since promotion"
            elif (avg_score is not None and len(scores) >= MIN_RUNS_FOR_QUALITY
                  and avg_score < UNDERPERF_SCORE):
                flag = "underperforming"
                reason = f"avg score {avg_score}/10 over {len(scores)} scored runs"

            out.append({
                "key": cand.key,
                "name": cand.name,
                "equipped_spawns": len(spawn_ids),
                "usage": usage,
                "avg_score": avg_score,
                "flag": flag,
                "reason": reason,
            })
    return out


async def retire_skill(key: str) -> dict:
    """Human-confirmed retire of a promoted self-authored skill. Never automatic.

    Guard: must be a promoted SkillCandidate for `key`. Then set the SkillPack
    status="retired" (non-assignable), set the candidate status="retired", and
    DELETE every SpawnCapability(kind="skill", ref_key=key) row.
    """
    async with db_session.AsyncSessionLocal() as db:
        cand = (await db.execute(
            select(SkillCandidate).where(
                SkillCandidate.key == key,
                SkillCandidate.status == "promoted",
            )
        )).scalars().first()
        if cand is None:
            return {"ok": False, "reason": "not a promoted self-authored skill"}

        pack = await db.get(SkillPack, key)
        if pack is not None:
            pack.status = "retired"

        caps = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.kind == "skill",
                SpawnCapability.ref_key == key,
            )
        )).scalars().all()
        for c in caps:
            await db.delete(c)

        cand.status = "retired"
        await db.commit()
    return {"ok": True, "key": key, "unassigned": len(caps)}
