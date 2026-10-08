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

import hashlib
import re
from datetime import datetime, timezone

import httpx
import yaml
from sqlalchemy import select

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
    # Single resolved root (config.data_dir(), same convention as code_sandbox): unset
    # ARSLAN_DATA_DIR -> the platform app-data dir, not CWD/data. Absolute + resolved.
    from server import config
    return config.data_dir()


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


_LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING")


def detect_license(text: str) -> str | None:
    """The SPDX id of a license FILE, from its text — only the permissive licenses
    we allow, recognised by their operative wording. Anything else (including
    "All rights reserved" terms) is None, which the gate refuses."""
    t = " ".join((text or "").split()).lower()
    if not t:
        return None
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in t:
        return "MIT"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if "neither the name" in t else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t:
        return "ISC" if "with or without fee is hereby granted, provided that" in t else "0BSD"
    if "this is free and unencumbered software released into the public domain" in t:
        return "Unlicense"
    if "cc0 1.0 universal" in t:
        return "CC0-1.0"
    return None


async def _skill_license(owner: str, repo: str, skill_path: str, paths: list[str],
                         repo_spdx: str | None, sha: str | None = None) -> tuple[str | None, str]:
    """(SPDX, where it came from) for ONE skill. The skill's own license file wins
    over the repo's (0.1.55): anthropics/skills has no repo license, but every skill
    folder has a LICENSE.txt — Apache-2.0 for most, Anthropic's own terms for the
    document skills. Read at the source, never from frontmatter or package metadata."""
    folder = skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""
    for name in _LICENSE_NAMES:
        candidate = f"{folder}/{name}" if folder else name
        if candidate in paths and folder:
            return detect_license(await _fetch_raw(owner, repo, candidate, sha)), candidate
    return repo_spdx, "repo"


def _skill_license_block(spdx: str | None, source: str) -> str | None:
    if source == "repo":
        return _license_gate(spdx)
    if spdx is None:
        return f"this skill's own {source.rsplit('/', 1)[-1]} is not a permissive license — cannot bundle it"
    return _license_gate(spdx)


async def _get(path: str, *, raw: bool = False) -> httpx.Response:
    token = await github_eval._token()
    headers = github_eval._headers(token)
    if raw:
        headers["Accept"] = "application/vnd.github.raw"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.get(f"{_GITHUB_API}{path}", headers=headers)


async def head_sha(owner: str, repo: str) -> str:
    """The commit the default branch points at now — what an import pins to (0.1.57 §5.2)."""
    r = await _get(f"/repos/{owner}/{repo}")
    r.raise_for_status()
    branch = r.json().get("default_branch") or "main"
    r = await _get(f"/repos/{owner}/{repo}/commits/{branch}")
    r.raise_for_status()
    return r.json()["sha"]


async def _tree_paths(owner: str, repo: str, sha: str | None = None) -> list[str]:
    """All blob paths at `sha`, or in the default branch (recursive tree)."""
    if sha is None:
        r = await _get(f"/repos/{owner}/{repo}")
        r.raise_for_status()
        sha = r.json().get("default_branch") or "main"
    r = await _get(f"/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
    if r.status_code == 403 and "rate limit" in (r.text or "").lower():
        raise ValueError("GitHub rate-limited — set GITHUB_TOKEN in Settings")
    r.raise_for_status()
    return [e["path"] for e in r.json().get("tree") or [] if e.get("type") == "blob"]


async def _fetch_raw(owner: str, repo: str, path: str, sha: str | None = None) -> str:
    r = await _get(f"/repos/{owner}/{repo}/contents/{path}" + (f"?ref={sha}" if sha else ""), raw=True)
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
    0.1.55: the license gate is per skill — its own license file, else the repo's."""
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
            spdx, source = await _skill_license(owner, repo, p, paths, meta["license"])
            block = _skill_license_block(spdx, source)
            entry.update(license=spdx, license_source=source)
            if block:
                entry.update(importable=False, reason=block)
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
            "license_ok": license_block is None or any(e.get("importable") for e in skills),
            "license_note": license_block if not any(e.get("license_source", "repo") != "repo" for e in skills) else None,
            "skills": skills}


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


async def import_skill(ref: str, path: str) -> dict:
    """Import ONE skill faithfully. Re-validates everything server-side (never trust the UI).

    0.1.57 §5.2: pinned. `ref` may name the commit (`owner/repo@<sha>`, what a dossier
    recorded); without one, the import pins to the commit the default branch points at now.
    Every file is fetched AT that commit and its SHA-256 returned, so the dossier can say
    exactly what was installed."""
    ref, _, sha = (ref or "").partition("@")
    parsed = github_eval.parse_repo_ref(ref)
    if parsed is None:
        raise ValueError("not a GitHub repo reference")
    if sha and not _SHA_RE.fullmatch(sha.lower()):
        raise ValueError("not a commit id")
    owner, repo = parsed
    meta = await github_eval.fetch_repo(owner, repo)
    sha = sha.lower() or await head_sha(owner, repo)
    paths = await _tree_paths(owner, repo, sha)
    spdx, source = await _skill_license(owner, repo, path, paths, meta["license"], sha)
    block = _skill_license_block(spdx, source)
    if block:
        raise ValueError(block)
    files: dict[str, str] = {}

    def _keep(file_path: str, content: str) -> str:
        files[file_path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return content

    raw = _keep(path, await _fetch_raw(owner, repo, path, sha))
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
    script_paths = _scripts_for(path, paths)[:_MAX_SCRIPTS]
    stored: list[str] = []
    if script_paths:
        script_dir = _data_dir() / "skill_scripts" / key
        script_dir.mkdir(parents=True, exist_ok=True)
        for sp in script_paths:
            content = await _fetch_raw(owner, repo, sp, sha)
            if len(content.encode("utf-8")) > _MAX_SCRIPT_BYTES:
                continue
            fname = sp.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.py", fname):
                continue
            (script_dir / fname).write_text(_keep(sp, content), encoding="utf-8")
            stored.append(fname)

    # bundled references → data_dir/skill_scripts/<key>/references/ (flat basenames,
    # .md/.txt only, same per-file + per-skill caps as scripts; PC-3 mounts these read-only).
    ref_paths = _references_for(path, paths)[:_MAX_REFERENCES]
    stored_refs: list[str] = []
    if ref_paths:
        ref_dir = _data_dir() / "skill_scripts" / key / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for rp in ref_paths:
            content = await _fetch_raw(owner, repo, rp, sha)
            if len(content.encode("utf-8")) > _MAX_REFERENCE_BYTES:
                continue
            fname = rp.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.(md|txt)", fname):
                continue
            if fname in stored_refs:  # basename collision from a nested ref — keep the first
                continue
            (ref_dir / fname).write_text(_keep(rp, content), encoding="utf-8")
            stored_refs.append(fname)

    today = datetime.now(timezone.utc).date().isoformat()
    attribution = (f"> Imported verbatim from https://github.com/{meta['full_name']} at {sha[:12]} "
                   f"({spdx}{'' if source == 'repo' else ', ' + source}) on {today}.\n\n")
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
            "scripts": stored, "references": stored_refs, "license": spdx,
            "license_source": source, "commit": sha, "files": files}
