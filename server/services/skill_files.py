"""Skill folders on disk (0.1.61 §C1–§C3): one folder per held skill, `<data>/skills/<key>/`.

Commands read it from the sandbox and never write it. Copying is fail-closed: regular files only,
paths kept inside the folder, size caps, only the exec bit kept; staged, swapped in whole, and a
replaced folder goes to the Trash once the caller's database write committed.
"""
from __future__ import annotations

import difflib
import errno
import hashlib
import io
import logging
import os
import re
import shutil
import stat
import tarfile
import uuid
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
#: Names Arslan gives its own folders under <data>/skills/ while it swaps (skill_boot.tidy reads them).
STAGING_PREFIX, OLD_PREFIX, NEW_PREFIX = ".staging-", ".old-", ".new-"
MAX_FOLDER_BYTES = 20 * 1024 * 1024
MAX_FOLDER_FILES = 2000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
#: Members of one archive: each costs memory while it is read (0.94 MB of download held 200,000).
MAX_ENTRIES = 100_000
MAX_LIST = 200
#: What a skill's text may call its own folder (Claude Code, Agent Skills, OpenClaw).
PLACEHOLDERS = ("${CLAUDE_SKILL_DIR}", "${SKILL_DIR}", "{baseDir}")
_SKIP_NAMES = frozenset({".DS_Store"})
#: Folders that are never part of a skill: Python's caches, a checkout's history.
_SKIP_DIRS = frozenset({"__pycache__", ".git"})
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
#: Why a file of an archive could not be written, skipped rather than failing the skill: the same
#: name in another case or normalisation, a file where a folder must be, a path too long for the
#: disk, a name the disk refuses.
_SKIPPABLE = frozenset({errno.EEXIST, errno.ENOTDIR, errno.ENAMETOOLONG, errno.EILSEQ})


class FolderTooLarge(ValueError):
    """The skill's folder is over the size or file-count limit: nothing was copied."""


class BadArchive(ValueError):
    """The download is not a readable GitHub archive, or it is too large to read."""


def skills_root() -> Path:
    from server import config
    return config.data_dir() / "skills"


def folder_for(key: str) -> Path:
    if not KEY_RE.fullmatch(key or ""):
        raise ValueError(f"not a skill key: {key!r}")
    return skills_root() / key


def safe_relpath(rel: str) -> str | None:
    """`rel` as a clean relative POSIX path, or None when it could leave the folder or is not a
    plain name: absolute, `..`, empty parts, NUL, a backslash, a part over 255 bytes, a name that
    was not UTF-8."""
    if not rel or "\x00" in rel or "\\" in rel:
        return None
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:                 # not UTF-8 in the repository (surrogateescape)
        return None
    path = PurePosixPath(rel)
    if path.is_absolute():
        return None
    parts = list(path.parts)
    if not parts or any(p in ("", ".", "..") or len(p.encode("utf-8")) > 255 for p in parts):
        return None
    return "/".join(parts)


def _shown(name: str) -> str:
    """A name as it can be shown and sent as JSON (bytes that were not UTF-8 become \\udcff)."""
    return name.encode("utf-8", "backslashreplace").decode("utf-8")


# ── the archive ───────────────────────────────────────────────────────────────

@dataclass
class Entry:
    path: str          # relative to the archive's top folder, POSIX
    kind: str          # file | dir | link | other
    size: int
    mode: int
    data: bytes | None = None


@dataclass
class Archive:
    commit: str
    entries: dict[str, Entry] = field(default_factory=dict)

    def under(self, folder: str) -> list[Entry]:
        prefix = f"{folder}/" if folder else ""
        return [e for p, e in self.entries.items() if e.kind != "dir" and p.startswith(prefix)]

    def text(self, path: str) -> str | None:
        entry = self.entries.get(path)
        if entry is None or entry.kind != "file" or entry.data is None:
            return None
        return entry.data.decode("utf-8", "replace")

    def skill_mds(self, subpath: str = "") -> list[str]:
        sub = subpath.strip("/")
        return sorted(p for p, e in self.entries.items() if e.kind == "file"
                      and (p == "SKILL.md" or p.endswith("/SKILL.md"))
                      and safe_relpath(p) is not None
                      and (not sub or p == f"{sub}/SKILL.md" or p.startswith(f"{sub}/")))


def read_archive(data: bytes, *, keep: Callable[[str], bool], keep_limit: int | None = None) -> Archive:
    """One pass over a GitHub tar.gz (codeload): every member's path, kind, size and mode, and the
    bytes of the members `keep` asks for — at most `keep_limit` bytes of them (default: one skill
    folder's budget; a scan of a whole repository passes more). GitHub writes the commit into the
    global pax header. Headers and the data of every member count toward MAX_UNPACKED_BYTES, and
    the stream is read to its end, where gzip checks its CRC-32 and length."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise BadArchive("the repository archive is larger than 64 MB")
    out = Archive(commit="")
    kept = seen = 0
    limit = keep_limit if keep_limit is not None else MAX_FOLDER_BYTES + 2 * 1024 * 1024
    mb = limit // (1024 * 1024)
    over = ("the skill's folder is larger than 20 MB" if keep_limit is None
            else f"what is read from the repository archive is larger than {mb} MB")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                # tar.offset: where this member's data ends in the inflated stream — headers, long
                # names and the data of every member, read or skipped — checked before tarfile
                # inflates its way past it. Not covered: tarfile reads a pax or GNU long-name header
                # whole, at its declared size, before this runs (git archive never writes a large
                # one; a size-bounded reader under tarfile would close it).
                if tar.offset > MAX_UNPACKED_BYTES:
                    raise BadArchive("the repository archive unpacks to more than 512 MB")
                seen += 1
                if seen > MAX_ENTRIES:
                    raise BadArchive(f"the repository archive has over {MAX_ENTRIES:,} entries")
                name = member.name.split("/", 1)[1] if "/" in member.name else ""
                name = name.rstrip("/")
                if not name:
                    continue                                    # the archive's top folder
                kind = ("file" if member.isreg() else "dir" if member.isdir()
                        else "link" if (member.issym() or member.islnk()) else "other")
                entry = Entry(path=name, kind=kind, size=member.size if kind == "file" else 0, mode=member.mode)
                if kind == "file" and keep(name):
                    kept += entry.size
                    if kept > limit:
                        raise FolderTooLarge(over)
                    handle = tar.extractfile(member)
                    entry.data = handle.read() if handle is not None else b""
                out.entries[name] = entry
            out.commit = str((tar.pax_headers or {}).get("comment") or "")
            rest = MAX_UNPACKED_BYTES - tar.offset
            while chunk := tar.fileobj.read(1 << 20):      # to the end, where gzip checks the CRC
                rest -= len(chunk)
                if rest < 0:
                    raise BadArchive("the repository archive unpacks to more than 512 MB")
    except (tarfile.TarError, OSError, EOFError, ValueError, zlib.error, RecursionError) as exc:
        # zlib.error: a broken deflate stream (tarfile converts it only around a header read).
        # RecursionError: a chain of pax or GNU long-name headers (tarfile reads them recursively).
        if isinstance(exc, (BadArchive, FolderTooLarge)):
            raise
        raise BadArchive(f"not a readable archive: {exc}") from None
    return out


# ── staging ───────────────────────────────────────────────────────────────────

@dataclass
class Staged:
    path: Path
    files: dict[str, str]            # relative path -> sha256
    skipped: list[str]
    bytes: int = 0


def _new_staging() -> Path:
    root = skills_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{STAGING_PREFIX}{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o755)
    return path


def _write(staging: Path, rel: str, data: bytes, executable: bool) -> str:
    dest = staging.joinpath(*rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    base, parent = staging.resolve(), dest.parent.resolve()
    if parent != base and base not in parent.parents:
        raise ValueError(f"{rel} leaves the skill's folder")
    mode = 0o755 if executable else 0o644
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(dest, mode)                       # the umask must not take the bit away
    return hashlib.sha256(data).hexdigest()


def stage(archive: Archive, folder: str) -> Staged:
    """Copy `folder` of the archive (every file under it) into a new staging folder."""
    prefix = f"{folder}/" if folder else ""
    entries = archive.under(folder)
    files = sorted((e for e in entries if e.kind == "file"), key=lambda e: e.path)
    if len(files) > MAX_FOLDER_FILES:
        raise FolderTooLarge(f"the skill's folder has more than {MAX_FOLDER_FILES} files")
    if sum(e.size for e in files) > MAX_FOLDER_BYTES:
        raise FolderTooLarge("the skill's folder is larger than 20 MB")
    out = Staged(path=_new_staging(), files={},
                 skipped=sorted(_shown(e.path[len(prefix):])
                                for e in entries if e.kind in ("link", "other")))
    try:
        for entry in files:
            rel = safe_relpath(entry.path[len(prefix):])
            if (rel is None or rel.rsplit("/", 1)[-1] in _SKIP_NAMES
                    or _SKIP_DIRS.intersection(rel.split("/")[:-1])):
                out.skipped.append(_shown(entry.path[len(prefix):]))
                continue
            if entry.data is None:
                raise ValueError(f"{entry.path} was not read from the archive")
            try:
                out.files[rel] = _write(out.path, rel, entry.data, bool(entry.mode & 0o111))
            except OSError as exc:
                if exc.errno not in _SKIPPABLE:
                    raise
                out.skipped.append(rel)
                continue
            out.bytes += len(entry.data)
        out.files = checksums(out.path)       # the names as on disk: a case twin's folder is one
    except BaseException:
        discard(out)
        raise
    return out


def stage_texts(files: dict[str, str], *, skill_md: str) -> Staged:
    """A folder from text (a skill saved from chat): SKILL.md and the draft's files. A file that
    starts with `#!` is made executable."""
    out = Staged(path=_new_staging(), files={}, skipped=[])
    try:
        items = {"SKILL.md": skill_md, **{k: v for k, v in files.items() if k != "SKILL.md"}}
        for rel, text in sorted(items.items()):
            clean = safe_relpath(rel)
            if clean is None:
                raise ValueError(f"not a file name inside the skill: {rel!r}")
            data = text.encode("utf-8")
            try:
                out.files[clean] = _write(out.path, clean, data, text.startswith("#!"))
            except OSError as exc:
                if exc.errno not in _SKIPPABLE:
                    raise
                raise ValueError(f"{clean} clashes with another file of the skill (a name in "
                                 "another case, or a file where a folder is), or the disk "
                                 "refuses it") from None
            out.bytes += len(data)
    except BaseException:
        discard(out)
        raise
    return out


def stage_tree(src: Path) -> Staged:
    """A copy of a folder on this Mac (a bundled seed, an old import): regular files only."""
    # Parked (review): lstat then read_bytes() can race a swap to a link; bundled seeds only.
    out = Staged(path=_new_staging(), files={}, skipped=[])
    try:
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            here = Path(dirpath)
            for name in sorted(dirnames):
                if (here / name).is_symlink():
                    out.skipped.append((here / name).relative_to(src).as_posix())
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not (here / d).is_symlink())
            for name in sorted(filenames):
                full = here / name
                rel = full.relative_to(src).as_posix()
                info = full.lstat()
                if not stat.S_ISREG(info.st_mode) or name in _SKIP_NAMES:
                    out.skipped.append(rel)
                    continue
                if len(out.files) >= MAX_FOLDER_FILES or out.bytes + info.st_size > MAX_FOLDER_BYTES:
                    raise FolderTooLarge("the folder is over the skill size limit")
                data = full.read_bytes()
                out.files[rel] = _write(out.path, rel, data, bool(info.st_mode & 0o111))
                out.bytes += len(data)
    except BaseException:
        discard(out)
        raise
    return out


def discard(staged: Staged) -> None:
    shutil.rmtree(staged.path, ignore_errors=True)        # Arslan's own scratch copy, never a skill


# ── swapping ──────────────────────────────────────────────────────────────────

def swap_in(staged: Staged, key: str) -> Path | None:
    """Put the staged folder where `key`'s folder is. Returns the folder it replaced, moved aside on
    the same disk, for the caller to `retire` once its database write committed — or to put back
    with `swap_back` when it did not."""
    final = folder_for(key)
    aside = None
    if final.exists() or final.is_symlink():
        aside = final.with_name(f"{OLD_PREFIX}{key}-{uuid.uuid4().hex[:8]}")
        os.replace(final, aside)
    try:
        os.replace(staged.path, final)
    except BaseException:
        if aside is not None:
            os.replace(aside, final)
        raise
    return aside


def swap_back(key: str, aside: Path | None) -> None:
    """Undo `swap_in` after the caller's database write failed. The old folder comes back FIRST
    (two renames on one disk), then the new copy — Arslan's own, made a moment ago from the
    archive — is deleted. Nothing here needs the Trash, so a Trash that cannot be reached never
    strands the old folder or hides the database's error (Ruling E)."""
    final = folder_for(key)
    new = None
    if final.exists() or final.is_symlink():
        new = final.with_name(f"{NEW_PREFIX}{key}-{uuid.uuid4().hex[:8]}")
        os.replace(final, new)
    if aside is not None:
        os.replace(aside, final)
    if new is not None:
        shutil.rmtree(new, ignore_errors=True)


def _trash_name(path: Path) -> str:
    """What the folder is called in the Trash. A name that starts with a dot is hidden in
    Finder, so a person could never find a replaced skill there."""
    name = path.name
    if name.startswith(OLD_PREFIX):
        return f"skill {name[len(OLD_PREFIX):].rsplit('-', 1)[0]} (replaced)"
    if path.parent.name == "skill_scripts":
        return f"skill {name} (scripts from before 0.1.61)"
    return f"skill {name.lstrip('.')}"


def _trash(path: Path) -> None:
    from server.services import capability_install
    capability_install.to_trash(path, name=_trash_name(path))


def retire(path: Path | None) -> None:
    """A folder Arslan no longer uses goes to the Trash (never deleted outright). When the Trash
    cannot be reached the folder stays where it is, logged; the next start tries again
    (skill_boot.tidy). Retiring never fails the work that came before it."""
    if path is None or not (path.exists() or path.is_symlink()):
        return
    try:
        _trash(path)
    except OSError:
        logger.warning("could not move %s to the Trash; it stays until the next start", path, exc_info=True)


# ── reading ───────────────────────────────────────────────────────────────────

def _walk_files(folder: Path) -> Iterator[tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not (here / d).is_symlink())
        for name in sorted(filenames):
            full = here / name
            if name in _SKIP_NAMES or full.is_symlink() or not full.is_file():
                continue
            yield full.relative_to(folder).as_posix(), full


def checksums(folder: Path | None) -> dict[str, str]:
    if folder is None or not folder.is_dir():
        return {}
    return {rel: hashlib.sha256(full.read_bytes()).hexdigest() for rel, full in _walk_files(folder)}


def list_files(folder: Path | None, limit: int = MAX_LIST) -> tuple[list[str], int]:
    if folder is None or not folder.is_dir():
        return [], 0
    names = sorted(rel for rel, _ in _walk_files(folder))
    return names[:limit], len(names)


def has_scripts(folder: Path | None) -> bool:
    """Whether the skill ships scripts (any file under scripts/): they run as commands."""
    # Parked (review): follows a symlinked scripts/ that list_files hides; it is only a flag.
    scripts = folder / "scripts" if folder is not None else None
    if scripts is None or not scripts.is_dir():
        return False
    return next(_walk_files(scripts), None) is not None


def read_text(folder: Path, rel: str, *, limit: int) -> str | None:
    """One file of the skill's folder as text, or None when `rel` is not a file inside it (no
    `..`, no absolute path, no link that leads out)."""
    clean = safe_relpath(rel)
    if clean is None:
        return None
    base = folder.resolve()
    target = (folder / clean).resolve()
    if base not in target.parents or not target.is_file():
        return None
    with target.open("rb") as handle:
        data = handle.read(limit * 4 + 4)
    return data.decode("utf-8", "replace")[:limit]


def substitute(body: str, folder: Path) -> str:
    for token in PLACEHOLDERS:
        body = body.replace(token, str(folder))
    return body


def changes(old_files: dict[str, str], new_files: dict[str, str], old_md: str, new_md: str) -> dict:
    """What a re-import changed: files added, removed and changed, and the SKILL.md diff."""
    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    changed = sorted(p for p in set(old_files) & set(new_files) if old_files[p] != new_files[p])
    diff = list(difflib.unified_diff(old_md.splitlines(), new_md.splitlines(), "SKILL.md (before)",
                                     "SKILL.md (now)", lineterm="", n=2))
    return {"added": added, "removed": removed, "changed": changed,
            "files_changed": len(added) + len(removed) + len(changed),
            "skill_md_diff": "\n".join(diff[:400])}
