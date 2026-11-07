"""CAP7b: a plugin (Claude Code's format; Codex's manifest and `mcp.json` read the same way) as one install.

A plugin is read at one pinned commit from one archive of its own repository. Only skills and MCP servers are
accepted: hooks, commands, agent definitions or anything not recognised refuse the whole plugin. Everything is prepared
before one card (each skill as `skill_import` prepares it, each package locked by `capability_install.prepare`), so a
yes adds exactly what was shown, or nothing stays.

What's installed is ordinary: a `capability_sources` row of kind "plugin", its skills with `SkillPack.source_id` set to
that row, and each MCP server its own `kind="mcp"` row (`candidate_id` "plugin:<parent id>:<name>"), which keeps the
per-server lock, scan, test, tool pin and sign-in. No folder of the plugin's is kept: every file lands where a single
install's does, inside Arslan's data folder, so what needs `${CLAUDE_PLUGIN_ROOT}` is refused. The group switches and
goes as one, and a changed tool list on any server stops the whole plugin.

The one-click list applies to its connections, as it does to a single one (`capability_allowlist`): a package by the
plugin's own repository, a remote by its address. One off the list makes the whole plugin "add by hand". Skills aren't
held to the list, as a single skill isn't.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import tarfile
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.orchestrator import untrusted
from server.services import capability_allowlist, capability_install, capability_runtime, mcp_pin, skill_import

logger = logging.getLogger(__name__)

MANIFESTS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")
MCP_FILES = (".mcp.json", "mcp.json")
#: Manifest keys that describe a plugin and add nothing to what it does. Any key not here and not `skills` or
#: `mcpServers` refuses it: an allowlist, so a new kind of part isn't installed by not being recognised.
_ABOUT = frozenset({"$schema", "name", "displayName", "version", "description", "author", "homepage", "repository",
                    "license", "keywords", "metadata", "defaultEnabled", "icon", "documentationUrl", "supportUrl",
                    "privacyPolicyUrl", "termsOfServiceUrl"})
_KEY_CODES = {"hooks": "hooks", "commands": "commands", "agents": "agents", "lspServers": "lsp"}
#: What a plugin's folders hold when it carries a part Arslan doesn't take, as (path or folder, code).
_PARTS = (("hooks/", "hooks"), ("commands/", "commands"), ("agents/", "agents"), (".lsp.json", "lsp"),
          ("output-styles/", "other"), ("themes/", "other"), ("workflows/", "other"), ("monitors/", "other"),
          ("bin/", "other"), ("settings.json", "other"), (".app.json", "other"))
_FOLDER_VARS = re.compile(r"\$\{?(?:CLAUDE_PLUGIN_ROOT|CLAUDE_PLUGIN_DATA|CLAUDE_SKILL_DIR|PLUGIN_ROOT|PLUGIN_DATA)\b")
_ANY_VAR = re.compile(r"\$\{")
_WHOLE_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEADER_NAME = re.compile(r"[A-Za-z0-9_-]+")
#: Env a plugin's connection can't set, fixed or asked for: it would load other code into the program the card shows,
#: send the program's traffic somewhere else, or stop checking who answers. Any case. The card's fixed values show the
#: rest, and the lock only holds what the runtime is told to load.
_UNSAFE_ENV = re.compile(
    r"(DYLD_|LD_|GIT_|NPM_CONFIG_).*|.*_PROXY"
    r"|NODE_(OPTIONS|PATH|COMPILE_CACHE|TLS_REJECT_UNAUTHORIZED|EXTRA_CA_CERTS|USE_ENV_PROXY)"
    r"|PYTHON(PATH|HOME|STARTUP|USERBASE|WARNINGS|BREAKPOINT|INSPECT|PYCACHEPREFIX|EXECUTABLE|HTTPSVERIFY)"
    r"|PATH|BASH_ENV|ENV|ZDOTDIR|PERL5(OPT|LIB)|RUBY(OPT|LIB)|_?JAVA_(TOOL_)?OPTIONS|JDK_JAVA_OPTIONS|CLASSPATH"
    r"|SSL_CERT_(FILE|DIR)|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE"
    r"|(UV|PIP)_(INDEX|INDEX_URL|DEFAULT_INDEX|EXTRA_INDEX_URL|FIND_LINKS|CONFIG_FILE)", re.I)
#: Headers that ask the remote's front end to route the call somewhere other than the address on the card.
_UNSAFE_HEADER = re.compile(r"host|forwarded|x-forwarded-host|x-original-url|x-rewrite-url", re.I)
_PINNED = re.compile(r"(@?[^@=\s]+)(?:@|==)([^@=\s]+)")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_REMOTE_TYPES = (None, "http", "streamable-http")
_RUNTIMES = {"npx": ("node", "npm"), "uvx": ("uv", "pypi")}

CODELOAD = "https://codeload.github.com"
ARCHIVE_TIMEOUT_S = 30.0
MAX_ARCHIVE_BYTES = 30 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
MAX_FILE_BYTES = 1_000_000
MAX_CONNECTIONS = 10
MAX_VALUE_CHARS = 500         # an argument's limit too (`capability_install.start_arguments`)


class Refused(Exception):
    """This plugin can't be added: `code` says why, `part` names which part. `by_hand`: why the one-click list doesn't
    cover that part, when the code is "add_by_hand"."""

    def __init__(self, code: str, part: str = "", by_hand: str | None = None):
        super().__init__(f"{code}: {part}" if part else code)
        self.code, self.part, self.by_hand = code, part, by_hand


@dataclass
class Snapshot:
    """One commit of a repository, read whole: every file is what the card shows and the install writes, so nothing
    is fetched a second time and GitHub's API (60 calls an hour without a token) isn't touched."""
    repo: str
    sha: str
    files: dict[str, bytes]

    def text(self, path: str) -> str:
        return self.files[path].decode("utf-8", "replace")


def read_archive(repo: str, data: bytes) -> Snapshot:
    """Plain files only, by plain paths: a link or an odd name isn't a file of this plugin. The archive's pax header
    names the commit it was made from (GitHub writes it there), as `capability_search.index_archive` reads it."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                total += member.size
                if total > MAX_UNPACKED_BYTES:
                    raise Refused("too_large", repo)
                rel = member.name.split("/", 1)[1] if "/" in member.name else ""
                if member.isfile() and member.size <= MAX_FILE_BYTES and skill_import._plain_path(rel):
                    content = archive.extractfile(member)
                    if content is not None:
                        files[rel] = content.read()
            sha = (archive.pax_headers or {}).get("comment") or ""
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:       # a download cut short, or not an archive
        raise Refused("unreadable", repo) from exc
    if not _SHA.fullmatch(sha):
        raise Refused("not_pinned", repo)
    return Snapshot(repo=repo, sha=sha, files=files)


async def snapshot(repo: str, ref: str | None = None) -> Snapshot:
    """The repository at `ref` (a marketplace's pinned commit), else at the commit its default branch points at now."""
    if not _REPO.fullmatch(repo or "") or not skill_import._plain_path(repo):      # `..` fits the pattern's characters
        raise Refused("not_github", str(repo))
    if ref and not _SHA.fullmatch(ref):
        raise Refused("not_pinned", ref)
    body = bytearray()
    try:
        async with httpx.AsyncClient(timeout=ARCHIVE_TIMEOUT_S, follow_redirects=True) as client:
            async with client.stream("GET", f"{CODELOAD}/{repo}/tar.gz/{ref or 'HEAD'}") as r:
                if r.status_code != 200:
                    raise Refused("unreachable", repo)
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_ARCHIVE_BYTES:
                        raise Refused("too_large", repo)
    except httpx.HTTPError as exc:
        raise Refused("unreachable", repo) from exc
    return await asyncio.to_thread(read_archive, repo, bytes(body))


def _join(root: str, rel: str) -> str:
    return f"{root}/{rel}" if root and rel else root or rel


def _inside(value) -> str:
    """A manifest's path as a path inside the plugin, without the `./`. `.` is the plugin's own folder."""
    text = str(value)
    plain = text[2:] if text.startswith("./") else text
    if plain in ("", "."):
        return ""
    if not skill_import._plain_path(plain):
        raise Refused("path_outside", text)
    return plain


def _manifest(snap: Snapshot, root: str) -> dict:
    for name in MANIFESTS:
        path = _join(root, name)
        if path in snap.files:
            try:
                manifest = json.loads(snap.text(path))
            except ValueError as exc:
                raise Refused("unreadable", name) from exc
            if not isinstance(manifest, dict):
                raise Refused("unreadable", name)
            return manifest
    raise Refused("not_a_plugin", snap.repo)


def _only_skills_and_connections(manifest: dict, snap: Snapshot, root: str) -> None:
    for key in manifest:
        if key in _KEY_CODES:
            raise Refused(_KEY_CODES[key], key)
        if key not in _ABOUT and key not in ("skills", "mcpServers"):
            raise Refused("other", key)
    prefix = _join(root, "")
    prefix = f"{prefix}/" if prefix else ""
    for path in sorted(snap.files):
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        for part, code in _PARTS:
            if rel == part or (part.endswith("/") and rel.startswith(part)):
                raise Refused(code, rel)


def _skill_files(manifest: dict, snap: Snapshot, root: str) -> list[str]:
    extra = manifest.get("skills")
    folders = ["skills", *(_inside(v) for v in (extra if isinstance(extra, list) else [extra] if extra else []))]
    found: list[str] = []
    for folder in folders:
        base = _join(root, folder)
        prefix = f"{base}/" if base else ""
        for path in sorted(snap.files):
            rel = path[len(prefix):] if path.startswith(prefix) else None
            if rel is not None and (rel == "SKILL.md" or (rel.endswith("/SKILL.md") and rel.count("/") == 1)):
                if path not in found:
                    found.append(path)
    if len(found) > skill_import._MAX_SKILLS_PER_SCAN:
        raise Refused("too_many", "skills")
    return found


def _servers(manifest: dict, snap: Snapshot, root: str) -> dict[str, dict]:
    """The plugin's MCP servers: its config file, then the manifest's, a later one of a name replacing an earlier one
    (as Claude Code reads them)."""
    def of(data) -> dict:
        data = data.get("mcpServers", data) if isinstance(data, dict) else None
        if not isinstance(data, dict):
            raise Refused("unreadable", "mcpServers")
        return data

    def from_file(rel: str) -> dict:
        path = _join(root, rel)
        if not rel.endswith(".json") or path not in snap.files:      # a .mcpb bundle or an address: nothing to read here
            raise Refused("cannot_pin", rel)
        try:
            return of(json.loads(snap.text(path)))
        except ValueError as exc:
            raise Refused("unreadable", rel) from exc

    servers: dict[str, dict] = {}
    for name in MCP_FILES:
        if _join(root, name) in snap.files:
            servers.update(from_file(name))
    declared = manifest.get("mcpServers")
    for value in declared if isinstance(declared, list) else [declared] if declared else []:
        servers.update(of(value) if isinstance(value, dict) else from_file(_inside(value)))
    if len(servers) > MAX_CONNECTIONS:
        raise Refused("too_many", "mcpServers")
    return servers


def _license(snap: Snapshot, root: str) -> tuple[str | None, str | None]:
    """The plugin's own license file, else its repository's: read at the pinned commit, by its wording."""
    for folder in ([root, ""] if root else [""]):
        for name in skill_import._LICENSE_NAMES:
            path = _join(folder, name)
            if path in snap.files:
                return skill_import.detect_license(snap.text(path)), path
    return None, None


def _part_candidate(plugin: dict, name: str, **fields) -> dict:
    """An MCP server of a plugin, shaped as the search shapes a candidate: `capability_install` takes it as it is."""
    return {"id": f"plugin-part:{name}", "kind": "mcp", "name": name, "summary": plugin.get("summary") or "",
            "source": "plugin", "source_url": plugin.get("source_url"), "repo": plugin.get("repo"), "not_here": None,
            "path": None, "stars": None, "pushed_days": None,
            "license": {"spdx": None, "read_from": None, "verdict": "unknown"}, **fields}


def _whole(name: str, value) -> str:
    """A value a connection starts with, which the card shows as it runs: one the card couldn't show whole (hidden
    characters, or too long to show) refuses the plugin, since nothing is cut or cleaned between the two."""
    if not isinstance(value, str) or untrusted.clean_name(value, MAX_VALUE_CHARS) != value:
        raise Refused("unreadable", name)
    return value


def setting_names(name: str, settings, valid: re.Pattern, unsafe: re.Pattern | None) -> dict:
    """A connection's `env` or `headers`: its shape, and no name `unsafe` holds. Absent is none. CAP8-1 shares this: it
    never shows a value, so the values aren't read here."""
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise Refused("unreadable", name)
    for key in settings:
        if not valid.fullmatch(key):
            raise Refused("unreadable", name)
        if unsafe is not None and unsafe.fullmatch(key):
            raise Refused("unsafe_setting", f"{name}: {key}")
    return settings


def _settings(name: str, settings, valid: re.Pattern, unsafe: re.Pattern) -> dict[str, str]:
    """A plugin's `env` or `headers`, which its card shows, so each value has to show whole."""
    for value in setting_names(name, settings, valid, unsafe).values():
        _whole(name, value)
    return settings or {}


def _env_keys(name: str, env) -> tuple[list[dict], dict]:
    """What the config asks the user for, and what it says itself. Only a value that is wholly one variable can be
    asked for: anything else with a variable in it can't be read."""
    keys, fixed = [], {}
    for key, value in _settings(name, env, _ENV_NAME, _UNSAFE_ENV).items():
        if _WHOLE_VAR.fullmatch(value):
            keys.append({"name": key, "required": True, "secret": True, "description": ""})
        elif _ANY_VAR.search(value):
            raise Refused("cannot_pin", name)
        else:
            fixed[key] = value
    return keys, fixed


def remote_url(name: str, spec: dict) -> str:
    """A remote's address, as written: one that names a variable can't be pinned to the card or the sheet."""
    url = spec.get("url")
    if spec.get("type") not in _REMOTE_TYPES or not isinstance(url, str) or _ANY_VAR.search(url):
        raise Refused("cannot_pin", name)
    return _whole(name, url)


def _remote(plugin: dict, name: str, spec: dict, allow: dict) -> dict:
    url = remote_url(name, spec)
    why = capability_allowlist.listed_remote(url, allow)
    if why:
        raise Refused("add_by_hand", name, by_hand=why)
    keys, fixed = [], {}
    for header, value in _settings(name, spec.get("headers"), _HEADER_NAME, _UNSAFE_HEADER).items():
        if _ANY_VAR.search(value):
            keys.append({"name": header, "required": True, "secret": True, "description": value})
        else:
            fixed[header] = value
    return {"candidate": _part_candidate(plugin, name, runtime="remote", version=None, package=None,
                                         remote={"url": url}, needs={"keys": keys, "network": True}), "env": fixed}


def package_line(name: str, spec: dict) -> tuple[str, list[str]]:
    """`npx` or `uvx`, by those bare names, and one package: the command, and its package then the package's arguments.
    Only the plain form is read: its options decide which argument is the package, and a variable in an argument can't
    be locked or asked for."""
    command = spec.get("command")
    if not isinstance(command, str) and command is not None:
        raise Refused("unreadable", name)
    if command not in _RUNTIMES:
        raise Refused("runs_from_source", name)
    args = spec.get("args", [])
    if not isinstance(args, list):
        raise Refused("unreadable", name)
    args = [_whole(name, a) for a in args]
    if any(_ANY_VAR.search(a) for a in args):
        raise Refused("cannot_pin", name)
    while args and args[0] in ("-y", "--yes"):
        args.pop(0)
    if not args or args[0].startswith("-"):
        raise Refused("cannot_pin", name)
    return command, args


async def pinned_package(parent: dict, name: str, command: str, args: list[str], keys: list[dict], fixed: dict) -> dict:
    """That line, locked as a Registry package is: its candidate, and the `env` it starts with."""
    try:
        pinned = (await mcp_pin.pin(command, [args[0]], fixed))[0]
    except mcp_pin.PinRefused as exc:
        raise Refused("cannot_pin", name) from exc
    match = _PINNED.fullmatch(pinned)
    if match is None:
        raise Refused("cannot_pin", name)
    runtime, registry = _RUNTIMES[command]
    package = {"registry_type": registry, "identifier": match.group(1), "version": match.group(2),
               "arguments": [{"type": "positional", "value": a} for a in args[1:]]}
    return {"candidate": _part_candidate(parent, name, runtime=runtime, version=match.group(2), package=package,
                                         remote=None, needs={"keys": keys, "network": None}), "env": fixed}


async def _package(plugin: dict, name: str, spec: dict, allow: dict) -> dict:
    """A package has no Registry publisher here, so the plugin's own repository answers to the list."""
    command, args = package_line(name, spec)
    keys, fixed = _env_keys(name, spec.get("env"))
    why = await capability_allowlist.confirm_repository(plugin, allow)
    if why:
        raise Refused("add_by_hand", name, by_hand=why)
    return await pinned_package(plugin, name, command, args, keys, fixed)


async def _skills(snap: Snapshot, paths: list[str], spdx_and_path: tuple) -> list[dict]:
    prepared: list[dict] = []
    keys: set[str] = set()
    for path in paths:
        try:
            skill = await skill_import.prepare_skill(f"{snap.repo}@{snap.sha}", path, snapshot=snap,
                                                     repo_license=spdx_and_path[0])
        except ValueError as exc:
            raise Refused("skill", str(exc)[:200]) from exc
        key = skill["key"]
        if key in keys:
            raise Refused("name_clash", key)
        keys.add(key)
        if _FOLDER_VARS.search("\n".join((skill["skill_md"], *skill["scripts"].values(),
                                          *skill["references"].values()))):
            raise Refused("needs_plugin_folder", key)
        skill["scan"] = skill_import.scan_prepared(skill)
        if skill["scan"]["level"] == "blocked":
            raise Refused("scan", key)
        prepared.append(skill)
    return prepared


def discard(prepared: dict | None) -> None:
    """A card that was not a yes: the locks' staging folders go; nothing was installed."""
    for connection in (prepared or {}).get("connections") or []:
        capability_install.discard(connection.get("locked"))


def _file_hashes(snap: Snapshot, prefix: str) -> dict[str, str]:
    return {path[len(prefix):]: hashlib.sha256(data).hexdigest() for path, data in snap.files.items()
            if path.startswith(prefix)}


async def prepare(candidate: dict) -> dict:
    """Everything before the card. Raises Refused, naming the part, with nothing kept."""
    snap = await snapshot(candidate.get("repo") or "", candidate.get("ref"))
    root = candidate.get("path") or ""
    manifest = _manifest(snap, root)
    _only_skills_and_connections(manifest, snap, root)
    paths = _skill_files(manifest, snap, root)
    servers = _servers(manifest, snap, root)
    license_ = _license(snap, root)
    skills = await _skills(snap, paths, license_)
    allow = await capability_allowlist.current()
    prefix = f"{root}/" if root else ""
    prepared = {"commit": snap.sha, "license": license_, "skills": skills, "connections": [], "manifest": manifest,
                "files": await asyncio.to_thread(_file_hashes, snap, prefix)}
    try:
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                raise Refused("unreadable", name)
            if _FOLDER_VARS.search(json.dumps(spec)):
                raise Refused("needs_plugin_folder", name)
            connection = (_remote(candidate, name, spec, allow) if spec.get("url") or spec.get("type")
                          else await _package(candidate, name, spec, allow))
            try:
                connection["locked"] = await capability_install.prepare(connection["candidate"])
            except (capability_install.InstallFailure, capability_runtime.RuntimeFailure) as exc:
                raise Refused(exc.code, name) from exc
            prepared["connections"].append(connection)
    except BaseException:
        discard(prepared)
        raise
    return prepared


def card_fields(prepared: dict) -> dict:
    """What the card adds to `capability_flow.card_for`: every part, by its own name, and each connection with what it
    is started with: its fixed `env` or `headers` and the `keys` it gets (a key two of them name is asked for once)."""
    spdx, read_from = prepared["license"]
    keys: dict[str, dict] = {}
    connections = []
    for connection in prepared["connections"]:
        c, locked = connection["candidate"], connection["locked"]
        for key in c["needs"]["keys"]:
            keys.setdefault(key["name"], key)
        remote = c["runtime"] == "remote"
        connections.append({"name": untrusted.clean_name(c["name"], 120), "runtime": c["runtime"],
                            "version": c.get("version"), "remote_host": (c.get("remote") or {}).get("url"),
                            "network": capability_install.grants_for([], c["needs"])["network"],
                            "arguments": [a["value"] for a in (c.get("package") or {}).get("arguments") or []],
                            "env": {} if remote else connection["env"], "headers": connection["env"] if remote else {},
                            "keys": [key["name"] for key in c["needs"]["keys"]],
                            "lock": capability_install.lock_summary(locked)})
    skills = [{"key": s["key"], "name": s["info"]["name"], "summary": s["info"]["description"],
               "scripts": sorted(s["scripts"]), "references": sorted(s["references"]), "skipped": s["skipped"],
               "scan": s["scan"],
               "hidden": untrusted.hidden_summary("\n".join([s["info"]["body"], *s["references"].values()]))}
              for s in prepared["skills"]]
    return {"commit": prepared["commit"], "license": {"spdx": spdx, "read_from": read_from}, "skills": skills,
            "connections": connections, "keys": list(keys.values())[:12], "folders": []}


def parent_of(candidate_id: str | None) -> str | None:
    """The plugin an MCP server's capability source belongs to, or None for one installed by itself."""
    parts = (candidate_id or "").split(":", 2)
    return parts[1] if len(parts) == 3 and parts[0] == "plugin" else None


async def _children(source_id: str) -> list[CapabilitySource]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CapabilitySource).where(
            CapabilitySource.kind == "mcp", CapabilitySource.state != "removed",
            CapabilitySource.candidate_id.like(f"plugin:{source_id}:%")))).scalars().all()
    return list(rows)


async def _skill_keys(source_id: str) -> list[str]:
    async with db_session.AsyncSessionLocal() as db:
        return list((await db.execute(select(SkillPack.key).where(SkillPack.source_id == source_id))).scalars().all())


async def _plugin(source_id: str) -> CapabilitySource | None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, source_id)
    return row if row is not None and row.kind == "plugin" else None


async def _undo(source_ids: list[str], skill_keys: list[str]) -> None:
    """An install that didn't finish: as much of it goes as can, one failure not keeping the others."""
    from server.services import capability_list
    steps = [*(capability_install.remove(source_id) for source_id in source_ids),
             *(capability_list._remove_skill(key) for key in skill_keys)]
    for step in steps:
        try:
            await step
        except Exception:  # noqa: BLE001 — the rest still goes
            logger.warning("a plugin's part could not be removed after a failed install", exc_info=True)


async def install(candidate: dict, prepared: dict, keys: dict, owner_id: str = "local") -> dict:
    """Every part, connections first (the test is what most often fails). One that doesn't pass takes the others with
    it: "on" here means the whole plugin, or `failed` / `blocked` with nothing kept. A connection's tool list changing
    while the rest go in stops the plugin as it would later (`stop_for`): `stopped`, installed with every part off."""
    from server.services import capability_flow
    source_id = uuid.uuid4().hex
    spdx, read_from = prepared["license"]
    manifest = prepared["manifest"]
    now = datetime.utcnow()
    worst = "blocked" if any(s["scan"]["level"] == "blocked" for s in prepared["skills"]) else (
        "warn" if any(s["scan"]["level"] != "clean" for s in prepared["skills"]) else "clean")
    async with db_session.AsyncSessionLocal() as db:
        db.add(CapabilitySource(
            id=source_id, owner_id=owner_id, kind="plugin", name=str(candidate.get("name"))[:120],
            candidate_id=str(candidate.get("id"))[:300], source_url=candidate.get("source_url"),
            repo=candidate.get("repo"), version=untrusted.clean_name(manifest.get("version") or prepared["commit"][:12], 80),
            commit_sha=prepared["commit"], license_spdx=spdx, license_path=read_from, stars=candidate.get("stars"),
            pushed_days=candidate.get("pushed_days"), checked_at=now, runtime="plugin",
            needs={"keys": card_fields(prepared)["keys"], "network": None}, grants={}, candidate=candidate,
            scan={"level": worst, "findings": [f for s in prepared["skills"] for f in s["scan"]["findings"]]},
            files=prepared["files"], state="proposed", created_at=now))
        await db.commit()
    done: list[str] = []
    written: list[str] = []
    tools: list[str] = []
    waiting: list[str] = []

    async def failed(result: dict) -> dict:
        await _undo([*done, *[child.id for child in await _children(source_id) if child.id not in done]], written)
        discard(prepared)
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(CapabilitySource, source_id)
            row.state, row.error = "failed", f"{result.get('part')}: {result.get('stage') or result['state']}"[:1000]
            await db.commit()
        return {**result, "source_id": source_id}

    part_name = str(candidate.get("name"))
    try:
        for connection in prepared["connections"]:
            part_name = connection["candidate"]["name"]
            part = {**connection["candidate"], "id": f"plugin:{source_id}:{part_name}"}
            wanted = {k["name"] for k in part["needs"]["keys"]}
            out = await capability_flow.install_mcp(part, folders=[], prepared=connection["locked"],
                                                    keys={**connection["env"],
                                                          **{k: v for k, v in (keys or {}).items() if k in wanted}})
            if out.get("source_id"):
                done.append(out["source_id"])
            if out["state"] not in ("on", "needs_sign_in"):
                return await failed({**out, "part": part_name})
            tools += out.get("tools") or []
            if out["state"] == "needs_sign_in":
                waiting.append(part_name)
        for skill in prepared["skills"]:
            part_name = skill["key"]
            written.append((await skill_import.install_prepared(skill, source_id=source_id))["key"])
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(CapabilitySource, source_id)
            row.state, row.installed_at = "installed", datetime.utcnow()
            row.test = {**(row.test or {}), "ok": True, "stage": "parts", "at": datetime.utcnow().isoformat() + "Z"}
            stopped = row.test.get("stopped")
            await db.commit()
        if stopped:                             # the parts that went in after the stop stop with the rest
            await _switch_parts(source_id, False)
            return {"state": "stopped", "stage": "tools_changed", "source_id": source_id}
    except asyncio.CancelledError:              # half a plugin would be parts nothing can reach: no row holds them
        await asyncio.shield(failed({"state": "failed", "stage": "install", "part": part_name}))
        raise
    except Exception as exc:  # noqa: BLE001 — whatever stopped it, nothing stays
        return await failed({"state": "failed", "stage": "install", "detail": str(exc)[:400] or type(exc).__name__,
                             "part": part_name})
    return {"state": "on", "source_id": source_id, "tools": tools, "skills": written, "needs_sign_in": waiting}


async def _switch_parts(source_id: str, on: bool, *, except_server: int | None = None) -> None:
    from server.services import mcp_service
    for child in await _children(source_id):
        if child.mcp_server_id == except_server or not child.mcp_server_id:
            continue
        # A connection still waiting for its sign-in stays off until the first listing after it (#724).
        if on and (child.test or {}).get("needs_sign_in"):
            continue
        await mcp_service.set_host_allowed(child.mcp_server_id, on)
    async with db_session.AsyncSessionLocal() as db:
        for pack in (await db.execute(select(SkillPack).where(SkillPack.source_id == source_id))).scalars():
            pack.enabled = on
        await db.commit()


async def switch(source_id: str, on: bool) -> bool:
    """The group's one switch. False when there is no such plugin. Switching on ends a stop: the rest come back, and
    the part whose tool list changed stays parked by its own pin (`discovery.held`) until the user reviews it."""
    row = await _plugin(source_id)
    if row is None or row.state != "installed":
        return False
    await _switch_parts(source_id, on)
    if on:
        async with db_session.AsyncSessionLocal() as db:
            stored = await db.get(CapabilitySource, source_id)
            stored.test = {k: v for k, v in (stored.test or {}).items() if k != "stopped"}
            await db.commit()
    return True


async def remove(source_id: str) -> bool:
    """The whole group, and only what this plugin installed. False when there is no such plugin."""
    row = await _plugin(source_id)
    if row is None:
        return False
    # Not `_undo`: a failure here leaves what's left in the group, and a retry completes it.
    from server.services import capability_list
    for child in await _children(source_id):
        await capability_install.remove(child.id)
    for key in await _skill_keys(source_id):
        await capability_list._remove_skill(key)
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(CapabilitySource, source_id)
        stored.state = "removed"
        await db.commit()
    return True


async def finish_interrupted() -> None:
    """At boot, before any server starts. A plain Quit kills the server, so an install it cut short ran no undo: its
    row is still `proposed`, its finished parts are on, and only a group's switch and delete reach them, which a row
    that never finished doesn't have. They go now. One that can't is tried again at the next boot."""
    async with db_session.AsyncSessionLocal() as db:
        ids = (await db.execute(select(CapabilitySource.id).where(CapabilitySource.kind == "plugin",
                                                                  CapabilitySource.state == "proposed"))).scalars().all()
    for source_id in ids:
        try:
            await remove(source_id)
            async with db_session.AsyncSessionLocal() as db:
                row = await db.get(CapabilitySource, source_id)
                row.state, row.error = "failed", "interrupted"
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — never a reason to stop the boot, or the next one
            logger.warning("a plugin install cut short was not undone at boot (%s): %s", source_id, exc)


async def stop_for(child: CapabilitySource, server_id: int) -> None:
    """CAP5a's pin found a changed tool list on this connection: if it belongs to a plugin, the whole plugin stops. The
    connection itself is parked by the pin raising; the rest are switched off, here."""
    source_id = parent_of(child.candidate_id)
    if source_id is None or await _plugin(source_id) is None:
        return
    await _switch_parts(source_id, False, except_server=server_id)
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(CapabilitySource, source_id)
        stored.test = {**(stored.test or {}), "stopped": {"connection": child.name,
                                                          "at": datetime.utcnow().isoformat() + "Z"}}
        await db.commit()
