"""Arslan — Template library: loading and searching official templates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

OFFICIAL_DIR = Path(__file__).parent / "official"


class TemplateConfig(BaseModel):
    """Configuration for a single official template."""

    name: str
    domain: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    workflow: list[dict[str, Any]] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=lambda: ["web"])
    path: str = ""

    @property
    def domain_tags(self) -> list[str]:
        """Split domain by '.' and return the parts as tags."""
        return self.domain.split(".")

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "TemplateConfig":
        """Load a TemplateConfig from a YAML file, setting path to the parent directory."""
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["path"] = str(yaml_path.parent)
        return cls(**data)


class TemplateLibrary:
    """Collection of templates with loading and search capabilities."""

    def __init__(self) -> None:
        self._templates: list[TemplateConfig] = []

    def load_official(self) -> None:
        """Load all official templates from the OFFICIAL_DIR directory tree."""
        for yaml_path in OFFICIAL_DIR.glob("**/template.yaml"):
            try:
                template = TemplateConfig.from_yaml(yaml_path)
                self._templates.append(template)
            except Exception:
                # Skip malformed templates
                pass

    def add(self, template: TemplateConfig) -> None:
        """Add a template to the library."""
        self._templates.append(template)

    def list_all(self) -> list[TemplateConfig]:
        """Return all loaded templates."""
        return list(self._templates)

    def search_by_domain(self, domain: str) -> list[TemplateConfig]:
        """Return templates whose domain exactly matches or starts with the given domain."""
        return [
            t for t in self._templates
            if t.domain == domain or t.domain.startswith(domain)
        ]

    def search(self, query: str) -> list[TemplateConfig]:
        """Case-insensitive substring search across name, description, and keywords."""
        q = query.lower()
        results = []
        for t in self._templates:
            if (
                q in t.name.lower()
                or q in t.description.lower()
                or any(q in kw.lower() for kw in t.keywords)
            ):
                results.append(t)
        return results
