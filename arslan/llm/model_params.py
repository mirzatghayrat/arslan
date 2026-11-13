"""H1-a (v0.1.64): two Claude parameters, each behind its own settings switch so the bench measures it off against on
(harness plan §4.3, `BENCH_ARSLAN_SETTINGS`). With every switch at its old value a request is byte-identical to the
one before H1-a (tests/llm/test_h1a_model_params.py holds main's bodies).

1. `claude_effort`: Claude's `output_config.effort`, on the models that take it ("" sends none, as before).
2. `output_cap`: a raised opening output budget (and length-cut ceiling) for Claude 4.5 and later.

Vendor documents read 2026-11-14 (links in the H1-a PR).

DELETE-BY: each switch flips to on in the H1-a PR once its Claude measurement shows it working, or is removed
there; none outlives v0.1.65.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Switches:
    claude_effort: str = ""          # "" (not sent) | "high" | "medium"
    output_cap: bool = False


OFF = Switches()
EFFORTS = ("high", "medium")


@dataclass(frozen=True)
class Cap:
    initial: int
    ceiling: int


# Claude 4.5 and later write up to 64K (4.6 and later 128K). Thinking shares the budget.
_CLAUDE_CAP = Cap(initial=32_768, ceiling=65_536)


def _claude_version(model: str) -> tuple[int, int] | None:
    from arslan.llm.providers.anthropic_provider import _claude_version as version
    return version(model.lower())


def takes_effort(model: str) -> bool:
    """Claude models with `output_config.effort`: Opus 4.5, and every Claude from 4.6 on."""
    version = _claude_version(model)
    return version is not None and (version >= (4, 6) or "opus-4-5" in model.lower())


def configure(provider: Any, switches: Switches) -> None:
    """Give one provider its switches; the raised cap is set here, once, on the budget it opens with."""
    provider.switches = switches
    if not switches.output_cap or provider.provider_name != "anthropic":
        return
    version = _claude_version(provider.model)
    if version is not None and version >= (4, 5):
        provider.max_tokens = max(provider.max_tokens, _CLAUDE_CAP.initial)
        provider.output_ceiling = max(provider.output_ceiling, _CLAUDE_CAP.ceiling)
