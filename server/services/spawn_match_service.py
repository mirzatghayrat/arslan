"""Score existing spawns against a capability need; classify into invite_one / picker / create."""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import wrap_external
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

STRONG = 0.8
MARGIN = 0.15
LOW = 0.4
_STRUCT_WEIGHT = 0.4
_COVER_WEIGHT = 0.6


def _split_domain(domain: str) -> tuple[str, str | None]:
    cat, _, sub = (domain or "").partition(".")
    return cat, (sub or None)


def _spawn_domain(spawn: dict) -> tuple[str | None, str | None]:
    """Accept both spawn-dict shapes: ORM-style split keys
    ({domain_category, domain_subcategory}) and SpawnOut-style single string
    ({domain: "cat.sub"}). Returns (category, subcategory)."""
    if spawn.get("domain_category") is not None:
        return spawn.get("domain_category"), spawn.get("domain_subcategory")
    if spawn.get("domain"):
        return _split_domain(spawn["domain"])
    return None, None


def _structural_score(need: dict, spawn: dict) -> float:
    cat, sub = _split_domain(need.get("domain", ""))
    spawn_cat, spawn_sub = _spawn_domain(spawn)
    if not cat or spawn_cat != cat:
        return 0.0
    score = 0.5
    if sub and spawn_sub == sub:
        score += 0.5
    return score


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    # role="draft" to match equipment_service.curate (lightweight coverage scoring).
    return build_adapter(role="draft")


async def _llm_coverage(need: dict, spawns: list[dict]) -> dict[int, float]:
    """Ask the LLM what fraction of the need's capabilities each spawn covers. Returns {id: 0..1}.

    Best-effort: on failure returns {} (callers treat missing as 0.0).
    """
    if not spawns:
        return {}
    caps = ", ".join(need.get("capabilities") or [])
    roster = "\n".join(
        f'{s["id"]}: {s.get("name")} — caps: {", ".join(s.get("capabilities") or [])}'
        for s in spawns
    )
    system = (
        "Rate how well each existing agent already covers the NEED's capabilities. "
        'Return JSON {"<id>": 0.0-1.0, ...} — fraction of the need each agent covers.'
    )
    user = wrap_external(f"NEED capabilities: {caps}\n\nAGENTS:\n{roster}")
    try:
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(system=system, user=user)
        parsed = parse_json_object(resp.content or "") or {}
        return {int(k): float(v) for k, v in parsed.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("match: llm coverage failed: %s", exc)
        return {}


async def score_spawns(need: dict, spawns: list[dict]) -> list[dict]:
    """Rank spawns against a need by structural + LLM-coverage score.

    Each spawn dict needs an ``id`` and may carry its domain in either shape:
    ORM-style split keys ({domain_category, domain_subcategory}) or SpawnOut-style
    single string ({domain: "category.subcategory"}). Returns a list sorted by
    score desc, each item {spawn_id, name, score, why}.
    """
    cover = await _llm_coverage(need, spawns)
    ranked = []
    for s in spawns:
        st = _structural_score(need, s)
        cov = cover.get(s["id"], 0.0)
        score = round(_STRUCT_WEIGHT * st + _COVER_WEIGHT * cov, 4)
        ranked.append({
            "spawn_id": s["id"],
            "name": s.get("name"),
            "score": score,
            "why": f"domain {st:.1f}, coverage {cov:.1f}",
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


def classify_band(ranked: list[dict]) -> tuple[str, dict]:
    if not ranked or ranked[0]["score"] < LOW:
        return "create", {}
    top = ranked[0]
    second = ranked[1]["score"] if len(ranked) > 1 else 0.0
    if top["score"] >= STRONG and (top["score"] - second) >= MARGIN:
        return "invite_one", {"spawn_id": top["spawn_id"], "name": top["name"], "why": top["why"]}
    candidates = [r for r in ranked if r["score"] >= LOW]
    return "picker", {"candidates": candidates}
