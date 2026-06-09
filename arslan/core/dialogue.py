"""Arslan — Dialogue Engine: walks the requirement tree collecting structured requirements."""
from __future__ import annotations

# DEPRECATED (2026-06-10): The step-by-step build wizard is superseded by natural-language
# spawn creation (server/services/spawn_drafter.py + POST /api/v1/spawns). This module and
# server/ws/build.py are retained for now (deprecate-not-delete) and slated for removal in a
# dedicated dead-code audit. No new callers should use it.

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from arslan.models import DomainInfo, PersonaSpec, RuntimeSpec, SpawnRequirements

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_ORDER = ["domain", "capabilities", "persona", "runtime", "spawn_name"]

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "requirement_tree.yaml"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Question:
    """A single dialogue question presented to the user."""

    node_id: str
    text: str
    options: list[str] | None = None
    multi_select: bool = False
    hint: str = ""


@dataclass
class DialogueState:
    """Mutable state that tracks progress through the requirement tree."""

    current_node: str = "domain"
    current_index: int = 0
    requirements: SpawnRequirements = field(default_factory=SpawnRequirements)
    _filled: set[str] = field(default_factory=set)

    @property
    def is_finished(self) -> bool:
        """True when all required requirements have been collected."""
        return self.requirements.is_complete

    def set_field(self, node_id: str, value: Any) -> None:
        """Populate the requirement field corresponding to *node_id*."""
        if node_id == "domain":
            self.requirements.domain = DomainInfo(**value)
        elif node_id == "capabilities":
            self.requirements.capabilities = value if isinstance(value, list) else [value]
        elif node_id == "persona":
            self.requirements.persona = PersonaSpec(**value)
        elif node_id == "runtime":
            self.requirements.runtime = RuntimeSpec(**value)
        elif node_id == "spawn_name":
            self.requirements.spawn_name = value
        self._filled.add(node_id)

    def advance(self) -> None:
        """Move *current_node* to the next unfilled node in NODE_ORDER."""
        for node_id in NODE_ORDER:
            if node_id not in self._filled:
                self.current_node = node_id
                self.current_index = NODE_ORDER.index(node_id)
                return
        self.current_node = "done"
        self.current_index = len(NODE_ORDER)


# ---------------------------------------------------------------------------
# Dialogue Engine
# ---------------------------------------------------------------------------


class DialogueEngine:
    """Drives a multi-turn conversation to collect spawn requirements."""

    def __init__(self) -> None:
        self.state = DialogueState()
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            self._tree: dict[str, Any] = yaml.safe_load(fh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_next_question(self) -> Question | None:
        """Return the question for the current node, or None if finished."""
        if self.state.is_finished or self.state.current_node == "done":
            return None

        node_id = self.state.current_node

        if node_id == "domain":
            node = self._tree["nodes"]["domain"]
            options = [
                f"{cat['value']} — {cat['label']}"
                for cat in node["categories"]
            ]
            return Question(
                node_id="domain",
                text="你想打造什么领域的 AI 分身？",
                options=options,
            )

        if node_id == "capabilities":
            node = self._tree["nodes"]["capabilities"]
            options = [
                f"{opt['value']} — {opt['label']}"
                for opt in node["options"]
            ]
            return Question(
                node_id="capabilities",
                text="你需要这个分身具备哪些能力？（可多选）",
                options=options,
                multi_select=True,
            )

        if node_id == "persona":
            return Question(
                node_id="persona",
                text="你希望这个分身是什么角色和风格？",
                hint="例如：资深美妆博主，亲切友好型",
            )

        if node_id == "runtime":
            return Question(
                node_id="runtime",
                text="你打算怎么使用它？",
                options=["网页对话", "命令行"],
            )

        if node_id == "spawn_name":
            return Question(
                node_id="spawn_name",
                text="给你的分身起个名字吧？",
            )

        return None

    def process_user_input(self, user_input: str) -> None:
        """Extract structured data from *user_input* for the current node."""
        node_id = self.state.current_node
        text = user_input.strip()

        if node_id == "domain":
            self.state.set_field("domain", self._extract_domain(text))

        elif node_id == "capabilities":
            self.state.set_field("capabilities", self._extract_capabilities(text))

        elif node_id == "persona":
            self.state.set_field("persona", self._extract_persona(text))

        elif node_id == "runtime":
            self.state.set_field("runtime", self._extract_runtime(text))

        elif node_id == "spawn_name":
            self.state.set_field("spawn_name", text)

        self.state.advance()

    def get_summary(self) -> str:
        """Return a human-readable summary of collected requirements."""
        req = self.state.requirements
        lines: list[str] = ["=== 分身需求摘要 ==="]

        if req.spawn_name:
            lines.append(f"名称: {req.spawn_name}")

        if req.domain:
            lines.append(f"领域: {req.domain.full_domain}")

        if req.capabilities:
            lines.append(f"能力: {', '.join(req.capabilities)}")

        if req.persona:
            lines.append(f"角色: {req.persona.role}")
            if req.persona.tone:
                lines.append(f"风格: {req.persona.tone}")

        if req.runtime:
            lines.append(f"平台: {req.runtime.platform} / 触发: {req.runtime.trigger}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    _DOMAIN_KEYWORD_MAP: dict[str, tuple[str, str | None]] = {
        "小红书": ("content-creator", "xiaohongshu"),
        "抖音": ("content-creator", "douyin"),
        "微信": ("content-creator", "wechat-mp"),
        "博客": ("content-creator", "blog"),
        "blog": ("content-creator", "blog"),
        "内容创作": ("content-creator", None),
        "content": ("content-creator", None),
        "客服": ("customer-service", None),
        "support": ("customer-service", None),
        "数据分析": ("data-analysis", None),
        "data": ("data-analysis", None),
        "翻译": ("personal-assistant", "translator"),
        "个人助手": ("personal-assistant", None),
        "assistant": ("personal-assistant", None),
        "微博": ("content-creator", "weibo"),
        "instagram": ("content-creator", "instagram"),
        "youtube": ("content-creator", "youtube"),
    }

    _CAPABILITIES_KEYWORD_MAP: dict[str, str] = {
        "采集": "info-gathering",
        "爬": "info-gathering",
        "搜索": "info-gathering",
        "search": "info-gathering",
        "生成": "content-generation",
        "写": "content-generation",
        "文案": "content-generation",
        "内容": "content-generation",
        "问答": "qa-interaction",
        "对话": "qa-interaction",
        "chat": "qa-interaction",
        "定时": "scheduled-tasks",
        "schedule": "scheduled-tasks",
        "分析": "data-processing",
        "analysis": "data-processing",
    }

    _TONE_KEYWORD_MAP: dict[str, str] = {
        "数据": "数据实测型",
        "实测": "数据实测型",
        "亲切": "亲切友好型",
        "友好": "亲切友好型",
        "专业": "专业严谨型",
        "严谨": "专业严谨型",
        "幽默": "幽默风趣型",
        "风趣": "幽默风趣型",
    }

    def _extract_domain(self, text: str) -> dict[str, Any]:
        """Map keyword text to a domain dict."""
        for keyword, (category, subcategory) in self._DOMAIN_KEYWORD_MAP.items():
            if keyword.lower() in text.lower():
                return {"category": category, "subcategory": subcategory}
        return {"category": "other", "subcategory": None}

    def _extract_capabilities(self, text: str) -> list[str]:
        """Extract one or more capability values from free text."""
        found: list[str] = []
        seen: set[str] = set()
        for keyword, capability in self._CAPABILITIES_KEYWORD_MAP.items():
            if keyword.lower() in text.lower() and capability not in seen:
                found.append(capability)
                seen.add(capability)
        return found if found else ["content-generation"]

    def _extract_persona(self, text: str) -> dict[str, Any]:
        """Build a PersonaSpec dict from free text."""
        tone = ""
        for keyword, tone_value in self._TONE_KEYWORD_MAP.items():
            if keyword in text:
                tone = tone_value
                break
        return {"role": text, "tone": tone}

    def _extract_runtime(self, text: str) -> dict[str, Any]:
        """Determine platform from keyword hints."""
        lower = text.lower()
        platform = "web" if any(k in lower for k in ("网页", "web", "browser")) else "cli"
        return {"platform": platform, "trigger": "user"}
