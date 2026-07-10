"""Prompts for the synthetic cold-start corpus generator (S2 E6).

Two sources, two prompts:
  - DOMAIN  : representative tasks built from the spawn's persona (domain +
              role + capabilities). No source run.
  - VARIANT : rewrites of a real task — same task TYPE, changed
              parameters/objects/constraints — so the synthetic pair still
              exercises the same skill the real run did.

Both prompts hard-constrain the model to tasks completable within the
replay-safe builtin toolset (no MCP / external-write needs) and to <=500 chars
each, and demand a bare JSON object {"tasks": [...]} so parse_json_object can
lift it out.
"""
from __future__ import annotations

MAX_TASK_LEN = 500

SYNTH_DOMAIN_SYSTEM = (
    "You generate synthetic EVALUATION tasks for an AI agent, used to measure whether a "
    "candidate instruction beats the baseline. Produce realistic, self-contained tasks that a "
    "user of this agent would actually ask. Each task MUST be completable using ONLY this "
    "replay-safe toolset: {tools}. Do NOT invent tasks that need external writes, email, "
    "databases, MCP servers, file uploads, or any tool outside that set. Each task <= "
    f"{MAX_TASK_LEN} characters, one self-contained request, no numbering, no commentary. "
    'Output ONLY a JSON object: {{"tasks": ["<task 1>", "<task 2>", ...]}}.'
)

SYNTH_VARIANT_SYSTEM = (
    "You rewrite an AI agent's real task into fresh VARIANTS for evaluation. Keep the task "
    "TYPE and difficulty identical, but change the concrete parameters, objects, numbers, or "
    "constraints so it is a genuinely different instance (never a paraphrase). Each variant "
    "MUST be completable using ONLY this replay-safe toolset: {tools}. No external writes, "
    "email, databases, MCP servers, or tools outside that set. Each variant <= "
    f"{MAX_TASK_LEN} characters, self-contained, no numbering, no commentary. "
    'Output ONLY a JSON object: {{"tasks": ["<variant 1>", "<variant 2>", ...]}}.'
)


def _tools_line(safe_tools) -> str:
    return ", ".join(sorted(safe_tools)) or "(none)"


def build_domain_system(safe_tools) -> str:
    return SYNTH_DOMAIN_SYSTEM.format(tools=_tools_line(safe_tools))


def build_variant_system(safe_tools) -> str:
    return SYNTH_VARIANT_SYSTEM.format(tools=_tools_line(safe_tools))


def build_domain_prompt(*, name: str, domain: str, persona_role: str,
                        capabilities: str, n: int) -> str:
    return (
        f"Agent: {name}\n"
        f"Domain: {domain}\n"
        f"Role: {persona_role}\n"
        f"Capabilities: {capabilities}\n\n"
        f"Generate {n} representative evaluation task(s) this agent should handle well."
    )


def build_variant_prompt(*, name: str, source_task: str, n: int) -> str:
    return (
        f"Agent: {name}\n\n"
        f"Real task to create variants of:\n{source_task}\n\n"
        f"Produce {n} distinct variant(s) of the SAME type."
    )
