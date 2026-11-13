"""H1-a (v0.1.64): three model parameters, each behind its own settings switch so the bench measures it off against on
(harness plan §4.3, `BENCH_ARSLAN_SETTINGS`). With every switch at its old value a request is byte-identical to the
one before H1-a (tests/llm/test_h1a_model_params.py holds main's bodies).

1. `tool_temperature`: a request that carries tools gets its vendor's temperature instead of 0.7.
2. `claude_effort`: Claude's `output_config.effort`, on the models that take it ("" sends none, as before).
3. `output_cap`: a raised opening output budget (and length-cut ceiling) where the model allows it.

Vendor documents read 2026-11-14 (links in the H1-a PR).

DELETE-BY: v0.1.65, each switch together with its losing value, once the bench has decided its default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Switches:
    tool_temperature: bool = False
    claude_effort: str = ""          # "" (not sent) | "high" | "medium"
    output_cap: bool = False


OFF = Switches()
EFFORTS = ("high", "medium")

#: Temperature for a request that carries tools; None leaves it out, so the endpoint's own default applies.
TOOL_TEMPERATURE: dict[str, float | None] = {
    # DeepSeek's parameter guide: 0.0 for coding / math. Its thinking mode (V4's default) ignores temperature.
    "deepseek": 0.0,
    # OpenAI's reasoning models take only the default (param_heal drops it after their 400); any other compatible
    # server has its own default for its model.
    "openai": None,
    # Gemini 3: temperature is deprecated and ignored ("remove these parameters"), a 400 in later generations.
    "gemini": None,
}


@dataclass(frozen=True)
class Cap:
    initial: int
    ceiling: int


# Claude 4.5 and later write up to 64K (4.6 and later 128K); OpenAI asks for at least 25K kept for reasoning and the
# answer, GPT-5 and the o-series write up to 100K or more; Gemini 2.5 and 3 up to 64K. Thinking shares the budget.
_CLAUDE_CAP = Cap(initial=32_768, ceiling=65_536)
_OPENAI_CAP = Cap(initial=32_768, ceiling=65_536)
GEMINI_MAX_OUTPUT = 65_536
_OPENAI_REASONING = re.compile(r"^(?:gpt-(\d+)|o[1-9])")
_GEMINI_VERSION = re.compile(r"gemini-(\d+)(?:\.(\d+))?")


def _claude_version(model: str) -> tuple[int, int] | None:
    from arslan.llm.providers.anthropic_provider import _claude_version as version
    return version(model.lower())


def takes_effort(model: str) -> bool:
    """Claude models with `output_config.effort`: Opus 4.5, and every Claude from 4.6 on."""
    version = _claude_version(model)
    return version is not None and (version >= (4, 6) or "opus-4-5" in model.lower())


def openai_reasoning(base_url: str, model: str) -> bool:
    """OpenAI's own host, a GPT-5-or-later or o-series model: `max_completion_tokens`, and 25K+ to work with."""
    if (base_url or "").rstrip("/") != "https://api.openai.com/v1":
        return False
    m = _OPENAI_REASONING.match(model.lower())
    return bool(m) and (m.group(1) is None or int(m.group(1)) >= 5)


def gemini_cap(model: str) -> int | None:
    m = _GEMINI_VERSION.search(model.lower())
    return GEMINI_MAX_OUTPUT if m and (int(m.group(1)), int(m.group(2) or 0)) >= (2, 5) else None


def configure(provider: Any, switches: Switches) -> None:
    """Give one provider its switches; the raised cap is set here, once, on the budget it opens with."""
    provider.switches = switches
    if not switches.output_cap:
        return
    name = provider.provider_name
    if name == "anthropic":
        version = _claude_version(provider.model)
        cap = _CLAUDE_CAP if version is not None and version >= (4, 5) else None
    elif name == "openai":
        cap = _OPENAI_CAP if openai_reasoning(provider.base_url, provider.model) else None
    else:
        cap = None
    if cap is not None:
        provider.max_tokens = max(provider.max_tokens, cap.initial)
        provider.output_ceiling = max(provider.output_ceiling, cap.ceiling)
