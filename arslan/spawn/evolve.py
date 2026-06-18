"""Tier-1 instruction evolution — inject learned rules into a skill-pack's SKILL.md.

This is the safe, autonomous half of the Evolution Engine: it rewrites a single
delimited section of ``SKILL.md`` from feedback-derived rules. It touches ONLY
``SKILL.md`` and the ``evolution/`` store — never ``scripts/`` or credentials.
Capability changes (new tools/credentials) are Tier-2 and go through the
registry choke point, not here.
"""
from __future__ import annotations

from pathlib import Path

from arslan.core.evolution import EvolutionEngine
from arslan.models import EvolutionRule

_START = "<!-- arslan:evolution:start -->"
_END = "<!-- arslan:evolution:end -->"
_EQ_START = "<!-- arslan:equipment:start -->"
_EQ_END = "<!-- arslan:equipment:end -->"


def _render_section(rules: list[EvolutionRule]) -> str:
    lines = [
        _START,
        "## 进化规则",
        "",
        f"共 {len(rules)} 条活跃规则，请遵循以下从用户反馈中学到的经验：",
    ]
    for i, rule in enumerate(rules, 1):
        lines.append(
            f"{i}. [{rule.rule_type}] {rule.rule}"
            f"（置信度 {rule.confidence:.0%}，样本 {rule.sample_size}）"
        )
    lines.append(_END)
    return "\n".join(lines)


def _strip_block(text: str, start: str, end: str) -> str:
    """Remove a previously-injected ``start``..``end`` block, returning the base body."""
    if start in text and end in text:
        pre, rest = text.split(start, 1)
        _, post = rest.split(end, 1)
        return (pre.rstrip("\n") + "\n" + post.lstrip("\n")).rstrip("\n") + "\n"
    return text


def apply_tier1_evolution(pack_path: Path | str) -> bool:
    """Rewrite the managed evolution section in SKILL.md from active rules.

    Returns ``True`` when SKILL.md changed. Below the minimum sample size (or
    with no active rules) the section is absent/removed and nothing else moves.
    Only SKILL.md and ``evolution/`` are written.
    """
    pack_path = Path(pack_path)
    engine = EvolutionEngine(pack_path / ".evolution")
    rules = engine.analyze_patterns()
    if rules:
        engine.save_rules(rules)
    return _inject_evolution_section(pack_path / "SKILL.md", engine.get_active_rules())


def _inject_evolution_section(skill_md: Path, active: list[EvolutionRule]) -> bool:
    """Rewrite the managed evolution block in SKILL.md from ``active`` rules."""
    if not skill_md.exists():
        return False  # rules persisted to .evolution; nothing to inject into
    original = skill_md.read_text(encoding="utf-8")
    base = _strip_block(original, _START, _END)
    if active:
        new_text = base.rstrip("\n") + "\n\n" + _render_section(active) + "\n"
    else:
        new_text = base
    if new_text != original:
        skill_md.write_text(new_text, encoding="utf-8")
        return True
    return False


def consolidate_evolution(pack_path: Path | str, now=None) -> int:
    """Prune decayed rules from rules.yaml and refresh the SKILL.md section.

    Unlike :func:`apply_tier1_evolution` this does NOT re-derive from feedback —
    it cleans the persisted set and re-injects the survivors. Returns the count
    of rules pruned.
    """
    pack_path = Path(pack_path)
    engine = EvolutionEngine(pack_path / ".evolution")
    removed = engine.prune_rules(now=now)
    _inject_evolution_section(pack_path / "SKILL.md", engine.get_active_rules(now=now))
    return removed


def reset_evolution(pack_path: Path | str) -> None:
    """Forget everything Tier-1 learned: clear feedback + rules + injected section.

    Touches only ``evolution/`` and SKILL.md — never scripts/ or credentials.
    """
    pack_path = Path(pack_path)
    evo = pack_path / ".evolution"
    for fname in ("rules.yaml", "feedback_log.jsonl"):
        target = evo / fname
        if target.exists():
            target.unlink()

    skill_md = pack_path / "SKILL.md"
    if skill_md.exists():
        text = skill_md.read_text(encoding="utf-8")
        stripped = _strip_block(text, _START, _END)
        if stripped != text:
            skill_md.write_text(stripped, encoding="utf-8")


def _render_equipment(capabilities: list[dict]) -> str:
    lines = [_EQ_START, "## 已装备能力", ""]
    if capabilities:
        for cap in capabilities:
            key = cap.get("key") or cap.get("ref_key") or ""
            desc = cap.get("description") or ""
            lines.append(f"- `{key}`：{desc}" if desc else f"- `{key}`")
    else:
        lines.append("（暂无装备能力）")
    lines.append(_EQ_END)
    return "\n".join(lines)


def apply_tier2_capabilities(pack_path: Path | str, capabilities: list[dict]) -> bool:
    """Reflect a spawn's granted equipment into a managed SKILL.md section (Tier-2).

    The DB equipment set stays the source of truth; this writes a *derived*,
    idempotent section so the portable skill-pack is self-describing. Touches only
    SKILL.md — the grant/gate/promotion itself happens through the registry choke
    point, never here. Returns ``True`` when SKILL.md changed.
    """
    pack_path = Path(pack_path)
    skill_md = pack_path / "SKILL.md"
    if not skill_md.exists():
        return False

    original = skill_md.read_text(encoding="utf-8")
    base = _strip_block(original, _EQ_START, _EQ_END)
    new_text = base.rstrip("\n") + "\n\n" + _render_equipment(capabilities) + "\n"

    if new_text != original:
        skill_md.write_text(new_text, encoding="utf-8")
        return True
    return False
