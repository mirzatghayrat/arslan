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


def _strip_section(text: str) -> str:
    """Remove a previously-injected evolution block, returning the base body."""
    if _START in text and _END in text:
        pre, rest = text.split(_START, 1)
        _, post = rest.split(_END, 1)
        return (pre.rstrip("\n") + "\n" + post.lstrip("\n")).rstrip("\n") + "\n"
    return text


def apply_tier1_evolution(pack_path: Path | str) -> bool:
    """Rewrite the managed evolution section in SKILL.md from active rules.

    Returns ``True`` when SKILL.md changed. Below the minimum sample size (or
    with no active rules) the section is absent/removed and nothing else moves.
    Only SKILL.md and ``evolution/`` are written.
    """
    pack_path = Path(pack_path)
    skill_md = pack_path / "SKILL.md"

    engine = EvolutionEngine(pack_path / "evolution")
    rules = engine.analyze_patterns()
    if rules:
        engine.save_rules(rules)
    active = engine.get_active_rules()

    original = skill_md.read_text(encoding="utf-8")
    base = _strip_section(original)
    if active:
        new_text = base.rstrip("\n") + "\n\n" + _render_section(active) + "\n"
    else:
        new_text = base

    if new_text != original:
        skill_md.write_text(new_text, encoding="utf-8")
        return True
    return False
