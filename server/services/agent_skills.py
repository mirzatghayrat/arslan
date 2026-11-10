"""`~/.agents/skills` as a skill source (v0.1.64 CAP6a, docs/plans/0164/CAP-capabilities.md §CAP6a).

The open standard's folder, shared by several tools: a skill is `<name>/SKILL.md` with its `scripts/` and
`references/` beside it. Skills Arslan installs go there (skill_import.install_prepared), and skills another tool
put there are listed too, as "from another tool": a switch and no delete (capability_list refuses the delete on the
server), and a card before their first use.

What Arslan approved is kept in its own data folder, never in the skill's (`agent_skills.json`): for each skill
folder it reads, who put it there and the SHA-256 of every file at the time it was approved (`files`; None until a
card says yes). The folder is read at start and when the Capabilities list loads (`sync`), and again on every
`read_skill` and skill `run_python` (`checked`), which use exactly the bytes they hashed. A folder whose files no
longer match is switched off, and switching it on shows the card again.

The registry still lists skills from `SkillPack`: a folder skill has a row like any other (its text, as approved, in
`body`), and the manifest says which rows are backed by a folder. A row with no manifest entry reads its files from
the data folder, as every skill did before CAP6a, until the one-time export moves them (CAP6a's second part).

Not read: a folder name that is not a plain key (lowercase letters, digits and hyphens, at most 60), a seed's key,
the key of a skill Arslan already has from elsewhere, a folder that is a link or holds one, one that holds a file
with another name on disk (a hard link: the other name may be another skill's file or one outside every skill, whose
bytes a yes would pin as this skill's), and one past the size caps. CAP6b (command_sandbox.cap6b_folders,
workspace_paths) keeps the model from reading or writing the folder by any other way.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import stat
from pathlib import Path

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillPack
from server.registry.skill_trust import OTHER_TOOL, SEEDED

logger = logging.getLogger(__name__)

MANIFEST = "agent_skills.json"
MAX_SKILLS = 200
MAX_FILES = 100
MAX_BYTES = 5_000_000            # one skill's files together
_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")
ARSLAN, OTHER = "arslan", "other"
#: What the model is told when a folder skill's files no longer match what was approved.
CHANGED = ("its files in ~/.agents/skills changed since they were approved, so it is switched off. The user can "
           "look at it again on the Capabilities page.")
# macOS 11+: no part of the path may be a link at the open (as file_tools._NOFOLLOW). Where it is missing (Linux CI),
# O_NOFOLLOW covers the last part only. Never both: macOS refuses O_NOFOLLOW | O_NOFOLLOW_ANY (EINVAL).
_NOFOLLOW = getattr(os, "O_NOFOLLOW_ANY", 0) or os.O_NOFOLLOW


class Unreadable(Exception):
    """A skill folder Arslan does not read (a link, a hard link, too large, no valid SKILL.md)."""


class Changed(Exception):
    """A folder skill whose files differ from what was approved (or that cannot be read now)."""


class NotApproved(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def root() -> Path:
    """The folder as Arslan looks it up, the one CAP6b closes (command_sandbox.cap6b_spellings, first entry)."""
    from server.services import command_sandbox
    return command_sandbox.cap6b_spellings(None)[0]


def folder(key: str) -> Path:
    return root() / key


def plain_key(key: str) -> bool:
    return bool(key) and _KEY.fullmatch(key) is not None


# ── the manifest, in Arslan's data folder ──────────────────────────────────────────────────────────────────────

def _manifest_path() -> Path:
    from server import config
    return Path(config.data_dir()) / MANIFEST


def entries() -> dict[str, dict]:
    """Every folder skill Arslan reads: {key: {"by": "arslan"|"other", "files": {path: sha256} | None}}. A missing
    or unreadable manifest is empty: then no row is folder-backed, and nothing reads as approved."""
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    skills = data.get("skills") if isinstance(data, dict) else None
    return {k: v for k, v in (skills or {}).items() if plain_key(k) and isinstance(v, dict)}


def _save(skills: dict[str, dict]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{MANIFEST}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"version": 1, "skills": skills}, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def record(key: str, *, by: str, files: dict[str, str] | None) -> None:
    """Load, change and save with no await between, so two writers in the event loop never interleave."""
    skills = entries()
    skills[key] = {"by": by, "files": files}
    _save(skills)


def forget(key: str) -> None:
    skills = entries()
    if skills.pop(key, None) is not None:
        _save(skills)


def is_folder_skill(key: str) -> bool:
    return key in entries()


def scripts_dir(key: str) -> Path:
    """Where a skill's bundled scripts are: `scripts/` in its folder, or (not yet exported) the data folder's
    `skill_scripts/<key>/`, as RunPythonExecutor and the registry's health checks have read them.

    DELETE-BY: v0.1.64, CAP6a's second PR (the one-time export): once every imported skill is in the folder, the
    data-folder branch here and in `references_dir` goes (keep only what a backup restore needs)."""
    from server import config
    return folder(key) / "scripts" if is_folder_skill(key) else Path(config.data_dir()) / "skill_scripts" / key


def references_dir(key: str) -> Path:
    from server import config
    return (folder(key) if is_folder_skill(key) else Path(config.data_dir()) / "skill_scripts" / key) / "references"


# ── reading one folder ─────────────────────────────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(MAX_BYTES + 1)


def read_folder(key: str) -> dict:
    """Every file of the skill's folder, hashed, with the text of each that is UTF-8, and its SKILL.md parsed. A link
    anywhere in it (the folder itself included), or a file with another name on disk, is refused, and each file is
    opened without following a link and must be the file that was checked, so what was hashed is what is used. Raises
    Unreadable."""
    from server.services import skill_import
    files, texts = _read_tree(folder(key))
    raw = texts.get("SKILL.md")
    parsed = skill_import.parse_skill_md(raw, f"{key}/SKILL.md") if raw is not None else None
    if parsed is None:
        raise Unreadable("no valid SKILL.md")
    return {"files": files, "texts": texts, "info": parsed}


def _read_tree(base: Path) -> tuple[dict[str, str], dict[str, str]]:
    # The folders above the skill's own may be links (~/.agents linked elsewhere is supported, command_sandbox
    # held_ancestors), and the opens below follow none: so they start from the real path. The skill's folder and
    # everything in it are still looked at as they are.
    base = base.parent.resolve() / base.name
    try:
        info = os.lstat(base)
    except OSError as exc:
        raise Unreadable("missing") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise Unreadable("not a folder")
    files: dict[str, str] = {}
    texts: dict[str, str] = {}
    total = 0
    for current, dirs, names in os.walk(base, followlinks=False):
        here = Path(current)
        # Python's own byte-code cache: never read or run (run_python takes only the `.py` texts), and written by
        # whatever ran a script, so it would read as a change.
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in sorted(dirs):
            if (here / name).is_symlink():
                raise Unreadable("holds a link")
        for name in sorted(names):
            path = here / name
            try:
                info = os.lstat(path)
            except OSError as exc:                  # gone between the listing and here
                raise Unreadable("a file can't be read") from exc
            if not stat.S_ISREG(info.st_mode):
                raise Unreadable("holds a link or a special file")
            if info.st_nlink > 1:
                raise Unreadable("a file has another name on disk (a hard link)")
            if len(files) >= MAX_FILES:
                raise Unreadable("too many files")
            # Opened as _read_file does, and it must be the file just looked at (its device and inode). O_NONBLOCK: a
            # FIFO swapped in can't hold the open. _NOFOLLOW: nor a folder on the way swapped for a link after the walk
            # looked at it, where O_NOFOLLOW_ANY exists. Not in _read_file: CAP8-2's import reads another tool's skills
            # with it, and whether a second name refuses those is that import's to decide.
            try:
                fd = os.open(path, os.O_RDONLY | _NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as handle:
                    opened = os.fstat(handle.fileno())
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise Unreadable("a file changed while it was read")
                    data = handle.read(MAX_BYTES + 1)
            except OSError as exc:
                raise Unreadable("a file can't be read") from exc
            total += len(data)
            if total > MAX_BYTES:
                raise Unreadable("too large")
            rel = path.relative_to(base).as_posix()
            files[rel] = hashlib.sha256(data).hexdigest()
            try:
                texts[rel] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    return files, texts


def digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(sorted(files.items())).encode("utf-8")).hexdigest()


def _matches(read: dict | None, entry: dict | None) -> bool:
    """The hash check: the folder as read now is exactly what was approved."""
    return read is not None and entry is not None and entry.get("files") is not None and read["files"] == entry["files"]


def _read_or_none(key: str) -> dict | None:
    """The folder, or None when it can't be read for any reason (a file gone mid-read, a SKILL.md the YAML reader
    chokes on): that folder only counts as unreadable, and never stops the others' reading."""
    try:
        return read_folder(key)
    except Unreadable:
        return None
    except Exception as exc:  # noqa: BLE001 — one folder's failure is that folder's, read as unreadable
        logger.warning("skill folder %s could not be read: %s", key, type(exc).__name__)
        return None


def still_arslans(key: str) -> bool:
    """Whether the folder under `key` is still exactly what Arslan installed there: its entry says Arslan's and the
    files match the recorded hashes. Only then may a cleanup move it to the Trash; a folder that differs may be the
    user's or another tool's by now, and stays where it is."""
    entry = entries().get(key)
    return bool(entry) and entry.get("by") == ARSLAN and _matches(_read_or_none(key), entry)


async def _orphan(key: str) -> bool:
    """A row another tool's folder made, whose manifest entry is gone (the manifest lost, or a save that never
    happened): never approved, so it needs its card and is never read as Arslan's own (fail closed)."""
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
    return pack is not None and pack.category == OTHER_TOOL


# ── the registry's view ────────────────────────────────────────────────────────────────────────────────────────

def _list_and_read() -> tuple[list[str], dict[str, dict | None]]:
    """The folder's plain-named skills and each one read (None: unreadable). Blocking: run in a thread."""
    base = root()
    try:
        names = sorted(e.name for e in os.scandir(base) if plain_key(e.name))[:MAX_SKILLS] if base.is_dir() else []
    except OSError:
        names = []
    return names, {key: _read_or_none(key) for key in names if key not in SEEDED}


async def sync() -> dict[str, str]:
    """Read the folder and bring the rows in line: a new skill folder becomes a row "from another tool", switched off
    until its card; one whose files changed is switched off; one another tool removed goes (Arslan's own stays, off,
    for the user to delete). Returns each folder skill's status: "ok", "new" (never approved), "changed" or "gone".

    The folder is listed and read in a worker thread, off the event loop: a slow disk or a large folder never holds
    up the server."""
    names, reads = await asyncio.to_thread(_list_and_read)
    known = entries()
    status: dict[str, str] = {}
    # The manifest changes only after the rows' commit: a failure on the way leaves the rows as they were and the
    # manifest too, never a row whose entry is gone (and an entry with no row reads as nothing).
    later: dict[str, dict | None] = {}
    async with db_session.AsyncSessionLocal() as db:
        keys = sorted(set(names) | set(known))
        packs = {p.key: p for p in (await db.execute(select(SkillPack).where(SkillPack.key.in_(keys)))).scalars()}
        for key in sorted(set(known) - set(names)):
            pack = packs.get(key)
            if known[key].get("by") == OTHER:
                if pack is not None and pack.category == OTHER_TOOL:
                    await db.delete(pack)
                later[key] = None
                continue
            if pack is not None:
                pack.enabled = False
            status[key] = "gone"
        for key in names:
            if key in SEEDED:
                continue
            pack = packs.get(key)
            if pack is not None and key not in known and pack.category != OTHER_TOOL:
                continue                       # a skill Arslan has from elsewhere: the folder never shadows it
            read = reads.get(key)
            if pack is None:
                if read is None:
                    continue
                info = read["info"]
                db.add(SkillPack(key=key, name=info["name"], category=OTHER_TOOL, description=info["description"],
                                 tier="safe", status="registered", body=info["body"], enabled=False))
                later[key] = {"by": OTHER, "files": None}
                status[key] = "new"
                continue
            entry = known.get(key)
            if entry is None:                  # the manifest was lost: read as never approved
                entry = {"by": OTHER, "files": None}
                later[key] = entry
            if _matches(read, entry):
                status[key] = "ok"
                continue
            if pack.enabled is not False:
                pack.enabled = False
                logger.warning("skill folder %s changed since it was approved; switched off", key)
            status[key] = "new" if entry.get("files") is None else "changed"
        await db.commit()
    for key, entry in later.items():
        if entry is None:
            forget(key)
        else:
            record(key, **entry)
    return status


async def _switch_off(key: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is not None and pack.enabled is not False:
            pack.enabled = False
            await db.commit()


async def checked(key: str) -> dict | None:
    """For read_skill and run_python: None for a skill that is not folder-backed; otherwise the folder as read now,
    when it matches what was approved. Raises Changed (and switches the skill off) when it doesn't."""
    known = entries()
    if key not in known and not await _orphan(key):
        return None
    read = await asyncio.to_thread(_read_or_none, key)      # any failure to read is a mismatch: switched off
    if not _matches(read, known.get(key)):
        await _switch_off(key)
        raise Changed(key)
    return read


async def needs_card(key: str) -> bool:
    """Whether switching this skill on needs its card first: a folder skill never approved, or changed since, or
    another tool's whose manifest entry is gone."""
    known = entries()
    if key not in known:
        return await _orphan(key)
    return not _matches(await asyncio.to_thread(_read_or_none, key), known[key])


def card(key: str) -> dict:
    """The card before a folder skill's first use, or after its files changed (CAP4's facts: the whole SKILL.md, the
    scan's findings first, every file). It says the folder is shared. `digest` is what a yes approves. Raises
    Unreadable."""
    return _card(key, read_folder(key))


def _card(key: str, read: dict) -> dict:
    from server.services import capability_scan
    from server.orchestrator import untrusted
    known = entries().get(key) or {"by": OTHER, "files": None}
    texts, info = read["texts"], read["info"]
    references = {p: t for p, t in texts.items() if p.startswith("references/")}
    code = {p: t for p, t in texts.items() if p != "SKILL.md" and p not in references}
    scan = capability_scan.scan_skill("\n".join((texts["SKILL.md"], info["frontmatter"], info["name"],
                                                 info["description"], info["body"])), code, references)
    return {"kind": "skill_folder", "key": key, "name": info["name"], "description": info["description"],
            "origin": "installed" if known.get("by") == ARSLAN else "other_tool",
            "changed": known.get("files") is not None, "folder": f"~/.agents/skills/{key}",
            "skill_md": texts["SKILL.md"], "hidden": untrusted.hidden_summary(info["body"]),
            "files": sorted(read["files"]), "unscanned": sorted(p for p in read["files"] if p not in texts),
            "scan": scan, "digest": digest(read["files"]),
            # The folder is shared by several tools: what is installed there, others may read and use (CAP6a).
            "shared_folder": True}


async def approve(key: str, shown: str) -> None:
    """The card's yes: record exactly the files the card showed (by `shown`, its digest) and switch the skill on, its
    row's text from that SKILL.md. Refused when the files changed after the card, or the scan blocks them."""
    from server.services import capability_list
    known = entries()
    if key not in known:
        raise NotApproved("not_found")
    if await capability_list._part_of_a_plugin(f"skill:{key}"):
        raise NotApproved("part_of_a_plugin")    # only its plugin's switch reaches a part (CAP7b)
    def read_and_card() -> tuple[dict, dict]:
        read = read_folder(key)                # one read: what is checked here is what is recorded
        return read, _card(key, read)
    try:
        read, now = await asyncio.to_thread(read_and_card)
    except Exception as exc:  # noqa: BLE001 — anything that stops the reading approves nothing
        raise NotApproved("unreadable") from exc
    if now["digest"] != shown:
        raise NotApproved("changed")
    if now["scan"]["level"] == "blocked":
        raise NotApproved("blocked")
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is None:
            raise NotApproved("not_found")
        info = read["info"]
        pack.name, pack.description, pack.body, pack.enabled = info["name"], info["description"], info["body"], True
        by = known[key].get("by") or OTHER
        # A re-approval clears the earlier hashes first: if the row commits and the new hashes never get written,
        # the folder (even back at the earlier files) reads as unapproved beside the new text, never as approved.
        record(key, by=by, files=None)
        await db.commit()
    # After the commit: a commit that fails leaves the files unapproved. Until this line a read finds them
    # unapproved and switches the skill off again (fail closed).
    record(key, by=by, files=read["files"])


def write_new(base: Path, expected: dict[str, str]) -> dict[str, str]:
    """Write a skill Arslan installs into its new folder (made by the caller): each file created new, never through
    a link, then the folder read back. Returns the hashes the manifest keeps; ValueError when the folder holds
    anything else."""
    for rel in sorted(expected):
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(expected[rel])
    try:
        found = _read_tree(base)[0]
    except Unreadable as exc:
        raise ValueError(f"the skill's folder does not match what was checked: {exc}") from exc
    want = {rel: hashlib.sha256(text.encode("utf-8")).hexdigest() for rel, text in expected.items()}
    if found != want:
        raise ValueError("the skill's folder does not match what was checked")
    return want
