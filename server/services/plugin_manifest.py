"""arslan.plugin.json — the third-party packaging contract (spec 2026-08-18 Part B).

The manifest is DATA. It declares how to launch an MCP server, which secret
SLOTS it needs (names + shapes, never values), which SKILL.md files ride
along, and whether to pre-tick the spawn-expose checkbox. Installing it never
executes anything: servers land through the locked add_server choke point and
connect stays a user action (= the server-level host consent), skills go
through the human-reviewed create_skill flow.

Validation is conservative in the mcp_suggest tradition: anything off-shape
returns (None, error) — never a partial pass-through. Unknown TOP-LEVEL keys
are ignored for forward compatibility; unknown shapes inside known keys are
errors.
"""
from __future__ import annotations

import json
import re

MAX_SERVERS = 10
MAX_SKILLS = 10
MAX_ENV_SLOTS = 20

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\- ]{1,80}$")
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
# Repo-relative file path: no traversal, no absolute, no query/fragment tricks.
_PATH_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,200}$")


def safe_repo_path(path: str) -> bool:
    return (bool(_PATH_RE.match(path or ""))
            and not path.startswith("/")
            and ".." not in path.split("/"))


def _err(msg: str) -> tuple[None, str]:
    return None, msg


def _validate_server(i: int, srv: object) -> tuple[dict | None, str | None]:
    if not isinstance(srv, dict):
        return _err(f"mcp_servers[{i}] must be an object")
    label = srv.get("label")
    if not isinstance(label, str) or not _NAME_RE.match(label):
        return _err(f"mcp_servers[{i}].label must be a short name")
    transport = srv.get("transport")
    if transport not in ("stdio", "http"):
        return _err(f"mcp_servers[{i}].transport must be stdio|http")
    out: dict = {"label": label, "transport": transport}
    if transport == "stdio":
        command = srv.get("command")
        if not isinstance(command, str) or not command.strip():
            return _err(f"mcp_servers[{i}].command required for stdio")
        args = srv.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return _err(f"mcp_servers[{i}].args must be a list of strings")
        out["command"], out["args"] = command, args
    else:
        url = srv.get("url")
        # https-only: the same doctrine as the open_external shell doorway.
        if not isinstance(url, str) or not url.startswith("https://"):
            return _err(f"mcp_servers[{i}].url must be an https:// URL")
        out["url"] = url
    env = srv.get("env", {})
    if not isinstance(env, dict) or len(env) > MAX_ENV_SLOTS:
        return _err(f"mcp_servers[{i}].env must be a small object of slots")
    slots: dict = {}
    for key, slot in env.items():
        if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
            return _err(f"mcp_servers[{i}].env has a non-env-shaped key")
        # A slot DECLARES a secret; a bare string smells like a shipped value.
        if not isinstance(slot, dict):
            return _err(f"mcp_servers[{i}].env.{key} must be a slot object, never a value")
        slots[key] = {"secret": bool(slot.get("secret", True)),
                      "description": str(slot.get("description", ""))[:200]}
    out["env"] = slots
    return out, None


def validate(raw: str) -> tuple[dict | None, str | None]:
    """(normalized_manifest, None) or (None, error)."""
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return _err("manifest is not valid JSON")
    if not isinstance(data, dict):
        return _err("manifest must be a JSON object")
    if data.get("schema_version") != 1:
        return _err("unsupported schema_version (expected 1)")
    name = data.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return _err("name must be a short string")
    version = data.get("version")
    if not isinstance(version, str) or not (0 < len(version) <= 40):
        return _err("version must be a short string")

    servers_in = data.get("mcp_servers", [])
    if not isinstance(servers_in, list) or len(servers_in) > MAX_SERVERS:
        return _err(f"mcp_servers must be a list of at most {MAX_SERVERS}")
    servers = []
    for i, srv in enumerate(servers_in):
        norm, err = _validate_server(i, srv)
        if err:
            return _err(err)
        servers.append(norm)

    skills_in = data.get("skills", [])
    if not isinstance(skills_in, list) or len(skills_in) > MAX_SKILLS:
        return _err(f"skills must be a list of at most {MAX_SKILLS}")
    for p in skills_in:
        if not isinstance(p, str) or not safe_repo_path(p) or not p.endswith(".md"):
            return _err(f"skills entry is not a safe repo-relative .md path: {p!r}")

    return {
        "schema_version": 1,
        "name": name,
        "version": version,
        "description": str(data.get("description", ""))[:500],
        "min_app_version": str(data.get("min_app_version", ""))[:40] or None,
        "mcp_servers": servers,
        "skills": list(skills_in),
        "suggest_spawn_expose": bool(data.get("suggest_spawn_expose", False)),
    }, None
