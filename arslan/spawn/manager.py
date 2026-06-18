"""SpawnManager — generates scaffold code for a SpawnBlueprint."""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from arslan.models import SpawnBlueprint


def _slug(name: str) -> str:
    """Filesystem/identifier-safe slug for a spawn name."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower() or "spawn"


# Map of (output_filename, template_filename) pairs.
# Templates without a .j2 suffix are copied directly (static files).
_TEMPLATES: list[tuple[str, str]] = [
    ("main.py", "main.py.j2"),
    ("agent.py", "agent.py.j2"),
    ("config.yaml", "config.yaml.j2"),
    ("requirements.txt", "requirements.txt.j2"),
    ("Dockerfile", "Dockerfile.j2"),
    ("docker-compose.yaml", "docker-compose.yaml.j2"),
    ("web/app.py", "web/app.py.j2"),
]

_STATIC_FILES: list[tuple[str, str]] = [
    ("web/templates/chat.html", "web/templates/chat.html"),
]

_SCAFFOLD_DIR = Path(__file__).parent / "scaffold"


class SpawnManager:
    """Generates and manages scaffold directories for spawns."""

    def __init__(self, spawns_dir: Path | None = None) -> None:
        self.spawns_dir: Path = spawns_dir or (Path.cwd() / "spawns")
        self.spawns_dir.mkdir(parents=True, exist_ok=True)

        self._env = Environment(
            loader=FileSystemLoader(str(_SCAFFOLD_DIR)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, blueprint: SpawnBlueprint) -> Path:
        """Render scaffold templates into a new spawn directory.

        Returns the path to the generated spawn directory.
        """
        req = blueprint.requirements
        spawn_name = req.spawn_name or "unnamed-spawn"
        spawn_path = self.spawns_dir / spawn_name

        # Create subdirs up front
        (spawn_path / "web" / "templates").mkdir(parents=True, exist_ok=True)

        ctx = self._build_context(blueprint)

        # Render Jinja2 templates
        for out_rel, tmpl_name in _TEMPLATES:
            tmpl = self._env.get_template(tmpl_name)
            rendered = tmpl.render(**ctx)
            (spawn_path / out_rel).write_text(rendered, encoding="utf-8")

        # Copy static files (replace {{ spawn_name }} placeholder in chat.html)
        for out_rel, src_rel in _STATIC_FILES:
            src = _SCAFFOLD_DIR / src_rel
            content = src.read_text(encoding="utf-8")
            # Replace the literal {{ spawn_name }} in the static HTML file
            content = content.replace("{{ spawn_name }}", spawn_name)
            (spawn_path / out_rel).write_text(content, encoding="utf-8")

        # Write metadata
        meta = {
            "name": spawn_name,
            "domain": req.domain.full_domain if req.domain else "",
            "template_used": blueprint.template_used or "",
            "generation_level": blueprint.generation_level,
        }
        (spawn_path / ".arslan-meta.yaml").write_text(
            yaml.dump(meta, allow_unicode=True),
            encoding="utf-8",
        )

        return spawn_path

    def generate_skillpack(self, blueprint: SpawnBlueprint) -> Path:
        """Render a lightweight *skill-pack* for a blueprint (P1, default path).

        Produces ``SKILL.md`` (frontmatter assembled programmatically for
        guaranteed-valid YAML, body rendered from a Jinja template) plus a
        cross-platform CLI under ``scripts/``. The result is designed to pass
        :func:`arslan.spawn.skillpack.validate_skillpack`. The heavy-runtime
        path lives in :meth:`generate` (P1.4, opt-in).
        """
        req = blueprint.requirements
        name = req.spawn_name or "unnamed-spawn"
        slug = _slug(name)
        pack_path = self.spawns_dir / name
        (pack_path / "scripts").mkdir(parents=True, exist_ok=True)

        ctx = self._build_skillpack_context(blueprint)

        frontmatter: dict = {
            "name": name,
            "description": ctx["description"],
            "version": "0.1.0",
            "authors": ["Arslan"],
        }
        if ctx["credentials"]:
            frontmatter["credentials"] = ctx["credentials"]

        body = self._env.get_template("skillpack/body.md.j2").render(**ctx)
        skill_md = (
            "---\n"
            + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)
            + "---\n\n"
            + body
        )
        (pack_path / "SKILL.md").write_text(skill_md, encoding="utf-8")

        cli = self._env.get_template("skillpack/cli.py.j2").render(name=name, slug=slug)
        (pack_path / "scripts" / f"{slug}_cli.py").write_text(cli, encoding="utf-8")

        meta = {
            "name": name,
            "domain": req.domain.full_domain if req.domain else "",
            "template_used": blueprint.template_used or "",
            "generation_level": blueprint.generation_level,
            "runtime": "skillpack",
        }
        (pack_path / ".arslan-meta.yaml").write_text(
            yaml.dump(meta, allow_unicode=True),
            encoding="utf-8",
        )

        return pack_path

    def list_spawns(self) -> list[dict]:
        """Return metadata for all spawns in spawns_dir."""
        results = []
        for meta_file in sorted(self.spawns_dir.glob("*/.arslan-meta.yaml")):
            try:
                data = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                continue
            data["path"] = str(meta_file.parent)
            results.append(data)
        return results

    def get_spawn_path(self, name: str) -> Path | None:
        """Return path to a spawn if it exists, else None."""
        candidate = self.spawns_dir / name
        if (candidate / ".arslan-meta.yaml").exists():
            return candidate
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_context(self, blueprint: SpawnBlueprint) -> dict:
        req = blueprint.requirements
        spawn_name = req.spawn_name or "unnamed-spawn"
        domain_str = req.domain.full_domain if req.domain else ""
        persona_role = req.persona.role if req.persona else ""
        persona_tone = req.persona.tone if req.persona else ""

        tools = [
            {"name": t.name, "description": t.description}
            for t in blueprint.tools
        ]

        return {
            "spawn_name": spawn_name,
            "domain": domain_str,
            "system_prompt": blueprint.system_prompt.replace('"', '\\"'),
            "persona_role": persona_role,
            "persona_tone": persona_tone,
            "web_port": 8080,
            "tools": tools,
        }

    def _build_skillpack_context(self, blueprint: SpawnBlueprint) -> dict:
        req = blueprint.requirements
        domain = req.domain.full_domain if req.domain else ""
        role = req.persona.role if req.persona else ""
        constraints = list(req.persona.constraints) if req.persona else []
        caps = list(req.capabilities)

        first_line = (blueprint.system_prompt or "").splitlines()
        description = role or (first_line[0] if first_line else (req.spawn_name or ""))

        anchor = domain or role or "该领域"
        trigger = f"当用户需求涉及「{anchor}」时激活"
        if caps:
            trigger += f"，核心能力：{'、'.join(caps)}。"
        else:
            trigger += "。"

        research_summary = (req.research_results or {}).get("summary", "")

        credentials: list[dict] = []
        for tool in blueprint.tools:
            cred = (tool.config or {}).get("credential")
            if cred:
                credentials.append({"name": cred, "required": False})

        return {
            "description": description,
            "trigger": trigger,
            "decision_rules": constraints,
            "research_summary": research_summary,
            "credentials": credentials,
        }
