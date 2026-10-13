"""Skills at boot (0.1.61 §C2): what a crash in the middle of a swap left is tidied; imports from
before 0.1.61 (`<data>/skill_scripts/<key>/`, flat scripts) move into
`<data>/skills/<key>/scripts|references/` and lose their run_python lists; the bundled seeds that
carry files get their folder, copied again when the app ships new files. Every step is idempotent
and restartable, and no step's failure stops another.

Nothing here deletes a folder. What is not wanted any more goes to the Trash (`skill_files.retire`),
and a Trash that cannot be reached leaves it where it is for the next start (Ruling E).

Tidy decides by the database, not by a folder's name: the live folder of a skill is the one whose
files are the ones its committed row describes (the dossier's checksums for an import, the app's own
files for a bundled seed). A folder moved aside by a swap that died before its row committed is put
back; one moved aside by a swap that committed is thrown away. Where the row cannot say, nothing is
touched.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.services import skill_files

logger = logging.getLogger(__name__)

_BUNDLED_LIST = re.compile(r"^##\s+Bundled (scripts|references)\b", re.I)
#: The names skill_files gives its scratch folders: `.staging-<12 hex>`, `.old-<key>-<8 hex>`,
#: `.new-<key>-<8 hex>`. A folder with any other name is not Arslan's and is left alone.
_STAGING = re.compile(r"\.staging-[0-9a-f]{12}")
_SUFFIX = re.compile(r"[0-9a-f]{8}")
#: Rows whose folder is Arslan's own to keep: a shared-folder skill's row points at someone else's.
_OWN_ORIGINS = ("saved", "imported")


def strip_bundled_lists(body: str) -> str:
    """The old importer's two appended lists, taken out; every other section stays."""
    out: list[str] = []
    skipping = False
    for line in (body or "").splitlines():
        stripped = line.strip()
        if _BUNDLED_LIST.match(stripped):
            skipping = True
            continue
        if skipping and stripped.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip()


# ── tidying a crash ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Known:
    """The files a committed row says its folder holds, path in the folder → sha256."""
    files: dict[str, str]
    #: A dossier written before 0.1.61 names SKILL.md, which the folder moved from `skill_scripts`
    #: never held.
    moved_import_ok: bool = False

    def matches(self, folder: Path) -> bool:
        found = skill_files.checksums(folder)         # {} for what is not a folder
        if not found:
            return False                                # an empty folder is nobody's copy
        if found == self.files:
            return True
        return self.moved_import_ok and found == {p: s for p, s in self.files.items() if p != "SKILL.md"}


def _dossier_files(files) -> dict[str, str] | None:
    """A dossier names every file by its path in the repository. The skill's folder starts where
    its own SKILL.md is (the topmost one): the paths in the folder are what comes after."""
    if not isinstance(files, dict) or not files or not all(
            isinstance(p, str) and isinstance(s, str) for p, s in files.items()):
        return None
    tops = [p for p in files if p == "SKILL.md" or p.endswith("/SKILL.md")]
    if not tops:
        return None
    prefix = min(tops, key=len)[:-len("SKILL.md")]
    if not all(p.startswith(prefix) for p in files):
        return None
    return {p[len(prefix):]: s for p, s in files.items()}


async def _known_for(db, pack: SkillPack) -> _Known | None:
    if pack.origin == "bundled":
        from server.registry.seeder import _SEEDS_DIR
        files = skill_files.checksums(_SEEDS_DIR / pack.key)
        return _Known(files) if set(files) - {"SKILL.md"} else None     # a seed with no files has no folder
    if not pack.source_id:
        return None
    dossier = await db.get(CapabilitySource, pack.source_id)
    if dossier is None or dossier.kind != "skill" or dossier.skill_key != pack.key:
        return None
    files = _dossier_files(dossier.files)
    return _Known(files, moved_import_ok=True) if files else None


async def _known(key: str) -> tuple[bool, _Known | None]:
    """(whether a row holds this key, what that row says its folder holds)."""
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is None:
            return False, None
        return True, await _known_for(db, pack)


async def _dangling() -> dict[str, _Known]:
    """The rows that expect their folder where Arslan keeps it, and it is not there."""
    out: dict[str, _Known] = {}
    async with db_session.AsyncSessionLocal() as db:
        for pack in (await db.execute(select(SkillPack))).scalars().all():
            if not skill_files.KEY_RE.fullmatch(pack.key or ""):
                continue
            folder = skill_files.folder_for(pack.key)
            if pack.folder != str(folder) or folder.exists() or folder.is_symlink():
                continue
            known = await _known_for(db, pack)
            if known is not None:
                out[pack.key] = known
    return out


def _leftover_key(name: str, prefix: str) -> str | None:
    """`.old-<key>-<8 hex>` or `.new-<key>-<8 hex>` -> the key. Any other name is not Arslan's."""
    if not name.startswith(prefix):
        return None
    key, _, suffix = name[len(prefix):].rpartition("-")
    if _SUFFIX.fullmatch(suffix) and skill_files.KEY_RE.fullmatch(key):
        return key
    return None


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _retire_all(paths: list[Path]) -> list[str]:
    """To the Trash; the names of those that left (a Trash that cannot be reached keeps them)."""
    gone = []
    for path in paths:
        skill_files.retire(path)
        if not _present(path):
            gone.append(path.name)
    return gone


def _put_back(key: str, chosen: Path) -> Path | None:
    """`chosen`, a copy the row describes, becomes the key's folder. What is there instead is not
    what the row describes: it is moved aside first (a rename on this disk, so a Trash that cannot
    be reached never strands the good copy) and returned for the Trash."""
    final = skill_files.folder_for(key)
    aside = None
    if _present(final):
        aside = final.with_name(f"{skill_files.NEW_PREFIX}{key}-{uuid.uuid4().hex[:8]}")
        os.replace(final, aside)
    os.replace(chosen, final)
    return aside


async def _settle(key: str) -> list[str]:
    """Everything a swap of `key` left, decided by the key's row. Called with the key's lock held."""
    root = skill_files.skills_root()
    final = skill_files.folder_for(key)
    entries = sorted(root.iterdir())
    olds = [p for p in entries if _leftover_key(p.name, skill_files.OLD_PREFIX) == key]
    news = [p for p in entries if _leftover_key(p.name, skill_files.NEW_PREFIX) == key]
    if not olds and not news:
        return []
    has_row, known = await _known(key)
    if not has_row:                                     # no row points at any copy
        return _retire_all(olds + news)
    if known is None:
        # A row that records nothing about its files cannot tell which copy is live. The one case
        # with an answer: the folder is gone and exactly one copy was moved aside — it is the
        # folder as it was before the swap.
        if not _present(final) and len(olds) == 1:
            os.replace(olds[0], final)
            return [olds[0].name] + _retire_all(news)
        logger.warning("skill %s: %d folder(s) left by a swap, and its row says nothing about its files; "
                       "left as they are", key, len(olds) + len(news))
        return []
    if known.matches(final):                            # the committed copy is in place: the rest is spare
        return _retire_all(olds + news)
    chosen = next((p for p in olds + news if known.matches(p)), None)
    if chosen is None:
        logger.warning("skill %s: no folder left by a swap matches its row; left as they are", key)
        return []
    aside = _put_back(key, chosen)
    done = [chosen.name] + _retire_all([p for p in olds + news if p != chosen])
    if aside is not None:
        _retire_all([aside])                            # what was in place is not what the row describes
    return done


async def _settle_stagings() -> list[str]:
    """A half-built copy goes to the Trash — unless it is the committed copy of a row whose folder
    is missing, then it takes the folder's place."""
    root = skill_files.skills_root()
    stagings = [p for p in sorted(root.iterdir()) if _STAGING.fullmatch(p.name)]
    if not stagings:
        return []
    done: list[str] = []
    claims = await _dangling()
    for staging in stagings:
        for key, known in list(claims.items()):
            if not known.matches(staging):
                continue
            async with skill_files.key_lock(key):
                final = skill_files.folder_for(key)
                if _present(final):
                    continue
                os.replace(staging, final)
            del claims[key]
            done.append(staging.name)
            break
        else:
            done.extend(_retire_all([staging]))
    return done


async def tidy() -> list[str]:
    """What a crash in the middle of a swap left under <data>/skills/, dealt with; the names found.

    `.old-<key>-*` and `.new-<key>-*` are settled per key under the key's lock, by what the key's
    row describes (`_settle`); `.staging-*` after them (`_settle_stagings`). Runs before anything
    can import."""
    root = skill_files.skills_root()
    if root.is_symlink() or not root.is_dir():
        return []
    keys = sorted({k for p in root.iterdir()
                   for k in (_leftover_key(p.name, skill_files.OLD_PREFIX),
                             _leftover_key(p.name, skill_files.NEW_PREFIX)) if k})
    done: list[str] = []
    for key in keys:
        try:
            async with skill_files.key_lock(key):
                done += await _settle(key)
        except Exception:  # noqa: BLE001 — one key that cannot be tidied never stops the others
            logger.warning("could not tidy what a swap of skill %s left", key, exc_info=True)
    done += await _settle_stagings()
    return sorted(done)


# ── old imports move ───────────────────────────────────────────────────────────

def _legacy_root() -> Path:
    from server import config
    return config.data_dir() / "skill_scripts"


def _legacy_pairs(old: Path) -> list[tuple[str, Path]]:
    """The old importer's layout: flat scripts beside a references/ folder."""
    pairs = [(f"scripts/{p.name}", p) for p in sorted(old.iterdir()) if p.name != "references"]
    refs = old / "references"
    if refs.is_dir() and not refs.is_symlink():
        pairs += [(f"references/{p.name}", p) for p in sorted(refs.iterdir())]
    return pairs


async def _point_row_at(key: str, new: Path) -> None:
    """The old import's row: its folder, its body without the run_python lists, its origin. Also
    what finishes a move a crash interrupted (the folder moved, the row did not). A row that is
    not Arslan's own (a shared-folder skill's) is left alone."""
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is None or pack.origin not in _OWN_ORIGINS or pack.folder == str(new):
            return
        pack.folder = str(new)
        if pack.category == "imported":
            pack.origin = "imported"
            if pack.body:
                pack.body = strip_bundled_lists(pack.body)
        await db.commit()


async def _move_one(old: Path, key: str) -> None:
    new = skill_files.folder_for(key)
    if not _present(new):                               # a folder already there is never replaced
        staged = await asyncio.to_thread(skill_files.stage_files, _legacy_pairs(old))
        if staged.files:
            try:
                aside = skill_files.swap_in(staged, key)
            except BaseException:
                skill_files.discard(staged)
                raise
            skill_files.retire(aside)                   # None: nothing was there
        else:
            skill_files.discard(staged)                 # nothing a skill can hold: no empty folder
    if new.is_dir():
        await _point_row_at(key, new)
    skill_files.retire(old)                             # the Trash, whole: what was not copied is not lost


async def migrate_legacy_imports() -> list[str]:
    """Each key moves on its own, under its lock; a move a crash interrupted is finished (the
    folder is already there: the row is pointed at it, the old one retired)."""
    root = _legacy_root()
    if root.is_symlink() or not root.is_dir():
        return []
    moved: list[str] = []
    for old in sorted(root.iterdir()):
        key = old.name
        if old.is_symlink() or not old.is_dir() or not skill_files.KEY_RE.fullmatch(key):
            continue
        try:
            async with skill_files.key_lock(key):
                await _move_one(old, key)
        except Exception:  # noqa: BLE001 — one skill that cannot move never stops the others
            logger.warning("could not move the old import %s; it stays in skill_scripts", key, exc_info=True)
            continue
        if not _present(old):
            moved.append(key)
    try:
        root.rmdir()                                    # an empty folder, once everything moved
    except OSError:
        pass
    return moved


# ── the bundled seeds ──────────────────────────────────────────────────────────

async def _set_folder(key: str, folder: Path) -> None:
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        if pack is not None and pack.folder != str(folder):
            pack.folder = str(folder)
            await db.commit()


async def _install_one(key: str, src: Path, want: dict[str, str]) -> bool:
    async with skill_files.key_lock(key):
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, key)
        if pack is None or pack.origin != "bundled":    # a person's own skill of that name: never touched
            return False
        dest = skill_files.folder_for(key)
        if skill_files.checksums(dest) == want:
            await _set_folder(key, dest)
            return False
        staged = await asyncio.to_thread(skill_files.stage_tree, src)
        aside = skill_files.swap_in(staged, key)
        try:
            await _set_folder(key, dest)
        except BaseException:
            skill_files.swap_back(key, aside)
            raise
        skill_files.retire(aside)                       # the folder it replaced may hold a person's files
        return True


async def install_bundled() -> list[str]:
    """The bundled seeds that carry files get <data>/skills/<key>/, copied again when the app's
    files differ. Only for a key whose row is the bundled one (seeder): a person's own skill of
    that name, and its folder, are never touched. One seed that fails never stops the others."""
    from server.registry.seed_catalog import SKILLS
    from server.registry.seeder import _SEEDS_DIR
    copied: list[str] = []
    for key, *_ in SKILLS:
        src = _SEEDS_DIR / key
        want = skill_files.checksums(src)
        if set(want) <= {"SKILL.md"}:
            continue                                    # nothing beside SKILL.md: no folder
        try:
            if await _install_one(key, src, want):
                copied.append(key)
        except Exception:  # noqa: BLE001 — a seed that cannot be installed is logged, the boot goes on
            logger.warning("could not install the bundled skill %s", key, exc_info=True)
    return copied


async def run() -> dict:
    """The three steps, each on its own: a failure in one is logged and never stops the next."""
    out: dict[str, list[str]] = {"tidied": [], "moved": [], "installed": []}
    for name, step in (("tidied", tidy), ("moved", migrate_legacy_imports), ("installed", install_bundled)):
        try:
            out[name] = await step()
        except Exception:  # noqa: BLE001 — a skills step must never break the boot or the next step
            logger.warning("skills boot step %s failed (non-fatal)", name, exc_info=True)
    if any(out.values()):
        logger.info("skills at boot: tidied %s, moved %s, installed %s", out["tidied"], out["moved"], out["installed"])
    return out
