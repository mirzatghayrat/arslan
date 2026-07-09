"""Tier enforcement choke point. ALL spawn-capability reads/writes route through here.

Layer 1: safe_menu() — the only listing spawn-facing contexts may use.
Layer 2: assert_assignable() — the only gate on spawn_capabilities writes.
Layer 3: wired_tools_for_spawn() — the only tool resolution the loop may call.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import session as db_session
from server.db.models import SkillPack, SpawnCapability, Tool, Toolset

ASSIGNABLE_STATUSES = ("wired", "registered")

# Deterministic, side-effect-free safe tools every spawn may use without per-spawn equipment.
# The safe+wired filter STILL applies — this cannot be used to bypass the choke point.
_UNIVERSAL_SAFE_TOOLS = ["web_search", "web_extract", "render_chart"]  # safe "work-smart" baseline every spawn has


def is_assignable(tier: str, status: str) -> bool:
    """Base assignability predicate: safe tier + wired/registered status."""
    return tier == "safe" and status in ASSIGNABLE_STATUSES


# ── Honesty layer (P0): equippable must mean FUNCTIONAL, not just catalogued ──────────
# A skill with no body injects nothing at dispatch; a toolset with no wired tool resolves
# to nothing at Layer 3. Both used to be equippable decoration. Now: catalog-only items
# stay VISIBLE in the library (assignable: false, shown as "catalog") but cannot be
# equipped until they gain a real body / a wired tool.

def skill_is_assignable(tier: str, status: str, body: str | None) -> bool:
    """A skill is equippable only if it actually does something: safe + registered/wired
    + a non-empty method body (otherwise dispatch injects nothing — pure decoration)."""
    return is_assignable(tier, status) and bool((body or "").strip())


def toolset_is_assignable(tier: str, status: str, *, has_wired_tool: bool) -> bool:
    """A toolset is equippable only if at least one of its tools is safe+wired (Layer 3
    resolves nothing otherwise). MCP toolsets qualify naturally once their tools are wired."""
    return is_assignable(tier, status) and has_wired_tool


# Subquery: keys of toolsets that have >=1 safe wired tool.
_WIRED_TOOLSET_KEYS = select(Tool.toolset_key).where(
    Tool.tier == "safe", Tool.status == "wired")

# Skills with a real body (non-null, non-empty after trim).
_SKILL_HAS_BODY = func.length(func.trim(func.coalesce(SkillPack.body, ""))) > 0


class NotAssignableError(Exception):
    """Raised when a capability is not in the spawn-assignable safe subset."""


def _toolset_dict(t: Toolset) -> dict:
    return {"key": t.key, "name": t.name, "description": t.description,
            "tier": t.tier, "status": t.status}


def skill_has_scripts(key: str) -> bool:
    """True iff data_dir/skill_scripts/<key>/ exists and holds >=1 .py file.

    Mirrors RunPythonExecutor._load_skill_script's resolution root (executors.py) so the
    injected run-hint line fires exactly when a bundled script is actually loadable via
    run_python(skill_script="<key>/<file>.py"). Fail-closed on any FS error → False."""
    if not key:
        return False
    root = Path(os.environ.get("ARSLAN_DATA_DIR", "data")) / "skill_scripts" / key
    try:
        return any(p.is_file() and p.suffix == ".py" for p in root.iterdir())
    except OSError:
        return False


def skill_has_references(key: str) -> bool:
    """True iff data_dir/skill_scripts/<key>/references/ exists and holds >=1 file.

    Mirrors skill_has_scripts for the bundled read-only docs PC-2 stores (only .md/.txt
    are mounted, but any file present means the skill ships reference material).
    Fail-closed on any FS error → False."""
    if not key:
        return False
    root = (Path(os.environ.get("ARSLAN_DATA_DIR", "data"))
            / "skill_scripts" / key / "references")
    try:
        return any(p.is_file() for p in root.iterdir())
    except OSError:
        return False


def _skill_script_paths(key: str) -> list[Path]:
    """Top-level (non-references/) files bundled under skill_scripts/<key>/."""
    if not key:
        return []
    root = Path(os.environ.get("ARSLAN_DATA_DIR", "data")) / "skill_scripts" / key
    try:
        return [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return []


def skill_compatibility(key: str, body: str | None) -> str:
    """Deterministic per-skill sandbox-compatibility class from REAL bundle signals.

    HONEST by construction: never returns "full" unless every bundled capability is
    runnable in the sandbox exactly as shipped (all .py, none declaring an unsupported
    `# requires:` need). When a script can't be read or verified, we downgrade to
    "partial" rather than overclaim.

    Rule (first match wins):
      • no bundled scripts AND no references            → "text"    (仅文本: body-only)
      • bundled scripts present:
          - any non-.py entry                           → "partial" (sandbox runs .py only)
          - any .py entry unreadable / not UTF-8        → "partial" (can't stand behind full)
          - any .py entry with a `# requires: net|cli`  → "partial" (sandbox denies, fails closed)
          - otherwise (all .py, all clean)              → "full"    (scripts run; bundled refs,
                                                                      if any, mount read-only)
      • no scripts but bundled references               → "partial" (material fetched via
                                                                      read_skill, not inlined)

    `body` is accepted so the classifier owns the full skill picture; a skill with neither
    scripts nor references is "text" regardless of body length (body-only == pure text).
    """
    from server.registry.executors import RunPythonExecutor  # lazy: avoid import cycle
    scripts = _skill_script_paths(key)
    has_refs = skill_has_references(key)
    if not scripts and not has_refs:
        return "text"
    if scripts:
        if any(p.suffix != ".py" for p in scripts):
            return "partial"
        for p in scripts:
            try:
                src = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return "partial"
            if RunPythonExecutor._scan_requires(src):
                return "partial"
        return "full"
    return "partial"  # references only


def _declared_bundles(body: str | None) -> tuple[set[str], set[str]]:
    """Parse the PC-2 body sections for DECLARED bundled files (source of truth for what the
    skill *claims* to ship). Returns (script_basenames, reference_relpaths).

    The importer writes, under fixed headers:
        ## Bundled scripts
        - `<key>/<file>`
        ## Bundled references
        - `references/<file>`
    We read the bullet lines beneath each header so storage health can flag a script/ref the
    body advertises but that is missing on disk (integrity), and vice-versa (orphan)."""
    import re as _re
    scripts: set[str] = set()
    refs: set[str] = set()
    section: str | None = None
    for line in (body or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("## bundled scripts"):
            section = "scripts"
            continue
        if low.startswith("## bundled references"):
            section = "references"
            continue
        if stripped.startswith("## "):
            section = None            # a different section ends the bundle list
            continue
        if section is None:
            continue
        m = _re.search(r"`([^`]+)`", stripped)   # bullet like: - `key/file.py`
        if not m:
            continue
        ref = m.group(1).strip()
        if section == "scripts":
            scripts.add(ref.rsplit("/", 1)[-1])            # store basename
        else:
            # references are declared as `references/<file>` — keep the relpath for a clear label
            rel = ref if ref.startswith("references/") else f"references/{ref.rsplit('/', 1)[-1]}"
            refs.add(rel)
    return scripts, refs


def _reference_paths(key: str) -> list[Path]:
    """Files under data_dir/skill_scripts/<key>/references/ (fail-closed → [])."""
    if not key:
        return []
    root = (Path(os.environ.get("ARSLAN_DATA_DIR", "data"))
            / "skill_scripts" / key / "references")
    try:
        return [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return []


def skill_health(key: str, body: str | None) -> dict:
    """PC-5 per-skill health report: storage integrity + script runnability + references.

    HONEST by construction (mirrors skill_compatibility's discipline):
      • A `.py` is "runnable" ONLY when it is resolvable, UTF-8-decodable, declares no
        `# requires: network|cli` need, AND a real sandbox backend is AVAILABLE on this host
        (probed cheaply — never executed). No backend → "sandbox unavailable", never a lie.
      • Storage is "ok" ONLY when the body is non-empty AND every body-declared bundled file
        is actually present on disk. A declared-but-absent file is reported as missing; an
        on-disk file the body never declares is reported as orphaned (informational only).

    Bounded/cheap: pure filesystem reads of the skill's own small bundle. The endpoint wraps
    this in a short timeout, but nothing here blocks on the network or a subprocess."""
    from server.services import code_sandbox  # lazy: keep boot path light

    body = body or ""
    sandbox_ok = code_sandbox.backend_available()
    backend = code_sandbox.backend_name()

    declared_scripts, declared_refs = _declared_bundles(body)
    disk_script_files = _skill_script_paths(key)            # top-level files (any ext)
    disk_ref_files = _reference_paths(key)
    disk_script_names = {p.name for p in disk_script_files}
    disk_ref_rel = {f"references/{p.name}" for p in disk_ref_files}

    # ── storage integrity ────────────────────────────────────────────────────────────
    missing = sorted(
        [n for n in declared_scripts if n not in disk_script_names]
        + [r for r in declared_refs if r not in disk_ref_rel]
    )
    orphaned = sorted(
        [p.name for p in disk_script_files if p.name not in declared_scripts]
        + [f"references/{p.name}" for p in disk_ref_files
           if f"references/{p.name}" not in declared_refs]
    )
    body_present = bool(body.strip())
    storage = {
        "ok": body_present and not missing,
        "body_present": body_present,
        "declared_scripts": sorted(declared_scripts),
        "declared_references": sorted(declared_refs),
        "disk_scripts": sorted(disk_script_names),
        "disk_references": sorted(disk_ref_rel),
        "missing": missing,
        "orphaned": orphaned,
    }

    # ── per-script runnability (availability + integrity, never execution) ─────────────
    from server.registry.executors import RunPythonExecutor
    scripts: list[dict] = []
    for p in sorted(disk_script_files, key=lambda x: x.name):
        entry = {"name": p.name, "runnable": False, "reason": ""}
        if p.suffix != ".py":
            entry["reason"] = f"非 .py({p.suffix or '无扩展名'}),沙箱只支持 .py"
            scripts.append(entry)
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            entry["reason"] = "不是有效 UTF-8,无法读取(not UTF-8 decodable)"
            scripts.append(entry)
            continue
        need = RunPythonExecutor._scan_requires(src)
        if need:
            kind, raw = need
            entry["reason"] = f"声明 requires: {raw} — 需{kind},沙箱不支持(blocked)"
            scripts.append(entry)
            continue
        if not sandbox_ok:
            entry["reason"] = f"sandbox unavailable(本机无隔离后端 backend={backend},未标记可运行)"
            scripts.append(entry)
            continue
        entry["runnable"] = True
        entry["reason"] = f"ok(sandbox backend={backend})"
        scripts.append(entry)

    # ── references readability ─────────────────────────────────────────────────────────
    references: list[dict] = []
    for p in sorted(disk_ref_files, key=lambda x: x.name):
        rf = {"name": p.name, "readable": False, "reason": ""}
        # Only .md/.txt are mounted read-only for the sandbox (PC-3 ②); others ship but aren't mounted.
        if p.suffix not in (".md", ".txt"):
            rf["reason"] = f"{p.suffix or '无扩展名'} 不挂载(仅 .md/.txt 只读挂载)"
            references.append(rf)
            continue
        try:
            p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            rf["reason"] = "不是有效 UTF-8,无法读取"
            references.append(rf)
            continue
        rf["readable"] = True
        rf["reason"] = "ok"
        references.append(rf)

    # ── roll-up ────────────────────────────────────────────────────────────────────────
    scripts_ok = all(s["runnable"] for s in scripts)
    refs_ok = all(r["readable"] for r in references)
    ok = storage["ok"] and scripts_ok and refs_ok
    return {
        "key": key,
        "status": "ok" if ok else "degraded",
        "ok": ok,
        "sandbox_available": sandbox_ok,
        "sandbox_backend": backend,
        "compatibility": skill_compatibility(key, body),
        "storage": storage,
        "scripts": scripts,
        "references": references,
    }


def _skill_dict(s: SkillPack) -> dict:
    return {"key": s.key, "name": s.name, "description": s.description,
            "category": s.category, "tier": s.tier, "status": s.status,
            "has_scripts": skill_has_scripts(s.key),
            "compatibility": skill_compatibility(s.key, s.body)}


async def safe_menu() -> dict:
    """Everything a spawn may be equipped with: tier=safe, wired or registered, AND
    functional — toolsets need >=1 safe wired tool, skills need a real body."""
    async with db_session.AsyncSessionLocal() as db:
        ts = (await db.execute(
            select(Toolset).where(Toolset.tier == "safe",
                                  Toolset.status.in_(ASSIGNABLE_STATUSES),
                                  Toolset.key.in_(_WIRED_TOOLSET_KEYS))
            .order_by(Toolset.key)
        )).scalars().all()
        sk = (await db.execute(
            select(SkillPack).where(SkillPack.tier == "safe",
                                    SkillPack.status.in_(ASSIGNABLE_STATUSES),
                                    _SKILL_HAS_BODY)
            .order_by(SkillPack.key)
        )).scalars().all()
    return {"toolsets": [_toolset_dict(t) for t in ts],
            "skills": [_skill_dict(s) for s in sk]}


async def assert_assignable(kind: str, ref_key: str, *, session=None) -> None:
    """Hard server-side gate: raises unless (kind, ref_key) is safe + assignable.

    No bypass parameter exists by design (spec §2): the only holder of
    orchestrator-tier capabilities is Arslan itself, implicitly.

    Pass session= to reuse a caller-owned AsyncSession (same pattern as
    equipment_for_spawn); when None, opens its own via AsyncSessionLocal.
    """
    if kind not in ("toolset", "skill"):
        raise NotAssignableError(f"unknown capability kind: {kind}")

    async def _lookup(db):
        return (await db.get(Toolset, ref_key) if kind == "toolset"
                else await db.get(SkillPack, ref_key))

    async def _check(db) -> None:
        row = await _lookup(db)
        if row is None:
            raise NotAssignableError(f"unknown {kind}: {ref_key}")
        if not is_assignable(row.tier, row.status):
            raise NotAssignableError(
                f"{kind} {ref_key} is not spawn-assignable (tier={row.tier}, status={row.status})"
            )
        # Honesty layer: catalogued-but-non-functional items are not equippable.
        if kind == "skill" and not (row.body or "").strip():
            raise NotAssignableError(
                f"skill {ref_key} is catalog-only (no method body yet) — not equippable")
        if kind == "toolset":
            has_wired = (await db.execute(
                select(Tool.key).where(Tool.toolset_key == ref_key,
                                       Tool.tier == "safe", Tool.status == "wired")
                .limit(1)
            )).first() is not None
            if not has_wired:
                raise NotAssignableError(
                    f"toolset {ref_key} has no wired tools (catalog-only) — not equippable")

    if session is not None:
        await _check(session)
    else:
        async with db_session.AsyncSessionLocal() as db:
            await _check(db)


async def _equipment_for_spawn_in(db, spawn_id: int) -> dict:
    """Inner implementation reusable by both session-owning and session-borrowing callers."""
    caps = (await db.execute(
        select(SpawnCapability).where(SpawnCapability.spawn_id == spawn_id)
        .order_by(SpawnCapability.id)
    )).scalars().all()
    toolsets, skills = [], []
    # NOTE: N+1 per-capability lookups; fine at v1 cap counts (<10 rows per spawn).
    for c in caps:
        if c.kind == "toolset":
            row = await db.get(Toolset, c.ref_key)
            if row is not None:
                toolsets.append({**_toolset_dict(row), "grant": c.grant,
                                 "granted_by": c.granted_by, "expires_turn": c.expires_turn})
        else:
            row = await db.get(SkillPack, c.ref_key)
            if row is not None:
                skills.append({**_skill_dict(row), "grant": c.grant,
                               "granted_by": c.granted_by, "expires_turn": c.expires_turn})
    return {"toolsets": toolsets, "skills": skills}


async def equipment_for_spawn(spawn_id: int, *, session=None) -> dict:
    """All equipment rows resolved against the registry (for tags/DTOs).

    Pass session= to reuse a caller-owned AsyncSession (avoids bypassing the
    dependency-injection DB override in tests and API endpoints that already
    hold a session).  When session is None, opens its own via AsyncSessionLocal.
    """
    if session is not None:
        return await _equipment_for_spawn_in(session, spawn_id)
    async with db_session.AsyncSessionLocal() as db:
        return await _equipment_for_spawn_in(db, spawn_id)


async def skill_bodies(keys: list[str]) -> dict[str, str | None]:
    """Map skill key -> body for the given keys (for dispatch-time injection only).
    Kept off _skill_dict/SkillPackOut so body never leaks to list/detail APIs."""
    if not keys:
        return {}
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(SkillPack.key, SkillPack.body).where(SkillPack.key.in_(keys))
        )).all()
    return {k: b for k, b in rows}


async def replace_user_equipment(session: AsyncSession, spawn_id: int,
                                 toolsets: list[str], skills: list[str]) -> None:
    """User equipment editor write path: declarative replace of user-managed
    permanent grants (granted_by in create/user -> new rows granted_by=user).
    All-or-nothing: every key is validated via assert_assignable before any
    row is written.

    Promotion policy: if an incoming key is currently held as a temporary
    grant, that temporary row is removed and the key becomes a permanent
    granted_by="user" row. Temporary grants for keys NOT in the incoming
    selection are left untouched."""
    toolsets = list(dict.fromkeys(toolsets))
    skills = list(dict.fromkeys(skills))
    for key in toolsets:
        await assert_assignable("toolset", key, session=session)
    for key in skills:
        await assert_assignable("skill", key, session=session)
    selected = {("toolset", k) for k in toolsets} | {("skill", k) for k in skills}
    rows = (await session.execute(
        select(SpawnCapability).where(SpawnCapability.spawn_id == spawn_id)
    )).scalars().all()
    for r in rows:
        is_user_managed = (r.grant == "permanent"
                           and r.granted_by in ("create", "user"))
        is_promoted_temp = (r.grant == "temporary"
                            and (r.kind, r.ref_key) in selected)
        if is_user_managed or is_promoted_temp:
            await session.delete(r)
    await session.flush()
    for key in toolsets:
        session.add(SpawnCapability(spawn_id=spawn_id, kind="toolset", ref_key=key,
                                    grant="permanent", granted_by="user"))
    for key in skills:
        session.add(SpawnCapability(spawn_id=spawn_id, kind="skill", ref_key=key,
                                    grant="permanent", granted_by="user"))
    await session.commit()


async def wired_tools_for_spawn(spawn_id: int, *, current_turn: int) -> list[dict]:
    """Layer-3 gate: tools callable by this spawn RIGHT NOW = (equipped toolsets, permanent
    or unexpired-temporary) ∩ safe ∩ wired, UNION the universal safe tools (also safe ∩ wired)."""
    async with db_session.AsyncSessionLocal() as db:
        caps = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id,
                SpawnCapability.kind == "toolset",
            )
        )).scalars().all()
        active_keys = [
            c.ref_key for c in caps
            if c.grant == "permanent"
            or (c.expires_turn is not None and c.expires_turn >= current_turn)
        ]
        equipped: list = []
        if active_keys:
            equipped = (await db.execute(
                select(Tool).where(
                    Tool.toolset_key.in_(active_keys),
                    Tool.tier == "safe",
                    Tool.status == "wired",
                )
            )).scalars().all()
        universal = (await db.execute(
            select(Tool).where(
                Tool.key.in_(_UNIVERSAL_SAFE_TOOLS),
                Tool.tier == "safe",
                Tool.status == "wired",
            )
        )).scalars().all()
    by_key: dict = {}
    for t in [*equipped, *universal]:
        by_key.setdefault(t.key, t)
    rows = sorted(by_key.values(), key=lambda t: t.key)
    return [{"key": t.key, "description": t.description, "input_schema": t.input_schema or {}} for t in rows]


async def grant_temporary(spawn_id: int, ref_key: str, *, current_turn: int,
                          turns: int = 3) -> None:
    """Escalation path (b): temporary safe-only grant. Validated, idempotent."""
    await assert_assignable("toolset", ref_key)
    async with db_session.AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(SpawnCapability).where(
                SpawnCapability.spawn_id == spawn_id,
                SpawnCapability.kind == "toolset",
                SpawnCapability.ref_key == ref_key,
            )
        )).scalar_one_or_none()
        if existing is not None:
            if existing.grant == "temporary":
                existing.expires_turn = current_turn + turns
        else:
            db.add(SpawnCapability(
                spawn_id=spawn_id, kind="toolset", ref_key=ref_key,
                grant="temporary", granted_by="escalation",
                expires_turn=current_turn + turns,
            ))
        await db.commit()
