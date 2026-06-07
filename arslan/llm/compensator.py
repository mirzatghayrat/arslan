"""Quality Compensator — adjusts prompts and parsing based on model capability profile."""
from __future__ import annotations

import json
import re

from arslan.models import CapabilityProfile

# Capabilities considered for compensation (creative is excluded — not actionable here)
_COMPENSATED_CAPS = ("reasoning", "tool_use", "chinese", "instruction")

# Below this score (strictly less than), compensation is triggered
WEAK_THRESHOLD = 3


class QualityCompensator:
    """Applies prompt-engineering compensations for models with weak capability scores.

    For each capability that scores strictly below WEAK_THRESHOLD (3), the
    compensator activates a corresponding strategy and mutates prompts
    accordingly.
    """

    def __init__(self, profile: CapabilityProfile) -> None:
        self.profile = profile
        weak = set(profile.weak_capabilities(WEAK_THRESHOLD))
        self._strategies: dict[str, bool] = {
            cap: True for cap in _COMPENSATED_CAPS if cap in weak
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_strategies(self) -> dict[str, bool]:
        """Return only the active (True) compensation strategies."""
        return dict(self._strategies)

    def compensate_prompt(self, prompt: str, task_type: str = "general") -> str:
        """Return a (potentially augmented) version of *prompt*.

        If no strategies are active the original prompt is returned unchanged.
        When strategies are active the relevant augmentations are applied.
        """
        if not self._strategies:
            return prompt

        result = prompt

        # 1. Task-specific augmentations
        if task_type == "reasoning" and self._strategies.get("reasoning"):
            result = self._add_cot_suffix(result)

        elif task_type == "tool_use" and self._strategies.get("tool_use"):
            result = self._add_react_prefix(result)

        elif task_type == "chinese" and self._strategies.get("chinese"):
            result = self._add_chinese_hint(result)

        # 2. Instruction-following wrapper (applied last, regardless of task_type)
        if self._strategies.get("instruction"):
            result = self._wrap_with_emphasis(result)

        return result

    def parse_react_output(self, text: str) -> dict | None:
        """Parse ReAct-format output produced by a weak tool-use model.

        Looks for ``工具[：:]`` and ``参数[：:]`` patterns (supporting both
        full-width ： and ASCII : separators).

        Returns
        -------
        dict | None
            ``{"tool": <name>, "params": <dict or {"raw": <str>}>}``
            or ``None`` when no tool marker is found.
        """
        tool_match = re.search(r"工具[：:]\s*(.+)", text)
        if not tool_match:
            return None

        tool_name = tool_match.group(1).strip()

        params_match = re.search(r"参数[：:]\s*(.+)", text, re.DOTALL)
        if params_match:
            raw_params = params_match.group(1).strip()
            try:
                params: dict = json.loads(raw_params)
            except (json.JSONDecodeError, ValueError):
                params = {"raw": raw_params}
        else:
            params = {}

        return {"tool": tool_name, "params": params}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_cot_suffix(prompt: str) -> str:
        """Append a chain-of-thought instruction in both Chinese and English."""
        return f"{prompt}\n请逐步思考，step by step."

    @staticmethod
    def _add_react_prefix(prompt: str) -> str:
        """Prepend a ReAct-style format reminder."""
        react_header = (
            "请按照以下格式回答 (Thought/Tool/Params format):\n"
            "思考：<your reasoning here>\n"
            "工具：<tool name>\n"
            "参数：<tool parameters as JSON>\n\n"
        )
        return react_header + prompt

    @staticmethod
    def _add_chinese_hint(prompt: str) -> str:
        """Append a hint to think in English internally, then output in Chinese."""
        hint = (
            "\n[Hint: Think through this problem in English first, "
            "then output your final answer in Chinese / "
            "提示：请先用英文思考，再用中文输出答案。]"
        )
        return prompt + hint

    @staticmethod
    def _wrap_with_emphasis(prompt: str) -> str:
        """Wrap the prompt in emphasis markers to reinforce instruction-following."""
        return f"### IMPORTANT INSTRUCTIONS — follow exactly ###\n{prompt}\n### END OF INSTRUCTIONS ###"
