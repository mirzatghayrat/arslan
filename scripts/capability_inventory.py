"""Generate a source-derived capability map without starting Arslan or reading its DB."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from server.registry.seed_catalog import TOOLSETS
from server.services.capability_fitness import NATIVE_TOOL_CALLS

ROOT = Path(__file__).resolve().parents[1]


def executor_sources() -> dict[str, str]:
    sources = {}
    for path in sorted((ROOT / "server/registry").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for assignment in node.body:
                if (isinstance(assignment, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "key" for t in assignment.targets)
                    and isinstance(assignment.value, ast.Constant)
                    and isinstance(assignment.value.value, str)):
                    sources[node.name] = (assignment.value.value, path.relative_to(ROOT).as_posix())
    tree = ast.parse((ROOT / "server/registry/executors.py").read_text())
    assembly = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "EXECUTORS" for t in n.targets))
    names = [item.func.id for item in assembly.generators[0].iter.elts]
    return {sources[name][0]: sources[name][1] for name in names}


def render() -> str:
    executors = executor_sources()
    version = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
    lines = ["# Generated capability inventory", "", f"Desktop configuration version: `{version}`.", "",
             "Regenerate with `uv run python -m scripts.capability_inventory`. This is static",
             "source evidence, not an installed-account probe or proof of model quality.", "",
             "`wired` is a catalog declaration; `executor present` means an implementation",
             "is assembled into the built-in registry. Neither grants permission, configures",
             "credentials, proves external availability, nor guarantees live task success.", "",
             "## Seeded tool catalog", "",
             "| Toolset | Tool | Tier | Catalog state | Built-in executor source |",
             "| --- | --- | --- | --- | --- |"]
    seeded = set()
    for group in TOOLSETS:
        for key, _, tier, status in group["tools"]:
            seeded.add(key)
            source = executors.get(key)
            present = f"[{source}](../{source})" if source else "Not in built-in registry"
            lines.append(f"| {group['key']} | `{key}` | {tier} | {status} | {present} |")
    lines += ["", "## Additional assembled executors", "",
              "These are not seeded as spawn-equippable catalog tools. Host policy, workspace",
              "configuration, explicit opt-ins and confirmation still decide access. The",
              "enrolment executor deliberately refuses execution; the UI owns enrolment.", "",
              "| Tool | Source |", "| --- | --- |"]
    for key in sorted(executors.keys() - seeded):
        source = executors[key]
        lines.append(f"| `{key}` | [{source}](../{source}) |")
    lines += ["", "## Provider native-tool transport", "",
              "`supported` below means the adapter serializes tool schemas in tested request",
              "payloads. It does **not** certify every endpoint/model behind a compatible",
              "provider, or live credentials. Streaming-with-tools is a separate interface.", "",
              "| Provider key | Wire-contract declaration | Live quality acceptance |",
              "| --- | --- | --- |"]
    for provider, state in sorted(NATIVE_TOOL_CALLS.items()):
        lines.append(f"| `{provider}` | {state} | Not measured by this inventory |")
    lines += ["", "## Versioned external components", "",
              "The optional static browser preview is pinned by",
              "`server/resources/browser_runtime/package-lock.json` (npm integrity hashes).",
              "Python dependencies are pinned by `uv.lock`; desktop dependencies by Cargo",
              "and npm lockfiles. User-connected MCP servers and imported skills are separate",
              "trust decisions; see THIRD_PARTY_NOTICES.md and docs/RELIABILITY.md.", "",
              "## Source fingerprints", "", "| Source | SHA-256 |", "| --- | --- |"]
    paths = sorted(set(executors.values()) | {"server/registry/seed_catalog.py",
                    "server/services/capability_fitness.py", "server/resources/browser_runtime/package-lock.json"})
    for name in paths:
        lines.append(f"| `{name}` | `{hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}` |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(), end="")
