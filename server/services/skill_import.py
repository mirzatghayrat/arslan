"""Faithful SKILL.md importer (P3).

Unlike Tool-Hub's "Add as Skill" (LLM-distills/rewrites a repo into house style), this imports
standard Agent-Skills-format skills VERBATIM: parse frontmatter + body → registry, with the
license gate the project treats as a red line, plus bundled `scripts/*.py` stored for the
P1 sandbox (run_python {"skill_script": "<key>/<file>"}).

Safety/discipline:
  • Fixed host api.github.com only (same as github_eval — not an SSRF surface).
  • LICENSE GATE enforced SERVER-SIDE on both scan and import: repo license must be in the
    permissive allowlist; no license / copyleft / unknown → not importable. 绝不捆绑未核实。
  • Attribution prepended into the imported body (source repo · license · date).
  • Scripts: .py only, per-file and per-skill caps, stored under data_dir/skill_scripts/<key>/;
    they execute ONLY inside the P1 sandbox (network-denied, env-scrubbed, tmpdir).
  • Import refuses keys that already exist (no silent overwrite of library content).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
import yaml
from sqlalchemy import select

import os
from pathlib import Path

from server.db import session as db_session
from server.db.models import SkillPack
from server.services import github_eval
from server.services.skill_forge import MAX_SKILL_BYTES

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 15.0
_MAX_SKILLS_PER_SCAN = 25
_MAX_SCRIPTS = 10
_MAX_SCRIPT_BYTES = 100_000
# References mirror the script caps exactly: a malicious skill must not write unbounded data.
_MAX_REFERENCES = 10
_MAX_REFERENCE_BYTES = 100_000

# Permissive licenses we may redistribute with attribution. Copyleft and "NONE" are refused.
ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
                    "Unlicense", "CC0-1.0", "0BSD"}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _data_dir() -> Path:
    # Same convention as code_sandbox: resolve() so cwd changes never bite.
    return Path(os.environ.get("ARSLAN_DATA_DIR", "data")).resolve()


def parse_skill_md(raw: str) -> dict | None:
    """Parse a standard SKILL.md: YAML frontmatter (needs name+description) + markdown body."""
    m = _FRONTMATTER_RE.match(raw or "")
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        return None
    body = raw[m.end():].strip()
    if not body:
        return None
    key = re.sub(r"[^a-z0-9]+", "-", str(meta["name"]).lower()).strip("-")[:60]
    return {"key": key, "name": str(meta["name"])[:100],
            "description": str(meta["description"])[:300], "body": body}


def _license_gate(spdx: str | None) -> str | None:
    """None when importable; otherwise the human-readable refusal reason."""
    if not spdx or spdx == "NOASSERTION":
        return "no license — cannot bundle unverified content"
    if spdx not in ALLOWED_LICENSES:
        return f"license {spdx} is not in the permissive allowlist"
    return None


async def _get(path: str, *, raw: bool = False) -> httpx.Response:
    token = await github_eval._token()
    headers = github_eval._headers(token)
    if raw:
        headers["Accept"] = "application/vnd.github.raw"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.get(f"{_GITHUB_API}{path}", headers=headers)


async def _tree_paths(owner: str, repo: str) -> list[str]:
    """All blob paths in the default branch (recursive tree)."""
    r = await _get(f"/repos/{owner}/{repo}")
    r.raise_for_status()
    branch = r.json().get("default_branch") or "main"
    r = await _get(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    if r.status_code == 403 and "rate limit" in (r.text or "").lower():
        raise ValueError("GitHub rate-limited — set GITHUB_TOKEN in Settings")
    r.raise_for_status()
    return [e["path"] for e in r.json().get("tree") or [] if e.get("type") == "blob"]


async def _fetch_raw(owner: str, repo: str, path: str) -> str:
    r = await _get(f"/repos/{owner}/{repo}/contents/{path}", raw=True)
    r.raise_for_status()
    return r.text or ""


def _scripts_for(skill_md_path: str, all_paths: list[str]) -> list[str]:
    """Bundled python scripts living beside this SKILL.md (scripts/ subdir, .py only)."""
    base = skill_md_path.rsplit("/", 1)[0] if "/" in skill_md_path else ""
    prefix = f"{base}/scripts/" if base else "scripts/"
    return sorted(p for p in all_paths if p.startswith(prefix) and p.endswith(".py"))


def _references_for(skill_md_path: str, all_paths: list[str]) -> list[str]:
    """Bundled text references living beside this SKILL.md (references/ subdir, .md/.txt only).
    startswith(prefix) also picks up nested references/**/… paths; storage flattens to basename."""
    base = skill_md_path.rsplit("/", 1)[0] if "/" in skill_md_path else ""
    prefix = f"{base}/references/" if base else "references/"
    return sorted(p for p in all_paths if p.startswith(prefix) and p.endswith((".md", ".txt")))


async def scan_skills(ref: str, subpath: str = "") -> dict:
    """Find standard SKILL.md skills in a repo and report per-skill importability.
    The license gate applies to the WHOLE scan (repo-level license, like github_eval)."""
    parsed = github_eval.parse_repo_ref(ref)
    if parsed is None:
        raise ValueError("not a GitHub repo reference (owner/name)")
    owner, repo = parsed
    meta = await github_eval.fetch_repo(owner, repo)
    license_block = _license_gate(meta["license"])

    paths = await _tree_paths(owner, repo)
    sub = (subpath or "").strip("/")
    skill_paths = [p for p in paths if p.endswith("SKILL.md")
                   and (not sub or p.startswith(sub + "/") or p == f"{sub}/SKILL.md")]
    skill_paths = skill_paths[:_MAX_SKILLS_PER_SCAN]

    async with db_session.AsyncSessionLocal() as db:
        existing = {k for (k,) in (await db.execute(select(SkillPack.key))).all()}

    skills = []
    for p in skill_paths:
        raw = await _fetch_raw(owner, repo, p)
        info = parse_skill_md(raw)
        entry: dict = {"path": p, "scripts": _scripts_for(p, paths),
                       "references": _references_for(p, paths)}
        if info is None:
            entry.update(importable=False, reason="not a valid SKILL.md (frontmatter name+description required)")
        else:
            entry.update(key=info["key"], name=info["name"], description=info["description"],
                         body_bytes=len(info["body"].encode("utf-8")))
            if license_block:
                entry.update(importable=False, reason=license_block)
            elif info["key"] in existing:
                entry.update(importable=False, reason="already in the library")
            elif entry["body_bytes"] > MAX_SKILL_BYTES:
                entry.update(importable=False,
                             reason=f"body {entry['body_bytes']}B exceeds the {MAX_SKILL_BYTES}B limit")
            else:
                entry.update(importable=True, reason=None)
        skills.append(entry)
    return {"repo": {"full_name": meta["full_name"], "html_url": meta["html_url"],
                     "license": meta["license"], "stars": meta["stars"]},
            "license_ok": license_block is None, "license_note": license_block,
            "skills": skills}


async def import_skill(ref: str, path: str) -> dict:
    """Import ONE skill faithfully. Re-validates everything server-side (never trust the UI)."""
    parsed = github_eval.parse_repo_ref(ref)
    if parsed is None:
        raise ValueError("not a GitHub repo reference")
    owner, repo = parsed
    meta = await github_eval.fetch_repo(owner, repo)
    block = _license_gate(meta["license"])
    if block:
        raise ValueError(block)

    raw = await _fetch_raw(owner, repo, path)
    info = parse_skill_md(raw)
    if info is None:
        raise ValueError("not a valid SKILL.md (frontmatter name+description required)")
    if len(info["body"].encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BYTES}B limit")

    key = info["key"]
    async with db_session.AsyncSessionLocal() as db:
        if await db.get(SkillPack, key) is not None:
            raise ValueError(f"skill '{key}' already exists in the library")

    # bundled scripts → data_dir/skill_scripts/<key>/ (flat names, .py only, capped)
    paths = await _tree_paths(owner, repo)
    script_paths = _scripts_for(path, paths)[:_MAX_SCRIPTS]
    stored: list[str] = []
    if script_paths:
        script_dir = _data_dir() / "skill_scripts" / key
        script_dir.mkdir(parents=True, exist_ok=True)
        for sp in script_paths:
            content = await _fetch_raw(owner, repo, sp)
            if len(content.encode("utf-8")) > _MAX_SCRIPT_BYTES:
                continue
            fname = sp.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.py", fname):
                continue
            (script_dir / fname).write_text(content, encoding="utf-8")
            stored.append(fname)

    # bundled references → data_dir/skill_scripts/<key>/references/ (flat basenames,
    # .md/.txt only, same per-file + per-skill caps as scripts; PC-3 mounts these read-only).
    ref_paths = _references_for(path, paths)[:_MAX_REFERENCES]
    stored_refs: list[str] = []
    if ref_paths:
        ref_dir = _data_dir() / "skill_scripts" / key / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for rp in ref_paths:
            content = await _fetch_raw(owner, repo, rp)
            if len(content.encode("utf-8")) > _MAX_REFERENCE_BYTES:
                continue
            fname = rp.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.(md|txt)", fname):
                continue
            if fname in stored_refs:  # basename collision from a nested ref — keep the first
                continue
            (ref_dir / fname).write_text(content, encoding="utf-8")
            stored_refs.append(fname)

    today = datetime.now(timezone.utc).date().isoformat()
    attribution = (f"> Imported verbatim from https://github.com/{meta['full_name']} "
                   f"({meta['license']}) on {today}.\n\n")
    body = attribution + info["body"]
    if stored:
        body += ("\n\n## Bundled scripts\n"
                 "Run inside the sandbox via the run_python tool with "
                 f'{{"skill_script": "{key}/<file>"}} (no network; results via print):\n'
                 + "\n".join(f"- `{key}/{f}`" for f in stored))
    if stored_refs:
        body += ("\n\n## Bundled references\n"
                 "Reference docs shipped with this skill. Read one via the read_skill tool with "
                 '{"key": "' + key + '", "section": "references/<file>"}:\n'
                 + "\n".join(f"- `references/{f}`" for f in stored_refs))

    async with db_session.AsyncSessionLocal() as db:
        row = SkillPack(key=key, name=info["name"], category="imported",
                        description=info["description"], tier="safe",
                        status="registered", body=body)
        db.add(row)
        await db.commit()
    return {"key": key, "name": info["name"], "description": info["description"],
            "scripts": stored, "references": stored_refs, "license": meta["license"]}
