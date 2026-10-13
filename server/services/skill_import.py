"""Importing a skill from GitHub, whole (0.1.61 §C2, §C4).

One archive of ONE commit (codeload.github.com) → the skill's whole folder into `<data>/skills/<key>/`
(skill_files); the SkillPack row keeps the index entry. The license is read in that same archive: the
nearest license file from the skill's folder up to the root decides, by its wording (Ruling A). A
license Arslan does not recognise imports only with `license_ok` = the sha256 of the text the server
fetched itself ("Use it on this Mac only"); the skill is then local use only. Re-import is an update.
Supply chain (test_capability_supply_chain): a named repository and path only, never a query; fixed
hosts api.github.com (the repository's metadata) and codeload.github.com (its archive — the only
address an archive is ever asked of, a redirect included).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.services import capability_scan, github_eval, skill_files
from server.services.skill_forge import MAX_SKILL_BYTES

_CODELOAD_HOST = "codeload.github.com"
_CODELOAD = f"https://{_CODELOAD_HOST}"
#: Redirects of an archive request followed (codeload sends a renamed repository to its new name).
_MAX_REDIRECTS = 5
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_ARCHIVE_HEADERS = {"Accept-Encoding": "identity", "User-Agent": "arslan-toolhub"}   # the bytes are the tar.gz, not a layer on it
_ARCHIVE_TIMEOUT = 60.0
_ARCHIVE_CACHE_S = 600
_ARCHIVE_CACHE_MAX = 4
#: All cached archives together: one large repository is kept, not four of them.
_ARCHIVE_CACHE_BYTES = 128 * 1024 * 1024
#: More SKILL.md files than this in one repository are counted ("more"), not listed.
MAX_SCAN_SKILLS = 500
MAX_DESCRIPTION = 500
MAX_LICENSE_BYTES = 256 * 1024

# Permissive licenses Arslan recognises: these import without the license step.
ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
                    "Unlicense", "CC0-1.0", "0BSD"}
NO_LICENSE_TEXT = "No license file: by default the author keeps all rights."
#: Skills Arslan reads where other agents keep them (skill_sources): an import takes their name.
EXTERNAL_ORIGINS = frozenset({"agents", "claude", "codex"})
#: Skills whose text comes from outside Arslan: read like a web page (0.1.57 decision 5).
OUTSIDE_ORIGINS = EXTERNAL_ORIGINS | {"imported"}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
#: GitHub's own rules, loosely: an owner is letters, digits, dashes (and the underscore of a managed
#: account); a repository adds dots. Nothing that could make a URL mean another address.
_OWNER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_TREE_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
                      r"(?:/(?:tree|blob)/([^/\s]+)(?:/(\S*))?)?/?$")
#: The license file names 0.1.55 read; the reviewed-library index still uses them, and they are
#: preferred when a folder holds more than one license file. (This module never names the search:
#: test_no_installer_imports_the_search reads its source.)
_LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING")
#: Any license file (Ruling A): LICENSE, LICENCE, COPYING or UNLICENSE in any case, with an extension
#: or a suffix (license.txt, LICENSE-MIT, COPYING.LESSER). A code file is never a license.
_LICENSE_FILE_RE = re.compile(r"(?:licen[cs]e|copying|unlicense)(?:[.-][a-z0-9.-]*)?")
_NOT_A_LICENSE = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".json", ".yaml", ".yml", ".toml", ".html",
                  ".css", ".rb", ".go")
#: A frontmatter `license:` naming one of the eight (any spelling of the id) takes nothing away.
_ALLOWED_NORMALISED = frozenset(re.sub(r"[^a-z0-9.]", "", spdx.lower()) for spdx in ALLOWED_LICENSES)
_LICENSE_POINTER = re.compile(r"\b(?:licen[cs]e|copying)\b", re.I)
#: Frontmatter Arslan shows and does not obey (§C1): its own permissions decide.
_DECLARED = ("allowed-tools", "requires", "metadata")

_archive_cache: OrderedDict[tuple[str, str, str], tuple[float, bytes]] = OrderedDict()


def _data_dir() -> Path:
    # Single resolved root (config.data_dir(), same convention as code_sandbox): unset
    # ARSLAN_DATA_DIR -> the platform app-data dir, not CWD/data. Absolute + resolved.
    from server import config
    return config.data_dir()


# ── SKILL.md ──────────────────────────────────────────────────────────────────

def slug(text: str) -> str:
    """A name as a skill key: lower-case Latin letters, digits and dashes, at most 60."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60].strip("-")


#: A frontmatter's `allowed-tools`, `requires` and `metadata` are shown, never obeyed (§C1): kept as plain
#: JSON, and small. YAML can alias one list into itself nine ways nine times over (a 400-byte file is a
#: 2 GB string once written out) and writes dates, binary data and numbers that JSON has no word for.
_DECLARED_NODES = 200
_DECLARED_TEXT = 500


def _plain(value, left: list[int]):
    """`value` as JSON can keep it. `left` counts the values still allowed (shared references are
    counted every time they are met, and a list that holds itself runs out of them), so the result
    is small however the YAML was written."""
    left[0] -= 1
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if value.bit_length() < 63 else f"a number of {value.bit_length()} bits"
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return value[:_DECLARED_TEXT]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if left[0] <= 0:
                break
            out[str(k)[:100]] = _plain(v, left)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        items = []
        for item in (sorted(value, key=str) if isinstance(value, (set, frozenset)) else value):
            if left[0] <= 0:
                break
            items.append(_plain(item, left))
        return items
    return str(value)[:_DECLARED_TEXT]                  # a date, binary data...


def _text(value) -> str:
    """A frontmatter value as the short text it is shown as (a list or a mapping as bounded JSON)."""
    if isinstance(value, str):
        return value
    plain = _plain(value, [_DECLARED_NODES])
    return plain if isinstance(plain, str) else json.dumps(plain, ensure_ascii=False)


def parse_skill_md(raw: str, *, fallback_key: str = "") -> dict | None:
    """A standard SKILL.md: YAML frontmatter (name and description) + a Markdown body.

    The key comes from the name, else from `fallback_key` (its folder's name), else from the
    name's hash, so a name with no Latin letters still has a key. `disable-model-invocation:
    true` makes it not `invocable`; `allowed-tools`, `requires` and `metadata` are kept to be
    shown (`declared`, small and fit for JSON), never obeyed. `license` is the frontmatter's own
    `license:` value: the license step reads it (it can take a recognised license away, never
    grant one)."""
    m = _FRONTMATTER_RE.match(raw or "")
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except (yaml.YAMLError, ValueError, OverflowError, RecursionError):    # 2024-13-45; a number of 5,000 digits; [[[[…
        return None
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        return None
    body = raw[m.end():].strip()
    if not body:
        return None
    name = _text(meta["name"])
    key = (slug(name) or slug(fallback_key)
           or "skill-" + hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()[:8])
    flag = meta.get("disable-model-invocation")
    return {"key": key, "name": name[:100],
            "description": " ".join(_text(meta["description"]).split())[:MAX_DESCRIPTION], "body": body,
            "invocable": not (flag is True or (isinstance(flag, str) and flag.strip().lower() == "true")),
            "declared": _plain({k: meta[k] for k in _DECLARED if k in meta}, [_DECLARED_NODES]),
            "license": None if meta.get("license") is None else _text(meta["license"])}


def _license_gate(spdx: str | None) -> str | None:
    """None when importable; otherwise the human-readable refusal reason. Kept for
    capability_install (0.1.57 MCP installs, `capability_install.install`)."""
    if not spdx or spdx == "NOASSERTION":
        return "no license — cannot bundle unverified content"
    if spdx not in ALLOWED_LICENSES:
        return f"license {spdx} is not in the permissive allowlist"
    return None


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


# ── where from ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Source:
    owner: str
    repo: str
    ref: str          # a commit, a branch or tag, or "HEAD"
    subpath: str      # a folder inside the repository ("" = all of it)


def _valid_repo(repo: str) -> bool:
    return bool(_REPO_RE.fullmatch(repo)) and repo not in (".", "..")


def parse_source(text: str, subpath: str = "") -> Source | None:
    """`owner/repo`, `owner/repo@<commit>`, or a github.com link — a `/tree/<ref>/<path>` (or
    `/blob/…/SKILL.md`) link is followed to that ref and folder. A ref with a slash in it (a
    branch named feature/x) is not supported in a link. None for anything that is not a
    repository; ValueError for a bad pin or a path that leaves the repository."""
    raw = (text or "").strip()
    base, at, pinned = raw.partition("@")
    if at and "/" in pinned:                   # an "@" further along a link is not a pin
        base, pinned = raw, ""
    ref, path = "", ""
    m = _TREE_RE.match(base)
    if m:
        owner, repo, ref, path = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
    else:
        parsed = github_eval.parse_repo_ref(base)
        if parsed is None or base.lower().startswith(("http://", "https://")) and "github.com" not in base:
            return None
        owner, repo = parsed
    if not _OWNER_RE.fullmatch(owner) or not _valid_repo(repo.removesuffix(".git")):
        return None                            # "evil.example/o/r" is no GitHub repository
    if pinned:
        if not _SHA_RE.fullmatch(pinned.lower()):
            raise ValueError("not a commit id")
        ref = pinned.lower()
    if ref and (not _REF_RE.fullmatch(ref) or ref.startswith(".")):
        raise ValueError("not a branch, tag or commit")
    path = (path or subpath or "").strip().strip("/")
    if path.rsplit("/", 1)[-1] == "SKILL.md":
        path = path.rsplit("/", 1)[0] if "/" in path else ""
    if path and skill_files.safe_relpath(path) is None:
        raise ValueError("not a folder inside the repository")
    return Source(owner, repo.removesuffix(".git"), ref or "HEAD", path)


def _codeload_url(owner: str, repo: str, ref: str) -> httpx.URL:
    """The one address an archive is asked of. The names are checked here, on the way to the request,
    whoever calls: nothing in them can make the URL mean another host or another path."""
    if (not _OWNER_RE.fullmatch(owner or "") or not _valid_repo(repo or "") or not _REF_RE.fullmatch(ref or "")
            or ref.startswith(".")):
        raise ValueError("not a GitHub repository")
    return httpx.URL(f"{_CODELOAD}/{owner}/{repo}/tar.gz/{ref}")


def _require_codeload(url: httpx.URL) -> None:
    """Refuse an address that is not codeload.github.com over https: checked on every request the
    download makes, the first and each redirect, before it is sent."""
    if url.scheme != "https" or url.host != _CODELOAD_HOST or url.port not in (None, 443) or url.userinfo:
        raise ValueError("GitHub sent the download somewhere other than codeload.github.com; it was not followed")


async def _download(owner: str, repo: str, ref: str, *, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """GitHub's tar.gz of `ref`, from codeload.github.com and nowhere else: redirects are followed by
    hand, up to _MAX_REDIRECTS, each one only if it stays on that host. `transport` is how a test
    serves the request (httpx.MockTransport); production leaves it None."""
    url = _codeload_url(owner, repo, ref)
    chunks: list[bytes] = []
    size = 0
    async with httpx.AsyncClient(timeout=_ARCHIVE_TIMEOUT, follow_redirects=False, transport=transport) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _require_codeload(url)
            async with client.stream("GET", url, headers=_ARCHIVE_HEADERS) as response:
                if response.status_code in _REDIRECTS and response.headers.get("location"):
                    try:
                        url = response.url.join(response.headers["location"])
                    except httpx.InvalidURL:
                        raise ValueError("GitHub sent the download to an address that is not one") from None
                    continue
                if response.status_code == 404:
                    raise ValueError("the repository or that commit is not on GitHub")
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > skill_files.MAX_ARCHIVE_BYTES:
                        raise ValueError("the repository archive is larger than 64 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError("GitHub redirected the download too many times")


def _remember(key: tuple[str, str, str], data: bytes) -> None:
    _archive_cache[key] = (time.monotonic(), data)
    _archive_cache.move_to_end(key)

    def held() -> int:                        # one archive may sit under two keys (ref and commit)
        return sum(len(blob) for blob in {id(v[1]): v[1] for v in _archive_cache.values()}.values())
    while len(_archive_cache) > _ARCHIVE_CACHE_MAX or (len(_archive_cache) > 1 and held() > _ARCHIVE_CACHE_BYTES):
        _archive_cache.popitem(last=False)


async def _fetch_archive(owner: str, repo: str, ref: str) -> bytes:
    """GitHub's tar.gz of `ref`. The last few are kept ten minutes, so a scan and the import that
    follows it download once."""
    key = (owner.lower(), repo.lower(), ref)
    hit = _archive_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < _ARCHIVE_CACHE_S:
        return hit[1]
    data = await _download(owner, repo, ref)
    _remember(key, data)
    return data


async def _archive(source: Source, *, keep, keep_limit: int | None = None) -> skill_files.Archive:
    data = await _fetch_archive(source.owner, source.repo, source.ref)
    archive = await asyncio.to_thread(skill_files.read_archive, data, keep=keep, keep_limit=keep_limit)
    if not re.fullmatch(r"[0-9a-f]{40}", archive.commit or ""):
        raise ValueError("GitHub's archive does not say which commit it is")
    if _SHA_RE.fullmatch(source.ref) and not archive.commit.startswith(source.ref):
        raise ValueError("GitHub sent another commit than the one pinned")
    _remember((source.owner.lower(), source.repo.lower(), archive.commit), data)
    return archive


# ── the license (Ruling A) ────────────────────────────────────────────────────

@dataclass(frozen=True)
class SkillLicense:
    spdx: str | None
    recognised: bool
    read_from: str          # the license file in the repository, "repo" (GitHub's detection) or "none"
    text: str               # what the user reads in the step
    sha256: str             # of `text`, UTF-8: what license_ok must equal

    def view(self, *, with_text: bool) -> dict:
        out = {"spdx": self.spdx, "recognised": self.recognised, "read_from": self.read_from,
               "sha256": self.sha256}
        if with_text:
            out["text"] = self.text
        return out


def license_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_license_name(name: str) -> bool:
    low = name.lower()
    return bool(_LICENSE_FILE_RE.fullmatch(low)) and not low.endswith(_NOT_A_LICENSE)


def _text_of(archive: skill_files.Archive, path: str) -> str | None:
    """A file read from the archive as the scan reads it (`capability_scan.decode_text`): UTF-16 or
    UTF-32 by its byte-order mark, otherwise UTF-8. Never `archive.text`, which reads UTF-8 only: a
    UTF-16 SKILL.md would come out as letters between NULs, and no rule finds a word in that."""
    entry = archive.entries.get(path)
    if entry is None or entry.kind != "file" or entry.data is None:
        return None
    return capability_scan.decode_text(entry.data)


def _license_file(archive: skill_files.Archive, folder: str) -> str | None:
    """The license file directly in `folder` ("" = the root): the 0.1.55 names first, then any."""
    prefix = f"{folder}/" if folder else ""
    names = [p[len(prefix):] for p, e in archive.entries.items()
             if e.kind == "file" and p.startswith(prefix) and "/" not in p[len(prefix):]
             and _is_license_name(p[len(prefix):])]
    if not names:
        return None
    names.sort(key=lambda n: (n not in _LICENSE_NAMES, n.lower()))
    return prefix + names[0]


def _folders_up(folder: str) -> list[str]:
    """The skill's folder, each folder above it, then the root ("")."""
    parts = folder.split("/") if folder else []
    return ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]


def _declared_note(archive: skill_files.Archive, folder: str, value) -> str | None:
    """The SKILL.md's own `license:` (Agent Skills frontmatter), when the user must read it: it can
    take a recognised license away, never grant one. Nothing when it names one of the eight, or
    when it points at a license file the skill's own folder has (that file then decides)."""
    if value is None or not str(value).strip():
        return None
    text = " ".join(str(value).split())[:300]
    norm = re.sub(r"[^a-z0-9.]", "", text.lower())
    if norm in _ALLOWED_NORMALISED or norm.removesuffix("license") in _ALLOWED_NORMALISED:
        return None
    if _LICENSE_POINTER.search(text) and _license_file(archive, folder) is not None:
        return None
    return f"SKILL.md says — license: {text}\n\n"


def skill_license(archive: skill_files.Archive, skill_path: str, repo_spdx: str | None,
                  declared=None) -> SkillLicense:
    """The license of ONE skill (§C4, Ruling A), read in the archive of the pinned commit.

    The nearest license file on the way from the skill's folder up to the root decides
    (anthropics/skills keeps a LICENSE.txt in every skill folder; a monorepo may keep one per
    group), and only its own wording can make it one of the eight. GitHub's detection — made for
    the default branch, today — is used only when no license file lies on that path. A
    frontmatter `license:` (`declared`) naming anything else puts its line in front of the text."""
    folder = skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""
    note = _declared_note(archive, folder, declared)
    for level in _folders_up(folder):
        path = _license_file(archive, level)
        if path is None:
            continue
        body = _text_of(archive, path) or ""
        if not body.strip():
            body = NO_LICENSE_TEXT                     # an empty license file is no license
        spdx = detect_license(body)
        text = (note or "") + body
        label = spdx or (repo_spdx if level == "" else None)
        return SkillLicense(label, spdx in ALLOWED_LICENSES and note is None, path, text, license_sha256(text))
    if repo_spdx in ALLOWED_LICENSES and note is None:
        return SkillLicense(repo_spdx, True, "repo", "", license_sha256(""))
    text = (note or "") + NO_LICENSE_TEXT
    return SkillLicense(repo_spdx or None, False, "none", text, license_sha256(text))


class LicenseStepNeeded(ValueError):
    """The license is not one Arslan recognises: the user reads the text and decides (§C4)."""

    def __init__(self, license: SkillLicense, *, key: str, name: str):
        super().__init__("license_step")
        self.license, self.key, self.name = license, key, name


def _skill_license_block(lic: SkillLicense, license_ok: str | None, accepted_sha256: str | None) -> str | None:
    """None when the import may go ahead: a recognised license, or the user's "Use it on this Mac
    only" for exactly this text — `license_ok` is its sha256, or this skill's earlier acceptance
    was of the same text. Otherwise "license_step", or why the answer given does not fit."""
    if lic.recognised:
        return None
    if license_ok and hmac.compare_digest(license_ok.strip().lower(), lic.sha256):
        return None
    if accepted_sha256 and hmac.compare_digest(accepted_sha256, lic.sha256):
        return None
    if license_ok:
        return "the license text is not the one that was shown (it changed): read it again and decide"
    return "license_step"


# ── scanning a repository ─────────────────────────────────────────────────────

def _same_import(pack: SkillPack, dossier: CapabilitySource | None, full_name: str, path: str) -> bool:
    """Whether `pack` is this repository's skill at `path`, imported before: then importing it
    again is an update. A skill imported before 0.1.61 has no dossier; its attribution line names
    the repository."""
    if pack.origin != "imported" and pack.category != "imported":
        return False
    if dossier is not None and dossier.repo:
        return dossier.repo.lower() == full_name.lower() and (dossier.candidate_id or "").endswith(f":{path}")
    first = (pack.body or "").split("\n", 1)[0]
    return first.startswith(f"> Imported verbatim from https://github.com/{full_name} ")


def _replaces(existing: SkillPack | None) -> dict | None:
    """The shared-folder skill an import takes the name of (Ruling 8): said before the click."""
    if existing is None or existing.origin not in EXTERNAL_ORIGINS:
        return None
    return {"source": existing.origin, "folder": existing.folder}


def _scan_entry(archive: skill_files.Archive, path: str, meta: dict, packs: dict, dossiers: dict) -> dict:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    prefix = f"{folder}/" if folder else ""
    files = [e for e in archive.under(folder) if e.kind == "file"]
    entry: dict = {"path": path, "files": len(files), "bytes": sum(e.size for e in files),
                   "has_scripts": any(e.path[len(prefix):].startswith("scripts/") for e in files),
                   "update": False, "replaces": None}
    fallback = folder.rsplit("/", 1)[-1] if folder else meta["full_name"].split("/")[-1]
    info = parse_skill_md(_text_of(archive, path) or "", fallback_key=fallback)
    if info is None:
        return {**entry, "importable": False,
                "reason": "not a valid SKILL.md (frontmatter name and description are needed)"}
    lic = skill_license(archive, path, meta["license"], info["license"])
    entry.update(key=info["key"], name=info["name"], description=info["description"],
                 body_bytes=len(info["body"].encode("utf-8")), invocable=info["invocable"],
                 license=lic.view(with_text=not lic.recognised))
    existing = packs.get(info["key"])
    entry["update"] = bool(existing is not None and _same_import(
        existing, dossiers.get(existing.source_id or ""), meta["full_name"], path))
    entry["replaces"] = _replaces(existing)
    reason = None
    if not lic.recognised and len(lic.text.encode("utf-8")) > MAX_LICENSE_BYTES:
        reason = "the license text is too long to show"
    elif entry["body_bytes"] > MAX_SKILL_BYTES:
        reason = f"body {entry['body_bytes']}B exceeds the {MAX_SKILL_BYTES}B limit"
    elif len(files) > skill_files.MAX_FOLDER_FILES or entry["bytes"] > skill_files.MAX_FOLDER_BYTES:
        reason = "the skill's folder is larger than 20 MB or 2,000 files"
    elif existing is not None and not entry["update"] and existing.origin not in EXTERNAL_ORIGINS:
        reason = f"a skill named '{info['key']}' already exists"
    return {**entry, "importable": reason is None, "reason": reason}


def _keep_for_scan(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name == "SKILL.md" or _is_license_name(name)


async def scan_skills(ref: str, subpath: str = "") -> dict:
    """Every SKILL.md in a repository (or under a `/tree/…` folder), each with its license, its
    folder's size and whether importing it would be an update. Reads one archive."""
    source = parse_source(ref, subpath)
    if source is None:
        raise ValueError("not a GitHub repo reference (owner/name)")
    meta = await github_eval.fetch_repo(source.owner, source.repo)
    archive = await _archive(source, keep=_keep_for_scan, keep_limit=skill_files.MAX_ARCHIVE_BYTES)
    paths = archive.skill_mds(source.subpath)
    async with db_session.AsyncSessionLocal() as db:
        packs = {p.key: p for p in (await db.execute(select(SkillPack))).scalars().all()}
        dossiers = {d.id: d for d in (await db.execute(
            select(CapabilitySource).where(CapabilitySource.kind == "skill"))).scalars().all()}
    return {"repo": {"full_name": meta["full_name"], "html_url": meta["html_url"],
                     "license": meta["license"], "stars": meta["stars"]},
            "commit": archive.commit, "subpath": source.subpath,
            "skills": await asyncio.to_thread(     # a repository of hundreds of skills is a lot of listing
                lambda: [_scan_entry(archive, p, meta, packs, dossiers) for p in paths[:MAX_SCAN_SKILLS]]),
            "more": max(0, len(paths) - MAX_SCAN_SKILLS)}


# ── importing one skill ───────────────────────────────────────────────────────

def _attribution(full_name: str, commit: str, lic: SkillLicense, today: str) -> str:
    if lic.recognised:
        terms = lic.spdx + ("" if lic.read_from in ("repo", "none") else f", {lic.read_from}")
    else:
        terms = "license not recognised: used on this Mac only, not redistributable"
    return f"> Imported verbatim from https://github.com/{full_name} at {commit[:12]} ({terms}) on {today}.\n\n"


#: How much of the SKILL.md already in the folder is read to say what an update changed.
_MAX_OLD_MD = 1024 * 1024


def _read_md(folder: Path) -> str:
    """The SKILL.md of the folder an update replaces, as the scan reads a file (`decode_text`)."""
    path = folder / "SKILL.md"
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        with path.open("rb") as handle:
            return capability_scan.decode_text(handle.read(_MAX_OLD_MD))
    except OSError:
        return ""


async def import_skill(ref: str, path: str, *, license_ok: str | None = None) -> dict:
    """Import ONE skill, whole and pinned to one commit (§C2, §C4). Everything is re-checked here,
    on the server: no client can skip the license step.

    `ref` names the repository, optionally a commit (`owner/repo@<sha>`, what a scan returned),
    or is a github.com link. `path` is the SKILL.md inside it. `license_ok` is the sha256 of the
    license text the user read and accepted for local use.

    The result's `files` maps each file to its sha256 under the name it was COPIED as: the skill's
    folder in the repository plus the file's path on this disk. On a Mac's case-insensitive disk
    `s/Docs/b.md` and `s/docs/a.md` land in one folder, and `files` says so (`Docs/b.md`,
    `Docs/a.md`); it is never translated back to the archive's spelling, because the dossier is
    compared with the folder on disk (`skill_files.checksums`) and must name the same files.

    The folder of `key` is swapped under `skill_files.key_lock(key)`, from reading the folder it
    replaces to its `retire` or `swap_back`: two imports of one key follow each other."""
    source = parse_source(ref)
    if source is None:
        raise ValueError("not a GitHub repo reference")
    skill_path = (path or "").strip().strip("/")
    if skill_files.safe_relpath(skill_path) is None or skill_path.rsplit("/", 1)[-1] != "SKILL.md":
        raise ValueError("path must name a SKILL.md inside the repository")
    folder = skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""
    prefix = f"{folder}/" if folder else ""
    meta = await github_eval.fetch_repo(source.owner, source.repo)
    archive = await _archive(source, keep=lambda p: p.startswith(prefix) or _is_license_name(p.rsplit("/", 1)[-1]))
    raw = _text_of(archive, skill_path)
    if raw is None:
        raise ValueError(f"{skill_path} is not in the repository at {archive.commit[:12]}")
    info = parse_skill_md(raw, fallback_key=folder.rsplit("/", 1)[-1] if folder else source.repo)
    if info is None:
        raise ValueError("not a valid SKILL.md (frontmatter name and description are needed)")
    if len(info["body"].encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BYTES}B limit")
    lic = skill_license(archive, skill_path, meta["license"], info["license"])
    if not lic.recognised and len(lic.text.encode("utf-8")) > MAX_LICENSE_BYTES:
        raise ValueError("the license text is too long to show")
    key = info["key"]
    async with skill_files.key_lock(key):
        async with db_session.AsyncSessionLocal() as db:
            existing = await db.get(SkillPack, key)
            dossier = (await db.get(CapabilitySource, existing.source_id)
                       if existing is not None and existing.source_id else None)
        update = existing is not None and _same_import(existing, dossier, meta["full_name"], skill_path)
        if existing is not None and not update and existing.origin not in EXTERNAL_ORIGINS:
            raise ValueError(f"a skill named '{key}' already exists")
        replaces = _replaces(existing)
        accepted = existing.license_sha256 if update and existing.local_only else None
        block = _skill_license_block(lic, license_ok, accepted)
        if block == "license_step":
            raise LicenseStepNeeded(lic, key=key, name=info["name"])
        if block:
            raise ValueError(block)

        final = skill_files.folder_for(key)
        old_files = await asyncio.to_thread(skill_files.checksums, final) if update else {}
        old_md = _read_md(final) if update else ""
        staged = await asyncio.to_thread(skill_files.stage, archive, folder)
        try:
            # SKILL.md is read from the staged folder, as the file it is: the scan decodes it by its
            # byte-order mark and caps it, and it is the file that will be there to be read.
            scan = await asyncio.to_thread(capability_scan.scan_skill_folder, staged.path, None)
            aside = skill_files.swap_in(staged, key)
        except BaseException:
            skill_files.discard(staged)
            raise
        try:
            recorded = await _record_import(key=key, info=info, raw=raw, lic=lic, scan=scan, meta=meta,
                                            commit=archive.commit, skill_path=skill_path, folder=folder,
                                            files=staged.files, newly_accepted=accepted != lic.sha256)
        except BaseException:
            skill_files.swap_back(key, aside)
            raise
        skill_files.retire(aside)                 # never raises: a Trash it cannot reach is logged
        scripts = skill_files.has_scripts(final)
    return {"key": key, "name": info["name"], "description": info["description"], "update": update,
            "replaces": replaces, "commit": archive.commit,
            "files": {prefix + rel: sha for rel, sha in staged.files.items()},
            "skipped": staged.skipped, "license": lic.spdx, "license_source": lic.read_from,
            "recognised": lic.recognised, "local_only": not lic.recognised, "scan": scan,
            "enabled": recorded["enabled"], "source_id": recorded["source_id"],
            "has_scripts": scripts,
            "changes": skill_files.changes(old_files, staged.files, old_md, raw) if update else None}


async def _record_import(*, key: str, info: dict, raw: str, lic: SkillLicense, scan: dict, meta: dict,
                         commit: str, skill_path: str, folder: str, files: dict[str, str],
                         newly_accepted: bool) -> dict:
    """The skill's row and its dossier, in one transaction. An update keeps the user's on/off,
    unless the new version scans dangerous with something the user has not read (Ruling C):
    then it is off."""
    now = datetime.utcnow()
    full = meta["full_name"]
    prefix = f"{folder}/" if folder else ""
    dangerous = scan.get("verdict") == "dangerous"
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is not None and pack.origin in EXTERNAL_ORIGINS:
            await db.delete(pack)              # Arslan's own import takes the name (§C1 precedence)
            await db.flush()
            pack = None
        dossier = await db.get(CapabilitySource, pack.source_id) if pack is not None and pack.source_id else None
        if pack is None:
            pack = SkillPack(key=key, enabled=not dangerous)
            db.add(pack)
        elif dangerous:
            if (pack.scan or {}).get("accepted") and capability_scan.same_findings(pack.scan, scan):
                scan = {**scan, "accepted": True}      # nothing new since the user read it: stays as it was
            else:
                pack.enabled = False
        if dossier is None:
            dossier = CapabilitySource(id=uuid.uuid4().hex, owner_id="local", kind="skill",
                                       candidate_id=f"github:{full}:{skill_path}"[:300], needs={}, grants={},
                                       created_at=now)
            db.add(dossier)
        pack.name, pack.category, pack.description = info["name"], "imported", info["description"]
        # `origin` is set on every write, a new row and an old one: the column's default is "saved".
        pack.tier, pack.status, pack.origin = "safe", "registered", "imported"
        pack.body = _attribution(full, commit, lic, now.date().isoformat()) + info["body"]
        pack.folder = str(skill_files.folder_for(key))
        pack.text_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        pack.scan, pack.frontmatter, pack.invocable = scan, info["declared"] or None, info["invocable"]
        pack.source_id = dossier.id
        pack.local_only, pack.license_spdx = not lic.recognised, lic.spdx
        pack.license_sha256 = None if lic.recognised else lic.sha256
        if lic.recognised:
            pack.license_accepted_at = None
        elif newly_accepted or pack.license_accepted_at is None:
            pack.license_accepted_at = now
        dossier.name = info["name"][:120]
        dossier.source_url = f"https://github.com/{full}/tree/{commit}/{folder}".rstrip("/")[:500]
        dossier.repo, dossier.version, dossier.commit_sha = full, commit[:12], commit
        dossier.license_spdx, dossier.license_path = lic.spdx, lic.read_from[:300]
        dossier.stars, dossier.pushed_days, dossier.checked_at = meta.get("stars"), meta.get("pushed_days"), now
        dossier.runtime, dossier.scan = "skill", scan
        dossier.test = {"ok": not dangerous, "stage": "scan", "at": now.isoformat() + "Z"}
        dossier.files = {prefix + rel: sha for rel, sha in files.items()}
        dossier.state, dossier.skill_key = "installed", key
        dossier.error = "scan" if dangerous else None
        dossier.installed_at = now
        await db.commit()
        return {"enabled": pack.enabled is not False, "source_id": dossier.id}
