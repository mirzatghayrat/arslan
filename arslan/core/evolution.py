"""Evolution Engine — feedback collection, pattern analysis, and prompt tuning."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import yaml

from arslan.models import EvolutionRule, FeedbackEntry

MIN_SAMPLES = 20


# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------


class FeedbackStore:
    """Append-only JSONL store for FeedbackEntry records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, entry: FeedbackEntry) -> None:
        """Append one entry as a JSON line."""
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")

    def list_all(self) -> list[FeedbackEntry]:
        """Return all entries; empty list when the file does not exist."""
        if not self.path.exists():
            return []
        entries: list[FeedbackEntry] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(FeedbackEntry.model_validate_json(line))
        return entries

    def count(self) -> int:
        """Count non-empty lines without loading all entries into memory."""
        if not self.path.exists():
            return 0
        total = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    total += 1
        return total


# ---------------------------------------------------------------------------
# EvolutionEngine
# ---------------------------------------------------------------------------


class EvolutionEngine:
    """Analyses user feedback and derives prompt-tuning rules."""

    def __init__(self, evolution_dir: Path) -> None:
        self.evolution_dir = evolution_dir
        evolution_dir.mkdir(parents=True, exist_ok=True)

        self.feedback_store = FeedbackStore(evolution_dir / "feedback_log.jsonl")
        self.rules_path = evolution_dir / "rules.yaml"

    # ------------------------------------------------------------------
    # Feedback recording
    # ------------------------------------------------------------------

    def record_feedback(self, entry: FeedbackEntry) -> None:
        """Persist a feedback entry."""
        self.feedback_store.add(entry)

    # ------------------------------------------------------------------
    # Pattern analysis
    # ------------------------------------------------------------------

    def analyze_patterns(self) -> list[EvolutionRule]:
        """Derive EvolutionRules from accumulated feedback.

        Returns an empty list when fewer than MIN_SAMPLES entries exist.
        """
        entries = self.feedback_store.list_all()
        total = len(entries)
        if total < MIN_SAMPLES:
            return []

        rules: list[EvolutionRule] = []
        now = datetime.now(timezone.utc).isoformat()

        # ------------------------------------------------------------------
        # Pattern 1: Edit rate
        # ------------------------------------------------------------------
        edited_entries = [e for e in entries if e.user_action == "edited"]
        edit_count = len(edited_entries)

        if edit_count >= total * 0.5:
            # Tally which fields appear in edits
            field_counts: dict[str, int] = {}
            for e in edited_entries:
                for field in e.edits:
                    field_counts[field] = field_counts.get(field, 0) + 1

            for field, count in field_counts.items():
                freq = count / total
                if freq >= 0.30:
                    rules.append(
                        EvolutionRule(
                            rule_type="edit_pattern",
                            rule=(
                                f"Users frequently edit the {field} field "
                                f"({count}/{total} times, {freq:.0%})"
                            ),
                            confidence=min(freq, 1.0),
                            sample_size=total,
                            examples_good=[],
                            examples_bad=[],
                            learned_at=now,
                        )
                    )

        # ------------------------------------------------------------------
        # Pattern 2: Rejection rate
        # ------------------------------------------------------------------
        reject_count = sum(
            1 for e in entries if e.user_action in {"rejected", "regenerated"}
        )
        reject_rate = reject_count / total

        if reject_rate >= 0.30:
            rules.append(
                EvolutionRule(
                    rule_type="quality_issue",
                    rule=(
                        f"High rejection/regeneration rate detected: "
                        f"{reject_count}/{total} ({reject_rate:.0%}). "
                        "Output quality may need improvement."
                    ),
                    confidence=min(reject_rate, 1.0),
                    sample_size=total,
                    examples_good=[],
                    examples_bad=[],
                    learned_at=now,
                )
            )

        return rules

    # ------------------------------------------------------------------
    # Rule persistence
    # ------------------------------------------------------------------

    def save_rules(self, rules: list[EvolutionRule]) -> None:
        """Serialise rules to rules.yaml."""
        data = [r.model_dump() for r in rules]
        with self.rules_path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, sort_keys=False)

    def get_active_rules(self) -> list[EvolutionRule]:
        """Load rules.yaml and return only active rules."""
        if not self.rules_path.exists():
            return []
        with self.rules_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not raw:
            return []
        rules = [EvolutionRule(**item) for item in raw]
        return [r for r in rules if r.is_active]

    # ------------------------------------------------------------------
    # Prompt generation
    # ------------------------------------------------------------------

    def generate_prompt_suffix(self) -> str:
        """Build a Chinese-language prompt suffix from active rules.

        Returns an empty string when there are no active rules.
        """
        active = self.get_active_rules()
        if not active:
            return ""

        lines: list[str] = [
            f"【进化规则】共 {len(active)} 条活跃规则，请遵循以下学习经验：",
        ]
        for i, rule in enumerate(active, 1):
            lines.append(
                f"{i}. [{rule.rule_type}] {rule.rule} "
                f"（置信度: {rule.confidence:.0%}，样本数: {rule.sample_size}）"
            )

        return "\n".join(lines)
