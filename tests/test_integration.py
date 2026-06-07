"""Integration tests: end-to-end spawn creation pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from arslan.core.dialogue import DialogueEngine
from arslan.core.evolution import EvolutionEngine
from arslan.models import (
    FeedbackEntry,
    SpawnBlueprint,
    ToolSpec,
)
from arslan.spawn.manager import SpawnManager
from arslan.spawn.quality import QualityGate
from arslan.templates.library import TemplateLibrary


class TestFullPipeline:
    """End-to-end tests covering dialogue → template match → spawn generation → quality gate → evolution."""

    def test_xiaohongshu_spawn_creation(self, tmp_path: Path) -> None:
        # ------------------------------------------------------------------ #
        # 1. Dialogue phase: collect requirements
        # ------------------------------------------------------------------ #
        engine = DialogueEngine()

        engine.process_user_input("我想做小红书美妆内容")   # domain
        engine.process_user_input("生成文案和追踪热点")      # capabilities
        engine.process_user_input("数据实测型美妆博主")      # persona
        engine.process_user_input("网页")                    # runtime
        engine.process_user_input("美美")                    # spawn_name

        assert engine.state.is_finished, "Dialogue should be finished after all inputs"
        requirements = engine.state.requirements
        assert requirements.spawn_name == "美美"
        assert requirements.domain is not None
        assert requirements.domain.category == "content-creator"

        # ------------------------------------------------------------------ #
        # 2. Template library: search by domain
        # ------------------------------------------------------------------ #
        library = TemplateLibrary()
        library.load_official()

        domain_str = requirements.domain.full_domain  # e.g. "content-creator.xiaohongshu"
        matches = library.search_by_domain(requirements.domain.category)
        assert len(matches) >= 1, f"Expected at least 1 template for domain '{requirements.domain.category}'"

        # ------------------------------------------------------------------ #
        # 3. Build blueprint
        # ------------------------------------------------------------------ #
        tools = [
            ToolSpec(
                name="content-generator",
                description="生成小红书风格文案",
                tags=["content", "writing"],
                input_schema={"prompt": {"type": "string"}},
                output_schema={"text": {"type": "string"}},
            ),
            ToolSpec(
                name="trend-tracker",
                description="追踪当前热点话题",
                tags=["search", "trends"],
                input_schema={"keyword": {"type": "string"}},
                output_schema={"trends": {"type": "array"}},
            ),
        ]

        blueprint = SpawnBlueprint(
            requirements=requirements,
            tools=tools,
            system_prompt="你是一位专业的小红书美妆博主，擅长生成爆款文案并追踪美妆热点。",
            workflow_steps=[
                {"step": "research", "action": "trend-tracker"},
                {"step": "generate", "action": "content-generator"},
            ],
            template_used=matches[0].domain if matches else None,
        )

        # ------------------------------------------------------------------ #
        # 4. Generate spawn
        # ------------------------------------------------------------------ #
        manager = SpawnManager(spawns_dir=tmp_path)
        spawn_path = manager.generate(blueprint)
        assert spawn_path.exists(), "Spawn directory should be created"

        # ------------------------------------------------------------------ #
        # 5. Quality gate
        # ------------------------------------------------------------------ #
        gate = QualityGate(spawn_path)
        results = gate.run_all()
        failed = [r for r in results if not r.passed]
        assert not failed, f"Quality checks failed: {[(r.name, r.message) for r in failed]}"

        # ------------------------------------------------------------------ #
        # 6. Evolution: record feedback and analyze patterns
        # ------------------------------------------------------------------ #
        evolution_dir = tmp_path / "evolution"
        evo = EvolutionEngine(evolution_dir=evolution_dir)

        now = datetime.now(timezone.utc).isoformat()

        # 18 edited entries (with title edits)
        for i in range(18):
            evo.record_feedback(
                FeedbackEntry(
                    session_id=f"session-{i:03d}",
                    user_input="生成小红书文案",
                    agent_output=f"文案内容 {i}",
                    user_action="edited",
                    edits={"title": f"用户修改标题 {i}"},
                    timestamp=now,
                )
            )

        # 7 accepted entries
        for i in range(7):
            evo.record_feedback(
                FeedbackEntry(
                    session_id=f"session-acc-{i:03d}",
                    user_input="生成小红书文案",
                    agent_output=f"文案内容 acc-{i}",
                    user_action="accepted",
                    edits={},
                    timestamp=now,
                )
            )

        rules = evo.analyze_patterns()
        assert len(rules) >= 1, "Expected at least 1 evolution rule after 25 feedback entries"

        # ------------------------------------------------------------------ #
        # 7. Verify list_spawns returns exactly 1 entry named "美美"
        # ------------------------------------------------------------------ #
        spawns = manager.list_spawns()
        assert len(spawns) == 1, f"Expected 1 spawn, got {len(spawns)}"
        assert spawns[0]["name"] == "美美", f"Expected spawn name '美美', got '{spawns[0]['name']}'"

    def test_translator_spawn_creation(self, tmp_path: Path) -> None:
        # ------------------------------------------------------------------ #
        # 1. Dialogue phase
        # ------------------------------------------------------------------ #
        engine = DialogueEngine()

        engine.process_user_input("翻译助手")   # domain
        engine.process_user_input("问答交互")    # capabilities
        engine.process_user_input("专业翻译")    # persona
        engine.process_user_input("web")         # runtime
        engine.process_user_input("译译")        # spawn_name

        assert engine.state.is_finished, "Dialogue should be finished after all inputs"
        requirements = engine.state.requirements
        assert requirements.spawn_name == "译译"

        # ------------------------------------------------------------------ #
        # 2. Build blueprint
        # ------------------------------------------------------------------ #
        tools = [
            ToolSpec(
                name="translator",
                description="翻译文本",
                tags=["translation", "language"],
                input_schema={"text": {"type": "string"}, "target_lang": {"type": "string"}},
                output_schema={"translated": {"type": "string"}},
            ),
        ]

        blueprint = SpawnBlueprint(
            requirements=requirements,
            tools=tools,
            system_prompt="你是一位专业翻译助手，擅长多语言翻译。",
            workflow_steps=[
                {"step": "translate", "action": "translator"},
            ],
            template_used=None,
        )

        # ------------------------------------------------------------------ #
        # 3. Generate spawn
        # ------------------------------------------------------------------ #
        manager = SpawnManager(spawns_dir=tmp_path)
        spawn_path = manager.generate(blueprint)
        assert spawn_path.exists(), "Spawn directory should be created"

        # ------------------------------------------------------------------ #
        # 4. Quality gate — all checks must pass
        # ------------------------------------------------------------------ #
        gate = QualityGate(spawn_path)
        results = gate.run_all()
        failed = [r for r in results if not r.passed]
        assert not failed, f"Quality checks failed: {[(r.name, r.message) for r in failed]}"
