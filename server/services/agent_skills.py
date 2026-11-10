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
the data folder, as every skill did before CAP6a. The one-time export (`export_imported`, CAP6a's second part) moves
the skills imported before CAP6a into the folder at start, once.

Every change to the manifest that goes with a commit of the rows holds `manifest_lock()` from its first write to its
last, and so does every switch-off after a reading of the folder (the reading itself is done before it): a reload
between an approval's commit and its hash write (#795 review) waits for the hashes instead of switching the
just-approved skill off.

Not read: a folder name that is not a plain key (lowercase letters, digits and hyphens, at most 60), a seed's key,
the key of a skill Arslan already has from elsewhere, a folder that is a link or holds one, and one past the size
caps. CAP6b (command_sandbox.cap6b_folders, workspace_paths) keeps the model from reading or writing the folder by
any other way.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import weakref
from datetime import datetime, timezone
from pathlib import Path

import yaml
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
#: Files Finder writes into any folder it opens. Never read or run by anything, so never hashed: one would read as a
#: change and switch the skill off (#808 review).
_IGNORED = frozenset({".DS_Store"})
ARSLAN, OTHER = "arslan", "other"
#: What the model is told when a folder skill's files no longer match what was approved.
CHANGED = ("its files in ~/.agents/skills changed since they were approved, so it is switched off. The user can "
           "look at it again on the Capabilities page.")


class Unreadable(Exception):
    """A skill folder Arslan does not read (a link, too large, no valid SKILL.md)."""


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


def _load() -> dict:
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def entries() -> dict[str, dict]:
    """Every folder skill Arslan reads: {key: {"by": "arslan"|"other", "files": {path: sha256} | None}}. A missing
    or unreadable manifest is empty: then no row is folder-backed, and nothing reads as approved."""
    skills = _load().get("skills")
    return {k: v for k, v in (skills.items() if isinstance(skills, dict) else ()) if plain_key(k) and isinstance(v, dict)}


def export_state() -> dict | None:
    """The one-time export's record (`export_imported`): {"state": "running"|"done", ...}, or None before it ran."""
    state = _load().get("export")
    return state if isinstance(state, dict) else None


def _save(skills: dict[str, dict], export: dict | None = None) -> None:
    """The whole manifest in one atomic replace. The export's record is kept as it is unless `export` is given."""
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"version": 1, "skills": skills}
    if (kept := export if export is not None else export_state()) is not None:
        data["export"] = kept
    temp = path.with_name(f".{MANIFEST}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def manifest_lock() -> asyncio.Lock:
    """Held across a change of the manifest that goes with a commit of the rows (`approve`, `sync`, an install, the
    export), and by `checked` before it switches a skill off: none of them sees another's half-done state. One per
    event loop (an asyncio.Lock belongs to the loop it first waits on)."""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = _locks[loop] = asyncio.Lock()
    return lock


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

    After the export (`export_imported`) the data-folder branch here and in `references_dir` serves only what it did
    not move: a skill switched off at the time, or one it kept (a folder another tool has under its key, a failure;
    `export_state()["kept"]`). An exported skill's copy is removed once its folder is checked.
    DELETE-BY: v0.1.64 (CAP6a). The release check lists it; what then still reads from the data folder (the skills
    above) needs the user's decision before the branch goes."""
    from server import config
    return folder(key) / "scripts" if is_folder_skill(key) else Path(config.data_dir()) / "skill_scripts" / key


def references_dir(key: str) -> Path:
    from server import config
    return (folder(key) if is_folder_skill(key) else Path(config.data_dir()) / "skill_scripts" / key) / "references"


# ── reading one folder ─────────────────────────────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> bytes:
    """A regular file's bytes, never through a link. Opened without blocking and checked as opened (#808 review): a
    FIFO swapped in after the caller's lstat would otherwise hold the open until something writes to it. Raises
    OSError for anything that is not a regular file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(f"not a regular file: {path.name}")
        return handle.read(MAX_BYTES + 1)


def read_folder(key: str) -> dict:
    """Every file of the skill's folder, hashed, with the text of each that is UTF-8, and its SKILL.md parsed. A link
    anywhere in it (the folder itself included) is refused, and each file is opened without following one, so what
    was hashed is what is used. Raises Unreadable."""
    from server.services import skill_import
    files, texts = _read_tree(folder(key))
    raw = texts.get("SKILL.md")
    parsed = skill_import.parse_skill_md(raw, f"{key}/SKILL.md") if raw is not None else None
    if parsed is None:
        raise Unreadable("no valid SKILL.md")
    return {"files": files, "texts": texts, "info": parsed}


def _read_tree(base: Path) -> tuple[dict[str, str], dict[str, str]]:
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
            if name in _IGNORED:
                continue
            path = here / name
            try:
                mode = os.lstat(path).st_mode
            except OSError as exc:                  # gone between the listing and here
                raise Unreadable("a file can't be read") from exc
            if not stat.S_ISREG(mode):
                raise Unreadable("holds a link or a special file")
            if len(files) >= MAX_FILES:
                raise Unreadable("too many files")
            try:
                data = _read_file(path)
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
    up the server. The read is not under `manifest_lock()` (#808 review: one slow read held up every install, approval
    and folder-skill read). The rows and the manifest change under it, after it is taken: an approval or an install
    half done (its rows committed and its hashes not yet written, or the other way round) is waited for. A skill
    whose manifest entry changed while the folder was read (an install, an approval, a delete) is read again then."""
    before = entries()
    names, reads = await asyncio.to_thread(_list_and_read)
    async with manifest_lock():
        known = entries()
        moved = sorted(k for k in set(known) | set(before) if known.get(k) != before.get(k))
        if moved:
            names, reads = await asyncio.to_thread(_read_again, names, reads, moved)
        return await _sync(names, reads, known)


def _read_again(names: list[str], reads: dict, keys: list[str]) -> tuple[list[str], dict]:
    """`_list_and_read` again for `keys` only: what an Arslan writer changed while the folder was being read."""
    names, reads = set(names), dict(reads)
    for key in keys:
        if os.path.lexists(folder(key)):
            names.add(key)
            if key not in SEEDED:
                reads[key] = _read_or_none(key)
        else:
            names.discard(key)
            reads.pop(key, None)
    return sorted(names), reads


async def _sync(names: list[str], reads: dict, known: dict) -> dict[str, str]:
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
    if _matches(read, entries().get(key)):
        return read
    # A mismatch: compared again under the lock, so an approval in progress (its row on, its hashes not yet written)
    # is waited for instead of switched off.
    async with manifest_lock():
        if not _matches(read, entries().get(key)):
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
    # #795 review: under the lock from the first hash write to the last, so a reload (`sync`) or a read (`checked`)
    # in between waits for the hashes instead of finding the skill on and unapproved, and switching it off.
    async with manifest_lock():
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, key)
            if pack is None:
                raise NotApproved("not_found")
            info = read["info"]
            pack.name, pack.description, pack.body, pack.enabled = info["name"], info["description"], info["body"], True
            by = known[key].get("by") or OTHER
            # A re-approval clears the earlier hashes first: if the row commits and the new hashes never get
            # written, the folder (even back at the earlier files) reads as unapproved beside the new text, never as
            # approved.
            record(key, by=by, files=None)
            await db.commit()
        # After the commit: a commit that fails leaves the files unapproved. A stop before this line leaves them
        # unapproved too, and the next read switches the skill off (fail closed).
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
    want = _hashes(expected)
    if found != want:
        raise ValueError("the skill's folder does not match what was checked")
    return want


def _hashes(expected: dict[str, str]) -> dict[str, str]:
    return {rel: hashlib.sha256(text.encode("utf-8")).hexdigest() for rel, text in expected.items()}


def skill_md(name: str, description: str, body: str) -> str:
    """The SKILL.md Arslan writes for a skill it installs or exports: the row's text under a name/description
    frontmatter. Deterministic, so the export can tell its own folder from another's by the hashes alone."""
    head = yaml.safe_dump({"name": name, "description": description}, allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n\n{body}\n"


# ── the one-time export (CAP6a, second part) ───────────────────────────────────────────────────────────────────
#
# Skills imported before CAP6a (`SkillPack` rows with category "imported" or a `source_id`) have their scripts and
# references in <data>/skill_scripts/<key>/. `export_imported` moves each one that is switched on, at the same
# version, into ~/.agents/skills/<key>/ with part 1's install path (`write_new`: each file created new, then read
# back) and hash records (`record`, by Arslan). The rows are not changed: the manifest entry is what makes a row
# folder-backed. A skill the user switched off stays in the data folder (the shared folder would show it to other
# tools as available). Once a skill's folder passes the check after (count and hashes), its data-folder copy goes:
# there is never a second copy (the plan's decision 3); the backup keeps one.
#
# Where it runs: at start (server/main.py `_boot_skills`), after a cut-short plugin install is cleaned up
# (plugin_package.finish_interrupted: its parts are never exported, then removed) and before the folder is first
# read (`sync`) and before any request. Nothing else changes the rows or the folder then, so every skill goes over in
# one consistent state, and the start's `sync` already finds each exported skill "ok". Its file work runs in a worker
# thread (as `sync` reads the folder since #795): a large data folder or a slow disk never holds up the event loop.
#
# What happens if Arslan stops at each step (none of these states is ever read wrongly, and the next start finishes):
#  1. Making the backup: a `.partial` folder under <data>/backups. Nothing else changed. Next start: it goes, and the
#     backup is made again.
#  2. Backup made, record "running" not yet written: nothing changed but the backup. Next start: a new backup.
#  3. Writing a skill: its stage `~/.agents/skills/.arslan-export-<key>` (not a plain key: `sync` and every reader skip
#     it). The skill reads from the data folder as before. Next start: the stage goes and the skill is written again.
#  4. Moved into place, no hashes yet: a folder under its key with no manifest entry. `sync` leaves it alone (a skill
#     Arslan has from elsewhere is never shadowed), and the skill reads from the data folder. Next start: the folder
#     holds exactly the files the export writes (SKILL.md is deterministic), so it is taken as the export's own.
#  5. Hashes recorded, not yet checked: the skill is folder-backed, its files read back against the hashes when they
#     were written (from the original files). Next start: the record "running" lists its key, so it is checked then,
#     against those recorded hashes.
#  6. Checked, its data-folder copy being removed (all, part or none of it gone), record "done" not yet written: the
#     skill is folder-backed and runs from the folder, never from what is left of the copy. Next start: checked
#     again against its recorded hashes (the copy is not needed for that), and what is left of the copy goes.
#  7. Done: the export never runs again.
# A failure at any step but the backup leaves that one skill where it was (its manifest entry forgotten, its folder,
# when the export made it, to the Trash), working from the data folder, and the export goes on with the others. A
# failed backup changes nothing; the next start tries again. The data folder's copy goes only after its skill passed
# the check. After that, a lost manifest leaves the skill's row (its text still reads) but not its scripts: it fails
# closed (run_python finds nothing), as a skill installed since #795 does.

EXPORT_BACKUP = "cap6a-skill-export"
_STAGE = ".arslan-export-"
_SCRIPT_NAME = re.compile(r"[A-Za-z0-9._-]+\.py")
_REFERENCE_NAME = re.compile(r"[A-Za-z0-9._-]+\.(md|txt)")


class _Kept(Exception):
    """Why one skill stays in the data folder."""


def _data_folder(key: str) -> Path:
    from server import config
    return Path(config.data_dir()) / "skill_scripts" / key


def _candidate(pack: SkillPack, known: dict, running: set[str]) -> bool:
    imported = (pack.category == "imported" or pack.source_id is not None) and pack.category != OTHER_TOOL
    return (imported and pack.enabled is not False and plain_key(pack.key) and pack.key not in SEEDED
            and (pack.key not in known or pack.key in running))


def _old_files(key: str) -> dict[str, str]:
    """What today's readers take of a skill not yet exported, from <data>/skill_scripts/<key>/: its `.py` scripts
    (run_python) and its `.md`/`.txt` references (read_skill, the sandbox's read-only copies), by the names the import
    stores them under, as `scripts/<name>` and `references/<name>`. Raises _Kept for a link anywhere in it or a file
    that is not UTF-8 text (today's readers refuse both)."""
    base = _data_folder(key)
    try:
        if not stat.S_ISDIR(os.lstat(base).st_mode):
            raise _Kept("its files are not a plain folder")
    except FileNotFoundError:
        return {}
    found: dict[str, str] = {}
    for prefix, here, pattern in (("scripts/", base, _SCRIPT_NAME), ("references/", base / "references", _REFERENCE_NAME)):
        if prefix == "references/":
            try:
                if not stat.S_ISDIR(os.lstat(here).st_mode):
                    raise _Kept("its references are not a plain folder")
            except FileNotFoundError:
                continue
        for entry in sorted(os.scandir(here), key=lambda e: e.name):
            if entry.is_symlink():
                raise _Kept("its files hold a link")
            if entry.is_file(follow_symlinks=False) and pattern.fullmatch(entry.name):
                try:
                    found[prefix + entry.name] = _read_file(Path(entry.path)).decode("utf-8")
                except UnicodeDecodeError:
                    raise _Kept("a file is not UTF-8 text") from None
    return found


def _clear(path: Path) -> None:
    """The export's own stage or half backup (named by it, never another tool's): gone, a link itself only."""
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _write_rows(path: Path, rows: dict) -> None:
    path.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")


def _backup(packs: list[dict], olds: dict[str, dict[str, str]]) -> str:
    """Before anything moves: each candidate's row (its text included) and its whole data folder, under
    <data>/backups/, then read back. Made under a `.partial` name and renamed whole, so a backup that is there is
    complete. Raises (and changes nothing) on any failure. Returns its path under the data folder."""
    from server import config
    backups = Path(config.data_dir()) / "backups"
    if backups.is_symlink():
        raise OSError("the backups folder is a link")
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    for stale in backups.glob(f".{EXPORT_BACKUP}-*.partial"):
        _clear(stale)
    name = f"{EXPORT_BACKUP}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    partial = backups / f".{name}.partial"
    try:
        partial.mkdir(mode=0o700)
        rows = {}
        for pack in packs:
            key = pack["key"]
            if os.path.lexists(_data_folder(key)):
                shutil.copytree(_data_folder(key), partial / "skill_scripts" / key, symlinks=True)
            rows[key] = {**pack, "files": _hashes(olds.get(key, {}))}
        _write_rows(partial / "skills.json", rows)
        # Read back: every file the export copies is in the backup byte for byte, and so is every row.
        for key, files in olds.items():
            for rel, text in files.items():
                copy = partial / "skill_scripts" / key / rel.removeprefix("scripts/")
                if _read_file(copy) != text.encode("utf-8"):
                    raise OSError(f"the backup of {key}/{rel} does not match")
        if json.loads((partial / "skills.json").read_text(encoding="utf-8")) != rows:
            raise OSError("the backup of the rows does not match")
        os.rename(partial, backups / name)
    except BaseException:
        try:
            _clear(partial)
        except OSError:
            pass
        raise
    return f"backups/{name}"


def _export_one(key: str, expected: dict[str, str], want: dict[str, str]) -> None:
    """One skill into its folder, its hashes recorded. Raises _Kept, after undoing what it did, when it stays."""
    dest = folder(key)
    if os.path.lexists(dest):
        # Another tool's folder (never overwritten), or the export's own from a start cut short after its rename
        # (exactly the files it writes: taken back).
        try:
            ours = _read_tree(dest)[0] == want
        except Unreadable:
            ours = False
        if not ours:
            raise _Kept("clash")
        record(key, by=ARSLAN, files=want)
        return
    stage = root() / f"{_STAGE}{key}"
    try:
        _clear(stage)
        stage.mkdir(parents=True)
        write_new(stage, expected)                     # part 1's path: each file created new, then read back
        if os.path.lexists(dest):
            _clear(stage)
            raise _Kept("clash")
        os.rename(stage, dest)
    except _Kept:
        raise
    except Exception as exc:  # noqa: BLE001 — one skill's failure is that skill's: it stays where it was
        try:
            _clear(stage)
        except OSError:
            pass
        raise _Kept(f"failed ({type(exc).__name__})") from exc
    try:
        record(key, by=ARSLAN, files=want)
    except Exception as exc:  # noqa: BLE001
        from server.services import capability_install
        try:                                     # moved into place and never recorded: the export's own leftover
            capability_install.to_trash(dest, prefix="Arslan failed skill export")
        except OSError:
            pass
        raise _Kept(f"failed ({type(exc).__name__})") from exc


def _same(read: dict | None, want: dict[str, str]) -> bool:
    """The check after the export: the folder as read now holds the same files as the skill had (the count: no more,
    no fewer), and each one has the hash of what was copied."""
    if read is None:
        return False
    if sorted(read["files"]) != sorted(want):
        return False
    return all(read["files"][rel] == digest for rel, digest in want.items())


def _export(packs: list[dict], running: set[str]) -> dict:
    """The export's file work, in a worker thread. See the notes above `EXPORT_BACKUP` for each step."""
    from server.services import skill_import
    known = entries()
    kept: dict[str, str] = {}
    olds: dict[str, dict[str, str]] = {}
    for pack in packs:
        if pack["key"] in known:
            continue             # recorded by a start cut short: checked below against its recorded hashes
        try:
            olds[pack["key"]] = _old_files(pack["key"])
        except _Kept as why:
            kept[pack["key"]] = str(why)
        except OSError as exc:
            kept[pack["key"]] = f"its files can't be read ({type(exc).__name__})"
    backup = _backup(packs, olds)                    # first; a failure here raises, and nothing has changed
    _save(entries(), export={"state": "running", "keys": sorted({p["key"] for p in packs} | running),
                             "backup": backup})
    wants: dict[str, dict[str, str]] = {}
    for pack in packs:
        key = pack["key"]
        if key in kept:
            continue
        if key in known:
            # Its hashes were read back against the original files when they were written; its data-folder copy
            # may be gone already (step 6), so it is checked against them.
            wants[key] = dict(known[key].get("files") or {})
            continue
        expected = {**olds[key], "SKILL.md": skill_md(pack["name"] or key, pack["description"] or "",
                                                     (pack["body"] or "").strip())}
        wants[key] = _hashes(expected)
        if skill_import.parse_skill_md(expected["SKILL.md"], f"{key}/SKILL.md") is None:
            kept[key] = "its text is not a valid SKILL.md"
            continue
        try:
            _export_one(key, expected, wants[key])
        except _Kept as why:
            kept[key] = str(why)
    exported, left = [], []
    for key, want in sorted(wants.items()):
        if key in kept:
            continue
        entry = entries().get(key)
        if entry is not None and entry.get("by") == ARSLAN and _same(_read_or_none(key), want):
            exported.append(key)
            # Checked: the data folder's copy goes, so there is one copy (the backup keeps another). A copy that
            # can't go is left and reported; the skill runs from its folder either way.
            try:
                _clear(_data_folder(key))
            except OSError as exc:
                logger.warning("the data-folder copy of skill %s was not removed: %s", key, type(exc).__name__)
                left.append(key)
            continue
        forget(key)                                  # back to the data folder, which is still whole
        kept[key] = "check failed"
    if sorted(exported + list(kept)) != sorted(p["key"] for p in packs):
        raise RuntimeError("the export lost count of its skills")      # never: every candidate is in one of them
    report = {"state": "done", "exported": exported, "kept": dict(sorted(kept.items())), "backup": backup,
              "copies_left": left, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _save(entries(), export=report)
    return report


async def export_imported() -> dict | None:
    """The one-time export of skills imported before CAP6a (see the notes above `EXPORT_BACKUP`). None when it already
    ran; otherwise its report: `exported` (keys), `kept` ({key: why}: "clash" for a folder another tool has under the
    key, which is never overwritten, the skill keeping its copy in Arslan's data folder and database), `backup`.
    Raises when the backup fails, and then nothing has changed."""
    state = export_state()
    if state is not None and state.get("state") == "done":
        return None
    running = {k for k in (state or {}).get("keys") or [] if isinstance(k, str)}
    async with manifest_lock():
        known = entries()
        async with db_session.AsyncSessionLocal() as db:
            packs = [{"key": p.key, "name": p.name, "description": p.description, "body": p.body,
                      "category": p.category, "source_id": p.source_id, "enabled": p.enabled}
                     for p in (await db.execute(select(SkillPack).order_by(SkillPack.key))).scalars()
                     if _candidate(p, known, running)]
        if not packs:
            report = {"state": "done", "exported": [], "kept": {}, "backup": None, "copies_left": [],
                      "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            _save(entries(), export=report)
            return report
        report = await asyncio.to_thread(_export, packs, running)
    for key, why in report["kept"].items():
        logger.warning("skill %s stays in Arslan's data folder, not exported to ~/.agents/skills: %s", key, why)
    logger.info("skills exported to ~/.agents/skills: %d (kept in the data folder: %d)", len(report["exported"]),
                len(report["kept"]))
    return report


def export_notice() -> int:
    """How many skills the export moved, while the one line that tells the user (on the Capabilities page) has not
    been shown yet; 0 otherwise. The folder is shared, so other tools can now read and use them."""
    state = export_state()
    if not state or state.get("state") != "done" or state.get("notice_shown"):
        return 0
    return len(state.get("exported") or [])


def export_notice_shown() -> None:
    """The page showed the line: it never shows again (recorded in the export's record, in the data folder)."""
    state = export_state()
    if state and state.get("state") == "done" and not state.get("notice_shown"):
        _save(entries(), export={**state, "notice_shown": True})
