"""Faithful SKILL.md importer (P3).

This imports standard Agent-Skills-format skills VERBATIM (nothing is rewritten into house style):
parse frontmatter + body → registry, with the license gate the project treats as a red line, plus
bundled `scripts/*.py` stored for the P1 sandbox (run_python {"skill_script": "<key>/<file>"}).

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
import os
import re
from urllib.parse import quote
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


def parse_skill_md(raw: str, path: str = "") -> dict | None:
    """Parse a standard SKILL.md: YAML frontmatter (needs name+description) + markdown body. The key is the
    name's ASCII letters and digits; a name with none (Chinese, for example) takes its folder's, else a short
    hash of `path`, never "" (#539 review 9: "" put the files at skill_scripts/'s root)."""
    m = _FRONTMATTER_RE.match(raw or "")
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        return None
    # UNI1: the name and description through the one name cleaner; the body keeps ordinary text, and loses
    # only Tag and control characters (`cleaned` says whether it lost any).
    from server.orchestrator import untrusted
    written = raw[m.end():].strip()
    body = untrusted.clean_body(written).strip()
    name, description = untrusted.clean_name(meta["name"], 100), untrusted.clean_name(meta["description"], 300)
    if not body or not name or not description:
        return None
    key = _slug(name) or _slug(path.rsplit("/", 2)[-2] if path.count("/") else "") \
        or "skill-" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]
    # Line endings are not hidden characters: a CRLF file read as LF lost nothing (#526 review 5).
    plain = written.replace("\r\n", "\n").replace("\r", "\n").strip()
    # `frontmatter`: the name and description as YAML decoded them, before the cleaner, for the scan only: a hidden
    # character the cleaner drops is still the sign of a skill that tried to hide one (#526 merged with #539).
    return {"key": key, "name": name, "description": description, "body": body, "cleaned": body != plain,
            "frontmatter": f"{meta['name']}\n{meta['description']}"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


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


async def _get(path: str, *, raw: bool = False, params: dict | None = None) -> httpx.Response:
    token = await github_eval._token()
    headers = github_eval._headers(token)
    if raw:
        headers["Accept"] = "application/vnd.github.raw"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.get(f"{_GITHUB_API}{path}", headers=headers, params=params)


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
    return [e["path"] for e in r.json().get("tree") or [] if e.get("type") == "blob" and _plain_path(e.get("path"))]


#: A repository path the import fetches: no query, fragment, escape or backslash character, no control
#: character (#539 review 5: `?ref=` inside a path switched the fetch to another ref).
_ODD_PATH = re.compile(r"[?#%\\\x00-\x1f\x7f]")


def _plain_path(path) -> bool:
    """And no `.`, `..` or empty segment, no leading `/` (#539 recheck: httpx collapses `..`, so a path could
    name another repository)."""
    return (isinstance(path, str) and bool(path) and not _ODD_PATH.search(path) and not path.startswith("/")
            and all(segment not in ("", ".", "..") for segment in path.split("/")))


async def _fetch_raw(owner: str, repo: str, path: str, sha: str | None = None) -> str:
    if not _plain_path(path):
        raise ValueError("not a path the import can fetch")
    r = await _get(f"/repos/{owner}/{repo}/contents/{quote(path, safe='/')}", raw=True,
                   params={"ref": sha} if sha else None)
    r.raise_for_status()
    return r.text or ""


async def full_sha(owner: str, repo: str, sha: str) -> str:
    """A commit id as all 40 hex digits (#539 review 6: an abbreviation loses to a branch or tag of that name).
    An abbreviation is resolved by GitHub and must be a prefix of what comes back."""
    sha = (sha or "").lower()
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("not a commit id")
    if len(sha) == 40:
        return sha
    r = await _get(f"/repos/{owner}/{repo}/commits/{sha}")
    r.raise_for_status()
    full = str(r.json().get("sha") or "").lower()
    if not (re.fullmatch(r"[0-9a-f]{40}", full) and full.startswith(sha)):
        raise ValueError(f"{sha} is not a commit of {owner}/{repo}")
    return full


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
    ref, _, pin = (ref or "").partition("@")
    parsed = github_eval.parse_repo_ref(ref)
    if parsed is None:
        raise ValueError("not a GitHub repo reference (owner/name)")
    owner, repo = parsed
    meta = await github_eval.fetch_repo(owner, repo)
    license_block = _license_gate(meta["license"])
    # CAP4a-1: the listing reads one pinned commit (it read HEAD) and says which; the import then pins to it.
    # A typed `@<sha>` is that commit (#539 review).
    sha = await full_sha(owner, repo, pin) if pin else await head_sha(owner, repo)
    paths = await _tree_paths(owner, repo, sha)
    sub = (subpath or "").strip("/")
    skill_paths = [p for p in paths if p.endswith("SKILL.md")
                   and (not sub or p.startswith(sub + "/") or p == f"{sub}/SKILL.md")]
    skill_paths = skill_paths[:_MAX_SKILLS_PER_SCAN]

    async with db_session.AsyncSessionLocal() as db:
        existing = {k for (k,) in (await db.execute(select(SkillPack.key))).all()}

    skills = []
    for p in skill_paths:
        raw = await _fetch_raw(owner, repo, p, sha)
        info = parse_skill_md(raw, p)
        entry: dict = {"path": p, "scripts": _scripts_for(p, paths),
                       "references": _references_for(p, paths)}
        if info is None:
            entry.update(importable=False, reason="not a valid SKILL.md (frontmatter name+description required)")
        else:
            entry.update(key=info["key"], name=info["name"], description=info["description"],
                         body_bytes=len(info["body"].encode("utf-8")))
            spdx, source = await _skill_license(owner, repo, p, paths, meta["license"], sha)
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
                     "license": meta["license"], "stars": meta["stars"]}, "commit": sha,
            "license_ok": license_block is None or any(e.get("importable") for e in skills),
            "license_note": license_block if not any(e.get("license_source", "repo") != "repo" for e in skills) else None,
            "skills": skills}


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


async def import_skill(ref: str, path: str) -> dict:
    """Import ONE skill faithfully: `prepare_skill`, the same scan the install card runs, then `install_prepared`.
    Re-validates everything server-side (never trust the UI). A blocked scan writes nothing (#539 review 3: the
    import panel installed with no scan, and under the user's D2 its skills read unframed)."""
    prepared = await prepare_skill(ref, path)
    scan = scan_prepared(prepared)
    if scan["level"] == "blocked":
        rules = ", ".join(sorted({f["rule"] for f in scan["findings"] if f["level"] == "high"}))
        raise ValueError(f"blocked by the safety check: {rules}")
    return {**await install_prepared(prepared), "scan": scan}


def scan_prepared(prepared: dict) -> dict:
    """The one scan of a prepared skill, for the install card and the import panel alike: the whole SKILL.md as
    fetched, its name and description as YAML decodes them (what is stored and, under the user's D2, read
    unframed; a folded scalar or a quoted escape decodes to text the raw file does not show: #539 recheck), every
    script, dotfiles included, and every reference. The name and description are scanned as YAML decoded them,
    before UNI1a's cleaner (`frontmatter`): the stored ones are clean, but a hidden character the cleaner drops is
    the sign of a skill that tried to hide one."""
    from server.services import capability_scan
    info = prepared["info"]
    return capability_scan.scan_skill(f"{prepared['skill_md']}\n{info['frontmatter']}",
                                      prepared["scripts"], prepared["references"])


async def prepare_skill(ref: str, path: str) -> dict:
    """Fetch ONE skill whole at one pinned commit, in memory: nothing is written (v0.1.64 CAP4a-1: the card is
    built from this, scanned and hashed, and a yes installs exactly it).

    0.1.57 §5.2: pinned. `ref` may name the commit (`owner/repo@<sha>`, what a dossier or the import panel's
    listing recorded); without one, the import pins to the commit the default branch points at now. Every file
    is fetched AT that commit and its SHA-256 kept, so the dossier can say exactly what was installed."""
    ref, _, sha = (ref or "").partition("@")
    parsed = github_eval.parse_repo_ref(ref)
    if parsed is None:
        raise ValueError("not a GitHub repo reference")
    if sha and not _SHA_RE.fullmatch(sha.lower()):
        raise ValueError("not a commit id")
    owner, repo = parsed
    meta = await github_eval.fetch_repo(owner, repo)
    sha = await full_sha(owner, repo, sha) if sha else await head_sha(owner, repo)
    paths = await _tree_paths(owner, repo, sha)
    spdx, source = await _skill_license(owner, repo, path, paths, meta["license"], sha)
    block = _skill_license_block(spdx, source)
    if block:
        raise ValueError(block)
    files: dict[str, str] = {}
    sizes: dict[str, int] = {}
    skipped: list[dict] = []           # what the folder holds that is not installed, and why (#539 review 7)

    def _keep(file_path: str, content: str) -> str:
        files[file_path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sizes[file_path] = len(content.encode("utf-8"))
        return content

    if path not in paths:                                     # a file of that commit's tree, nothing else
        raise ValueError("no such SKILL.md at that commit")
    raw = _keep(path, await _fetch_raw(owner, repo, path, sha))
    info = parse_skill_md(raw, path)
    if info is None:
        raise ValueError("not a valid SKILL.md (frontmatter name+description required)")
    if len(info["body"].encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BYTES}B limit")
    async with db_session.AsyncSessionLocal() as db:
        if await db.get(SkillPack, info["key"]) is not None:
            raise ValueError(f"skill '{info['key']}' already exists in the library")

    # bundled scripts (flat names, .py only, capped) and references (flat basenames, .md/.txt only, the same
    # per-file and per-skill caps; PC-3 mounts these read-only), kept in memory until `install_prepared`.
    async def _bundled(found: list[str], cap: int, max_bytes: int, name_re: str) -> dict[str, str]:
        kept: dict[str, str] = {}
        taken: set[str] = set()                         # basenames ignoring case: APFS keeps one of two
        for n, file_path in enumerate(found):
            fname = file_path.rsplit("/", 1)[-1]
            if n >= cap:
                skipped.append({"path": file_path, "reason": f"more than {cap} files"})
                continue
            if not re.fullmatch(name_re, fname):
                skipped.append({"path": file_path, "reason": "not a file name the import keeps"})
                continue
            if fname.lower() in taken:
                skipped.append({"path": file_path, "reason": "the same file name as another"})
                continue
            content = await _fetch_raw(owner, repo, file_path, sha)
            if len(content.encode("utf-8")) > max_bytes:
                skipped.append({"path": file_path, "reason": f"larger than {max_bytes} bytes"})
                continue
            kept[fname] = _keep(file_path, content)
            taken.add(fname.lower())
        return kept

    # bundled scripts (flat names, .py only, capped) and references (flat basenames, .md/.txt only, the same
    # per-file and per-skill caps; PC-3 mounts these read-only), kept in memory until `install_prepared`.
    scripts = await _bundled(_scripts_for(path, paths), _MAX_SCRIPTS, _MAX_SCRIPT_BYTES, r"[A-Za-z0-9._-]+\.py")
    references = await _bundled(_references_for(path, paths), _MAX_REFERENCES, _MAX_REFERENCE_BYTES,
                                r"[A-Za-z0-9._-]+\.(md|txt)")
    return {"key": info["key"], "info": info, "full_name": meta["full_name"], "commit": sha, "license": spdx,
            "license_source": source, "skill_md": raw, "scripts": scripts, "references": references,
            "files": files, "sizes": sizes, "skipped": skipped}


async def install_prepared(prepared: dict) -> dict:
    """Write exactly what `prepare_skill` fetched: its scripts and references under data_dir/skill_scripts/<key>/,
    then the row. No second fetch, so what was scanned and shown is what is installed (CAP4a-1).

    #539 review 2 and 8: a folder already under the key has no row (checked first), so it is a removed or failed
    import's leftover; it goes to the Trash before anything is written, or its files would join the skill
    unscanned. Every file is created new, never through a link, then the folder is read back against the
    prepared hashes: exactly those files, those bytes. On any failure the folder goes to the Trash and no row is
    written."""
    from server.services import capability_install
    key, info, sha = prepared["key"], prepared["info"], prepared["commit"]
    async with db_session.AsyncSessionLocal() as db:
        if await db.get(SkillPack, key) is not None:
            raise ValueError(f"skill '{key}' already exists in the library")
    stored, stored_refs = list(prepared["scripts"]), list(prepared["references"])
    folder = _data_dir() / "skill_scripts" / key
    if os.path.lexists(folder):
        capability_install.to_trash(folder, prefix="Arslan leftover skill files")
    try:
        if stored or stored_refs:
            _write_folder(folder, prepared)
        return await _install_row(prepared, key, info, sha, stored, stored_refs)
    except BaseException:
        capability_install.to_trash(folder, prefix="Arslan failed skill import")
        raise


def _write_folder(folder: Path, prepared: dict) -> None:
    """The prepared files, each created new (O_EXCL, never through a link), then read back: the folder holds
    exactly them, byte for byte."""
    expected = {fname: content for fname, content in prepared["scripts"].items()}
    expected.update({f"references/{fname}": content for fname, content in prepared["references"].items()})
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    if prepared["references"]:
        (folder / "references").mkdir()
    for rel, content in expected.items():
        fd = os.open(folder / rel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
    found = {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in folder.rglob("*") if not path.is_dir() or path.is_symlink()}
    if found != {rel: hashlib.sha256(content.encode("utf-8")).hexdigest() for rel, content in expected.items()}:
        raise ValueError("the skill's folder does not match what was checked")


async def _install_row(prepared: dict, key: str, info: dict, sha: str, stored: list, stored_refs: list) -> dict:
    spdx, source = prepared["license"], prepared["license_source"]
    today = datetime.now(timezone.utc).date().isoformat()
    # "verbatim" only when nothing went (UNI1: Tag and control characters do).
    attribution = (f"> Imported {'with hidden characters removed' if info.get('cleaned') else 'verbatim'} "
                   f"from https://github.com/{prepared['full_name']} at {sha[:12]} "
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
            "license_source": source, "commit": sha, "files": prepared["files"]}
