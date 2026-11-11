"""CAP8-2: the skills and plugins the user has in Claude Code, copied in by the user's click (§CAP8).

Only the import routes in `api/capabilities` reach this: no model tool, job or prompt does, and nothing here goes in the
model's context. It reads, and never writes:

- **Skills:** `~/.claude/skills/<name>/SKILL.md` and the files beside it (https://code.claude.com/docs/en/skills). A
  folder there holding `.claude-plugin/plugin.json` is a plugin, as Claude Code reads it (its `@skills-dir`).
- **Plugins:** `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, one folder per installed version, and the
  entry naming it in `~/.claude/plugins/marketplaces/<marketplace>/.claude-plugin/marketplace.json`
  (https://code.claude.com/docs/en/plugins/loading.md, https://code.claude.com/docs/en/plugins/marketplace-reference.md).
  A version folder Claude Code marked `.orphaned_at` is an old one, and isn't listed.
- **Codex:** its user skills are in `$HOME/.agents/skills` (https://learn.chatgpt.com/docs/build-skills), the folder
  CAP6a already reads in place, so there is nothing to copy. Where Codex keeps an installed plugin isn't in its docs, so
  its plugins are left out.

What comes in is Arslan's own copy, so it can be deleted like anything Arslan installed; the other tool's files stay
as they are.

- **A skill** goes through CAP6a's install (`skill_import.install_prepared`): into `~/.agents/skills/<key>/`, every
  file hashed in Arslan's data folder, scanned first (blocked is refused). It lands off and unapproved, so its first
  switch-on shows CAP6a's card.
- **A plugin** goes through CAP7b (`plugin_package.prepare_read`, `install`): commands, agents, language servers or a
  part not recognised refuse it, each connection is locked, its skills are scanned. Its card comes before the install:
  the first `add` answers `card`, and one sent back with that card's digest installs exactly it. Its marketplace entry
  may only describe it (CAP7b's phonebook rule): an entry can add parts, hooks among them, the cached folder doesn't
  show. A plugin starts unticked on the sheet.
- **Hooks, by the user's rule (2026-11-10):** judged by the event's name only, never by what a hook runs
  (`plugin_package.QUIET_HOOK_EVENTS`). A plugin or skill whose hooks all fire on one of the 16 quiet events comes in,
  and its hooks are never registered or run: nothing in Arslan runs a hook, and none is copied anywhere (a plugin's
  folder isn't kept, and a skill's frontmatter hooks are stripped, since Arslan writes a SKILL.md of its own with the
  name and description only). Any other event, or one not recognised, refuses it before anything is prepared. The
  card names each hook's event. After an update in the other tool, the sheet's scan judges it again: a blocking hook
  added since switches the installed plugin off, its switch stays off, and only its card brings it back (`add`
  installs the new group, then removes the old one). This is the only time it can be judged again: Arslan's copy
  never changes without a re-import, and only the user's click reads the other tool's folders. The same rule holds
  for a skill's frontmatter hooks wherever a skill comes in (`skill_import.frontmatter_hooks`).
- Neither is held to the one-click list or the license gate, as CAP8-1's connections aren't: this click is the
  deliberate one, and it's the user's own copy, not a redistribution.
- **Skipped or unticked:** one already here (a skill of that key, a folder of that key in `~/.agents/skills`, a plugin
  of that name) is skipped, and the second copy of a skill or plugin is listed unticked (`same_as`).

**Stated limits:** a folder that is a link or holds one is refused, though Claude Code accepts a linked skill folder.
A SKILL.md with no `name` or `description` is refused (the open standard needs both; Claude Code doesn't). A skill
brings `scripts/*.py` and `references/*.md|txt`, as from GitHub; `left` says how many other files stay behind.
`CLAUDE_CODE_PLUGIN_CACHE_DIR` isn't read. A marketplace added from a local folder has no copy under `marketplaces/`,
so its plugins are refused. `node_modules`, `__pycache__`, `.git` and `.mcpb-cache` are what running a plugin makes,
and aren't read. A file over 5 MB refuses its folder (never cut), and no more than MAX_ITEMS folders are read.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.orchestrator import untrusted
from server.services import agent_skills, plugin_hooks, plugin_package, skill_import
from server.services.plugin_package import Refused, Snapshot
from server.services.skill_forge import MAX_SKILL_BYTES

logger = logging.getLogger(__name__)

TOOL = "claude_code"
SOURCE = "import"
FROM = "Claude Code"
MAX_ITEMS = 200
MAX_FILES = 500
MAX_BYTES = 30 * 1024 * 1024
_MADE_BY_RUNNING = frozenset({"__pycache__", "node_modules", ".git", ".mcpb-cache"})
_PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
#: Keyed, as CAP8-1's: a restart only means scanning again.
_DIGEST_KEY = secrets.token_bytes(32)
_ONE_AT_A_TIME = asyncio.Lock()


def _keyed(*parts) -> str:
    return hmac.new(_DIGEST_KEY, json.dumps(parts, sort_keys=True, default=str).encode(), "sha256").hexdigest()


def _claude() -> Path:
    return Path.home() / ".claude"


# ── reading, never writing ───────────────────────────────────────────────────────────────────────────────────────

def _read_local(base: Path) -> dict[str, bytes]:
    """Every file of one folder by its plain relative path. A link anywhere, the folder itself included, or a special
    file refuses it, and each file is opened without following one. Raises Refused."""
    try:
        if not stat.S_ISDIR(os.lstat(base).st_mode):
            raise Refused("unreadable", "a link or not a folder")
        files: dict[str, bytes] = {}
        total = 0
        for current, dirs, names in os.walk(base, followlinks=False):
            here = Path(current)
            if any((here / name).is_symlink() for name in dirs):
                raise Refused("unreadable", "holds a link")
            dirs[:] = sorted(name for name in dirs if name not in _MADE_BY_RUNNING)
            for name in sorted(names):
                path = here / name
                rel = path.relative_to(base).as_posix()
                if not stat.S_ISREG(os.lstat(path).st_mode) or not skill_import._plain_path(rel):
                    raise Refused("unreadable", "holds a link or an odd name")
                if len(files) >= MAX_FILES:
                    raise Refused("too_large", "files")
                try:
                    files[rel] = agent_skills._read_file(path)
                except agent_skills.TooLarge as exc:
                    raise Refused("too_large", rel) from exc
                total += len(files[rel])
                if total > MAX_BYTES:
                    raise Refused("too_large", "bytes")
        return files
    except OSError as exc:
        raise Refused("unreadable", "a file can't be read") from exc


def _folders(base: Path) -> tuple[str, list[str]]:
    """(how the folder read, the names in it). The folder itself has to be a plain folder."""
    try:
        if not stat.S_ISDIR(os.lstat(base).st_mode):
            return "unreadable", []
        return "read", sorted(e.name for e in os.scandir(base) if not e.name.startswith("."))[:MAX_ITEMS]
    except FileNotFoundError:
        return "missing", []
    except OSError:
        return "unreadable", []


def _entry(marketplace: str, plugin: str) -> None:
    """The marketplace entry naming this plugin may only describe it. One that adds parts the cached folder doesn't
    show (hooks among them), or one that can't be read, refuses the plugin."""
    from server.services import capability_search
    listing = _claude() / "plugins" / "marketplaces" / marketplace / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(agent_skills._read_file(listing))
    except (OSError, ValueError, RecursionError) as exc:
        raise Refused("entry_unread", marketplace) from exc
    found = [e for e in (data.get("plugins") if isinstance(data, dict) else None) or []
             if isinstance(e, dict) and e.get("name") == plugin]
    if len(found) != 1:
        raise Refused("entry_unread", plugin)
    if set(found[0]) - capability_search._ENTRY_ABOUT or found[0].get("strict", True) is not True:
        raise Refused("entry_adds_parts", plugin)


def _listed() -> tuple[list[dict], list[tuple]]:
    """(each folder's state, (kind, where, name, files or the Refused)), MAX_ITEMS of them at most: none is read past
    that (#809 review). Blocking: run in a thread."""
    out: list[tuple] = []

    def read(base: Path, check=None):
        try:
            if check:
                check()
            return _read_local(base)
        except Refused as exc:
            return exc

    skills = _claude() / "skills"
    skills_state, names = _folders(skills)
    for name in names:                                  # `_folders` lists MAX_ITEMS at most
        files = read(skills / name)
        # As Claude Code's disk opens it: a manifest folder in another case makes a plugin too, refused for it.
        plugin = isinstance(files, dict) and any(plugin_package.fold(path) == plugin_package.fold(_PLUGIN_MANIFEST)
                                                 for path in files)
        out.append(("plugin" if plugin else "skill", f"skills/{name}", name, files))
    cache = _claude() / "plugins" / "cache"
    cache_state, marketplaces = _folders(cache)
    versions = ((m, p, v) for m in marketplaces for p in _folders(cache / m)[1] for v in _folders(cache / m / p)[1])
    for marketplace, plugin, version in versions:
        if len(out) >= MAX_ITEMS:
            break
        base = cache / marketplace / plugin / version
        if os.path.lexists(base / ".orphaned_at"):
            continue
        files = read(base, lambda m=marketplace, p=plugin: _entry(m, p))
        out.append(("plugin", f"plugins/{marketplace}/{plugin}/{version}", plugin, files))
    return [{"what": "skills", "state": skills_state}, {"what": "plugins", "state": cache_state}], out


# ── one skill, prepared as `skill_import.prepare_skill` prepares one ─────────────────────────────────────────────

async def _prepared_skill(snap: Snapshot, folder: str) -> dict:
    """The same parse, the same bundled scripts and references with their caps, every kept file hashed, from files
    already read. `left`: what else the folder holds, which stays behind. `hooks`: its frontmatter's, judged; they
    never go further, since the SKILL.md Arslan writes holds the name and description only. Raises ValueError, or
    Refused for a hook."""
    prefix = f"{folder}/" if folder else ""
    path = f"{prefix}SKILL.md"
    try:
        raw = snap.files[path].decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise ValueError("no SKILL.md as UTF-8 text") from exc
    info = skill_import.parse_skill_md(raw, path)
    if info is None:
        raise ValueError("not a valid SKILL.md (frontmatter name+description required)")
    try:
        # The same rule and reader as every other way a skill comes in.
        hook_rows = skill_import.frontmatter_hook_rows(raw, where=path)
    except skill_import.HookRefused as exc:
        raise Refused(exc.code, exc.part, rows=exc.rows) from None
    if len(info["body"].encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError(f"body exceeds the {MAX_SKILL_BYTES}B limit")
    files: dict[str, str] = {path: hashlib.sha256(raw.encode("utf-8")).hexdigest()}
    sizes: dict[str, int] = {path: len(raw.encode("utf-8"))}
    skipped: list[dict] = []

    def keep(file_path: str, content: str) -> str:
        files[file_path], sizes[file_path] = hashlib.sha256(content.encode("utf-8")).hexdigest(), len(content.encode())
        return content

    async def fetch(file_path: str) -> str:
        return snap.text(file_path)
    scripts, references = await skill_import._bundles("", "", snap.sha, path, list(snap.files), skipped, keep, fetch)
    named = {item["path"] for item in skipped}
    skipped += [{"path": p, "reason": "not a file the import keeps"} for p in sorted(snap.files)
                if p.startswith(prefix) and p not in files and p not in named]
    return {"key": info["key"], "info": info, "full_name": snap.repo, "commit": snap.sha, "license": None,
            "license_source": "none", "skill_md": raw, "scripts": scripts, "references": references, "files": files,
            "sizes": sizes, "skipped": skipped, "imported_from": FROM, "hooks": [row["event"] for row in hook_rows],
            "hook_rows": hook_rows}


async def _skill_here(key: str, besides: frozenset[str] = frozenset()) -> bool:
    """A skill of that key, or a folder of that key in the shared folder (another tool's, or Arslan's). `besides`:
    plugins whose skills don't count, being replaced by their card (`_marked`); such a skill's folder is its own."""
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
    if pack is not None:
        return pack.source_id not in besides
    return os.path.lexists(agent_skills.folder(key))


async def _offline_skill(ref: str, path: str, *, snapshot: Snapshot, repo_license=None) -> dict:
    """`plugin_package._skills`'s `prepare_one` for an imported plugin, from what was read, in the worker thread."""
    return await _prepared_skill(snapshot, path.rsplit("/", 1)[0] if "/" in path else "")


def _plugin_skill(besides: frozenset[str]):
    """The same, at the add, on the loop: a skill already here refuses the plugin."""
    async def prepare(ref: str, path: str, *, snapshot: Snapshot, repo_license=None) -> dict:
        skill = await _offline_skill(ref, path, snapshot=snapshot)
        if await _skill_here(skill["key"], besides):
            raise ValueError(f"skill '{skill['key']}' already exists in the library")
        return skill
    return prepare


# ── the sheet ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    """One skill or plugin as the other tool has it. Only `view` leaves this module."""
    id: str
    kind: str
    name: str
    digest: str
    snap: Snapshot | None = None
    skill: dict | None = None
    plugin: dict = field(default_factory=dict)
    identity: str = ""
    refused: str | None = None
    refused_part: str | None = None
    scan: str | None = None
    hooks: list[str] = field(default_factory=list)
    hook_rows: list[dict] | None = None     # HOOK-1: a plugin's hooks as they'd be stored, once judged
    refused_rows: list[dict] | None = None  # HOOK-1: the hooks of one a protection refused, for the sheet to show
    taken: bool = False             # refused only because a skill of its key is here (`_read`), not for its files

    @property
    def marketplace(self) -> str | None:
        """Where Claude Code installed a cached plugin from; None for one in its skills folder."""
        parts = self.id.split("/")
        return untrusted.clean_name(parts[1], 120) if parts[0] == "plugin:plugins" and len(parts) > 2 else None

    def view(self, *, here: bool, same_as: str | None) -> dict:
        # A plugin starts unticked (board 7): its card comes before it is added, so it is ticked only by hand.
        row = {"id": self.id, "tool": TOOL, "kind": self.kind, "name": self.name, "digest": self.digest, "here": here,
               "same_as": same_as, "refused": self.refused, "refused_part": self.refused_part,
               "tick": self.kind == "skill" and not (self.refused or here or same_as), "hooks": list(self.hooks)}
        if self.refused_rows is not None:
            # HOOK-1: a protection refused it; its hooks are shown, so the user sees why. Nothing of it is kept.
            row.update(refused_note=plugin_hooks.PROTECTIONS[self.kind],
                       hook_rows=plugin_hooks.card_rows(self.refused_rows))
        if self.kind == "skill":
            s = self.skill or {}
            info = s.get("info") or {}
            row.update(key=s.get("key"), description=info.get("description"), scripts=sorted(s.get("scripts") or {}),
                       references=sorted(s.get("references") or {}), left=len(s.get("skipped") or []), scan=self.scan)
        else:
            row.update(skills=sorted(self.plugin.get("skills") or []),
                       connections=sorted(self.plugin.get("connections") or []))
            row["from"] = self.marketplace
        return row


def _snapshot(name: str, files: dict[str, bytes], prefix: str = "") -> Snapshot:
    """What was read, as CAP7b reads an archive. `sha` is the content's digest, not a commit: there's none."""
    content = hashlib.sha256(json.dumps(sorted((p, hashlib.sha256(d).hexdigest()) for p, d in files.items()))
                             .encode()).hexdigest()
    return Snapshot(repo=name, sha=content[:40], files={f"{prefix}{p}": d for p, d in files.items()})


async def _item(kind: str, where: str, name: str, files) -> Item:
    """One folder judged from what was read: no database, so it runs in the worker thread (`_judged`)."""
    item = Item(id=f"{kind}:{where}", kind=kind, name=untrusted.clean_name(name, 120), digest="", identity=name)
    if isinstance(files, Refused):
        item.digest = _keyed(TOOL, where, "unread")
        item.refused, item.refused_part = files.code, untrusted.clean_name(files.part, 200)
        return item
    item.digest = _keyed(TOOL, where, sorted((p, hashlib.sha256(d).hexdigest()) for p, d in files.items()))
    try:
        if kind == "skill":
            item.snap = _snapshot(name, files, prefix=f"{name}/")
            try:
                item.skill = await _prepared_skill(item.snap, name)
            except ValueError as exc:
                raise Refused("unreadable", str(exc)[:200]) from exc
            item.identity, item.hooks = item.skill["key"], item.skill["hooks"]
            scan = skill_import.scan_prepared(item.skill)
            item.scan = scan["level"]
            if scan["level"] == "blocked":
                raise Refused("blocked", ", ".join(sorted({f["rule"] for f in scan["findings"] if f["level"] == "high"})))
        else:
            item.snap = _snapshot(name, files)
            item.hook_rows = plugin_package.judged_hooks(item.snap)     # first: no other refusal hides a blocking hook
            item.hooks = [row["event"] for row in item.hook_rows]
            manifest, paths, servers = plugin_package.parts(item.snap, hooks=True)
            item.identity = str(manifest.get("name") or name)
            item.name = untrusted.clean_name(item.identity, 120)
            # Every skill prepared and scanned now, as the add does: refusals show on the sheet, not after a tick.
            skills = await plugin_package._skills(item.snap, paths, (None, None), _offline_skill)
            item.plugin = {"skills": [s["key"] for s in skills], "connections": [untrusted.clean_name(n, 120)
                                                                                 for n in servers]}
    except Refused as exc:
        item.refused, item.refused_part = exc.code, untrusted.clean_name(exc.part, 200)
        item.refused_rows = exc.rows
    except Exception as exc:  # noqa: BLE001 — one folder no reader can read: the others stay
        logger.warning("an import candidate could not be read (%s)", type(exc).__name__)
        item.refused, item.refused_part = "unreadable", item.name
    return item


async def _plugin_rows() -> list[CapabilitySource]:
    async with db_session.AsyncSessionLocal() as db:
        return list((await db.execute(select(CapabilitySource).where(
            CapabilitySource.kind == "plugin", CapabilitySource.state.in_(("installed", "proposed"))))).scalars().all())


def _hooked(row: CapabilitySource) -> bool:
    """An imported plugin an update switched off for a blocking hook (`plugin_package.hooks_added`)."""
    return bool((row.test or {}).get("hooks_added"))


async def _marked() -> dict[str, str]:
    """{name: source id} of the imported plugins switched off for a hook: not here, so their card can bring them
    back, and their own skills don't count as already here."""
    return {row.name: row.id for row in await _plugin_rows() if _hooked(row)}


async def _plugins_here() -> set[str]:
    rows = [row for row in await _plugin_rows() if not _hooked(row)]
    return {row.name for row in rows} | {str(row.candidate_id) for row in rows}


def _judged() -> tuple[list[dict], list[Item]]:
    """The read, then the parse, the scan and the hook rule, all in the worker thread (#809 review: they held the
    event loop). `_item` touches no database and no lock of the server's loop, so it runs on a loop of its own here."""
    folders, listed = _listed()

    async def judge() -> list[Item]:
        return [await _item(*entry) for entry in listed]
    return folders, asyncio.run(judge())


async def _read() -> tuple[list[dict], list[Item]]:
    folders, items = await asyncio.to_thread(_judged)
    # Then, on the loop, the one check that needs the database: a plugin's skill already here refuses the plugin.
    besides = frozenset((await _marked()).values())
    for item in items:
        if item.kind != "plugin" or item.refused:
            continue
        for key in item.plugin.get("skills") or []:
            if await _skill_here(key, besides):
                item.refused, item.refused_part, item.taken = "skill", f"skill '{key}' already exists in the library", True
                break
    return folders, items


async def _is_here(item: Item, plugins: set[str]) -> bool:
    if item.kind == "skill":
        return bool(item.skill) and await _skill_here(item.skill["key"])
    return item.identity in plugins or f"{SOURCE}:{item.id}" in plugins


def _place(item_id: str) -> str:
    """Where Claude Code keeps a plugin, without its version: `plugin:plugins/<marketplace>/<plugin>`."""
    return item_id.rsplit("/", 1)[0] if item_id.startswith("plugin:plugins/") else item_id


async def _judged_again(items: list[Item]) -> None:
    """The hook rule after an update (the user's rule 4): an installed import whose other-tool copy now has a hook
    on a blocking or unknown event is switched off until its card. Hooks are judged first (`judged_hooks`), and a
    copy refused for anything else is switched off too, since that refusal could hide one. Matched by where Claude
    Code keeps it, which a copy too broken to name itself still has. Only at this scan: the page's load reads
    nothing.

    HOOK-1: an update that adds, removes or changes any hook (`plugin_hooks.changed`), a quiet one included, switches
    it off the same way (code `hooks_changed`), so its card is shown again. Its own skills then no longer count as
    already here, as for a plugin marked earlier (`_marked`)."""
    imported = [row for row in await _plugin_rows()
                if row.state == "installed" and str(row.candidate_id).startswith(f"{SOURCE}:")]
    marked = False
    for item in items:
        if item.kind != "plugin":
            continue
        for row in imported:
            if _place(str(row.candidate_id)[len(SOURCE) + 1:]) != _place(item.id):
                continue
            if item.refused and not item.taken:
                event = (item.refused_part or "") if item.refused == "hooks" else ""
                await plugin_package.hooks_added(row.id, event, item.refused)
            elif item.hook_rows is not None and (event := plugin_hooks.changed(row.candidate or {}, item.hook_rows)
                                                 ) is not None:
                await plugin_package.hooks_added(row.id, untrusted.clean_name(event, 80), "hooks_changed")
                marked = True
    besides = frozenset((await _marked()).values()) if marked else frozenset()
    for item in items if marked else []:
        if item.taken and not [key for key in item.plugin.get("skills") or [] if await _skill_here(key, besides)]:
            item.refused = item.refused_part = None
            item.taken = False


async def scan() -> dict:
    folders, items = await _read()
    await _judged_again(items)
    plugins = await _plugins_here()
    first: dict[tuple, str] = {}
    out: dict[str, list] = {"skills": [], "plugins": []}
    for item in items:
        same_as = first.setdefault((item.kind, item.identity), item.id)
        out[f"{item.kind}s"].append(item.view(here=await _is_here(item, plugins),
                                              same_as=None if same_as == item.id else same_as))
    return {"folders": folders, **out}


# ── the add ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def _checked(item: Item | None, tick: dict, kind: str) -> dict | None:
    """Gone, changed since the sheet, already here (a plugin in, its skills read as here too), or refused."""
    if item is None or item.kind != kind:
        return {"state": "gone"}
    if item.digest != tick["digest"]:
        return {"state": "changed"}
    if await _is_here(item, await _plugins_here()):
        return {"state": "here"}
    if item.refused:
        return {"state": "refused", "code": item.refused}
    return None


async def _add_skill(item: Item | None, tick: dict) -> dict:
    if (stop := await _checked(item, tick, "skill")) is not None:
        return stop
    try:
        done = await skill_import.install_prepared(item.skill, approved=False)
    except ValueError:              # a row or a folder of that key came meanwhile, or the folder didn't read back
        return {"state": "here"} if await _skill_here(item.skill["key"]) else {"state": "failed", "code": "write"}
    except Exception as exc:  # noqa: BLE001 — one skill's failure isn't the others'
        logger.warning("an imported skill did not install (%s)", type(exc).__name__)
        return {"state": "failed", "code": type(exc).__name__}
    return {"state": "added", "key": done["key"]}


async def _add_plugin(item: Item | None, tick: dict) -> dict:
    if (stop := await _checked(item, tick, "plugin")) is not None:
        return stop
    candidate = {"id": f"{SOURCE}:{item.id}", "kind": "plugin", "name": item.identity[:120], "source": SOURCE,
                 "source_url": None, "repo": None}
    old = (await _marked()).get(item.identity[:120])          # switched off for a hook: this card replaces it
    prepared = None
    try:
        prepared = await plugin_package.prepare_read(candidate, item.snap, "",
                                                     imported=_plugin_skill(frozenset({old} - {None})))
        about = prepared["manifest"].get("description")
        card = {**plugin_package.card_fields(prepared), "name": item.name, "from": item.marketplace,
                "summary": untrusted.clean_name(about, 300) if isinstance(about, str) else ""}
        shown = _keyed("card", card, prepared["files"])
        if tick.get("card") != shown:       # CAP7b's order: the card, then a yes to exactly it
            return {"state": "card", "card": card, "card_digest": shown}
        # Kept on its row: what the card showed, and (HOOK-1) every hook as stored, each with its switch.
        candidate.update(summary=card["summary"], hooks=card["hooks"], hook_rows=prepared["hook_rows"])
        keys = tick.get("keys") or {}
        out = await (plugin_package.replace(old, candidate, prepared, keys) if old is not None
                     else plugin_package.install(candidate, prepared, keys))
    except Refused as exc:
        return {"state": "refused", "code": exc.code}
    except Exception as exc:  # noqa: BLE001 — its text could quote a key
        logger.warning("an imported plugin did not install (%s)", type(exc).__name__)
        return {"state": "failed", "stage": "install", "code": type(exc).__name__}
    finally:
        plugin_package.discard(prepared)
    from server.services import capability_flow
    result = {key: out[key] for key in ("state", "source_id", "stage", "part", "needs_sign_in") if key in out}
    if "detail" in out:
        result["detail"] = capability_flow._plain(str(out["detail"]), keep="\n")[:400]
    return result


async def add(skills: list[dict], plugins: list[dict]) -> list[dict]:
    """Each ticked one, from the folders as they read now, with its own result: `added` (a skill, off until its card),
    `card` then `on`, `needs_sign_in`, `failed`, `blocked` or `stopped` (a plugin, as CAP7b's install), or `refused`,
    `here`, and `gone` or `changed` when the folder no longer holds what the sheet showed. A plugin switched off for a
    hook is replaced by its card's yes: install, then swap (`plugin_package.replace`); if the install fails, the old
    group stays as it was, off, with its card. The other tool's copy is never touched."""
    if not skills and not plugins:
        return []
    async with _ONE_AT_A_TIME:
        found = {item.id: item for item in (await _read())[1]}
        out = [{"id": tick["id"], **await _add_skill(found.get(tick["id"]), tick)} for tick in skills]
        for tick in plugins:
            out.append({"id": tick["id"], **await _add_plugin(found.get(tick["id"]), tick)})
        return out
