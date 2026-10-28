"""The SKILL.md format: YAML frontmatter plus a Markdown body that carries ``## Trigger`` and
``## Decision Rules`` (the legacy Chinese decision heading is accepted too).

C9 (v0.1.63): moved here from ``arslan/spawn/skillpack.py``. The seeder reads skills through it.
The directory-level validator that only expert spawns used went with the rest of ``arslan/spawn``
in C7 (v0.1.63).
"""
from __future__ import annotations

import yaml
from pydantic import BaseModel, Field

#: Markdown sections every skill-pack body must carry (spec §4.2).
REQUIRED_SECTIONS = ("Trigger", "Decision Rules")


def has_body_section(body: str, title: str) -> bool:
    """Match canonical headings while preserving legacy Chinese skill packs."""
    aliases = {"Decision Rules", "决策规则"} if title in {"Decision Rules", "决策规则"} else {title}
    return any(
        line.strip().startswith("#") and line.strip().lstrip("#").strip() in aliases
        for line in body.splitlines()
    )


class CredentialSpec(BaseModel):
    """A credential the skill-pack declares it may need.

    Declarative only — never holds a plaintext secret. Actual values are
    resolved at runtime from CLI flag / .env / environment, and encrypted at
    rest via the server's crypto layer.
    """

    name: str
    required: bool = False
    description: str = ""
    storage: str = ""


class SkillPack(BaseModel):
    """Parsed representation of a ``SKILL.md`` frontmatter + body."""

    name: str
    description: str
    version: str
    authors: list[str] = Field(default_factory=list)
    credentials: list[CredentialSpec] = Field(default_factory=list)
    body: str = ""

    @classmethod
    def from_skill_md(cls, text: str) -> SkillPack:
        """Parse a ``SKILL.md`` string into a :class:`SkillPack`.

        Raises ``ValueError`` when the YAML frontmatter block is missing or
        not terminated.
        """
        frontmatter, body = _split_frontmatter(text)
        data = yaml.safe_load(frontmatter) or {}
        data["body"] = body
        return cls(**data)

    def has_section(self, title: str) -> bool:
        """True when the body contains a Markdown heading equal to ``title``."""
        return has_body_section(self.body, title)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a frontmatter document into ``(yaml_str, body_str)``."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        raise ValueError("SKILL.md missing YAML frontmatter (expected leading '---')")
    after_open = stripped[len("---"):].lstrip("\n")
    parts = after_open.split("\n---", 1)
    if len(parts) != 2:
        raise ValueError("SKILL.md frontmatter not terminated with '---'")
    frontmatter, body = parts
    return frontmatter, body.lstrip("\n")
