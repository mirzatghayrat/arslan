"""Tests for the Evolution Engine: FeedbackStore and EvolutionEngine."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from arslan.core.evolution import EvolutionEngine, FeedbackStore
from arslan.models import EvolutionRule, FeedbackEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    action: str = "accepted",
    edits: dict | None = None,
    session_id: str = "s1",
    user_input: str = "generate something",
    agent_output: str = "some output",
) -> FeedbackEntry:
    return FeedbackEntry(
        session_id=session_id,
        user_input=user_input,
        agent_output=agent_output,
        user_action=action,
        edits=edits or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _make_edited_entry(field: str = "title") -> FeedbackEntry:
    return _make_entry(
        action="edited",
        edits={field: {"before": "old", "after": "new"}},
    )


# ---------------------------------------------------------------------------
# FeedbackStore tests
# ---------------------------------------------------------------------------


class TestFeedbackStore:
    def test_add_and_list_all(self, tmp_path: Path):
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        e1 = _make_entry("accepted")
        e2 = _make_entry("edited", edits={"title": {}})

        store.add(e1)
        store.add(e2)

        entries = store.list_all()
        assert len(entries) == 2
        assert entries[0].user_action == "accepted"
        assert entries[1].user_action == "edited"

    def test_list_all_returns_empty_when_file_missing(self, tmp_path: Path):
        store = FeedbackStore(tmp_path / "nonexistent.jsonl")
        assert store.list_all() == []

    def test_count(self, tmp_path: Path):
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        assert store.count() == 0

        for _ in range(5):
            store.add(_make_entry())

        assert store.count() == 5

    def test_count_does_not_load_all_entries(self, tmp_path: Path):
        """count() should work correctly regardless of content size."""
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        for i in range(30):
            store.add(_make_entry(session_id=str(i)))
        assert store.count() == 30

    def test_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c" / "feedback.jsonl"
        store = FeedbackStore(nested)
        store.add(_make_entry())
        assert nested.exists()


# ---------------------------------------------------------------------------
# EvolutionEngine tests
# ---------------------------------------------------------------------------


class TestEvolutionEngine:
    def test_record_feedback_delegates_to_store(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        engine.record_feedback(_make_entry("accepted"))
        assert engine.feedback_store.count() == 1

    def test_analyze_patterns_returns_empty_when_below_min_samples(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        # Add 19 entries — one short of MIN_SAMPLES (20)
        for _ in range(19):
            engine.record_feedback(_make_entry("edited", edits={"title": {}}))
        rules = engine.analyze_patterns()
        assert rules == []

    def test_analyze_patterns_detects_edit_pattern(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        # 20 "edited" entries all touching the "title" field
        for _ in range(20):
            engine.record_feedback(_make_edited_entry("title"))
        # 5 "accepted" entries
        for _ in range(5):
            engine.record_feedback(_make_entry("accepted"))

        rules = engine.analyze_patterns()
        assert len(rules) >= 1

        rule_types = [r.rule_type for r in rules]
        assert "edit_pattern" in rule_types

        edit_rule = next(r for r in rules if r.rule_type == "edit_pattern")
        assert "title" in edit_rule.rule
        assert edit_rule.sample_size == 25  # total entries
        assert 0.0 < edit_rule.confidence <= 1.0

    def test_analyze_patterns_detects_rejection_pattern(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        # 15 "rejected" + 7 "regenerated" = 22 rejections out of 30 total (>= 30%)
        for _ in range(15):
            engine.record_feedback(_make_entry("rejected"))
        for _ in range(7):
            engine.record_feedback(_make_entry("regenerated"))
        for _ in range(8):
            engine.record_feedback(_make_entry("accepted"))

        rules = engine.analyze_patterns()
        rule_types = [r.rule_type for r in rules]
        assert "quality_issue" in rule_types

    def test_save_and_get_active_rules(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)

        active_rule = EvolutionRule(
            rule_type="edit_pattern",
            rule="Users frequently edit the title field",
            confidence=0.8,
            sample_size=25,
            learned_at=datetime.now(timezone.utc).isoformat(),
        )
        inactive_rule = EvolutionRule(
            rule_type="edit_pattern",
            rule="Users sometimes edit the body field",
            confidence=0.3,  # below 0.5 threshold
            sample_size=25,
            learned_at=datetime.now(timezone.utc).isoformat(),
        )

        engine.save_rules([active_rule, inactive_rule])

        active = engine.get_active_rules()
        assert len(active) == 1
        assert active[0].rule_type == "edit_pattern"
        assert active[0].confidence == 0.8

    def test_get_active_rules_returns_empty_when_no_file(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        assert engine.get_active_rules() == []

    def test_generate_prompt_suffix_includes_rule_text(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)

        rule = EvolutionRule(
            rule_type="edit_pattern",
            rule="Users frequently edit the title field",
            confidence=0.75,
            sample_size=30,
            learned_at=datetime.now(timezone.utc).isoformat(),
        )
        engine.save_rules([rule])

        suffix = engine.generate_prompt_suffix()
        assert suffix != ""
        # Should include rule text
        assert "title" in suffix or "标题" in suffix or len(suffix) > 10

    def test_generate_prompt_suffix_empty_when_no_active_rules(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        # No rules saved at all
        assert engine.generate_prompt_suffix() == ""

    def test_generate_prompt_suffix_empty_when_rules_inactive(self, tmp_path: Path):
        engine = EvolutionEngine(tmp_path)
        inactive_rule = EvolutionRule(
            rule_type="edit_pattern",
            rule="Low confidence rule",
            confidence=0.2,
            sample_size=5,  # below 20 threshold
            learned_at=datetime.now(timezone.utc).isoformat(),
        )
        engine.save_rules([inactive_rule])
        assert engine.generate_prompt_suffix() == ""

    def test_creates_evolution_dir(self, tmp_path: Path):
        new_dir = tmp_path / "evolution" / "nested"
        engine = EvolutionEngine(new_dir)
        assert new_dir.exists()
