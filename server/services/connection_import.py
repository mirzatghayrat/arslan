"""CAP8-1: the MCP servers the user already configured in Claude Code and Codex, brought in by the user's click.

Only the two routes in `api/capabilities` reach this: no model tool, job or prompt does, and nothing here goes in the
model's context. It reads only the top-level `mcpServers` of `~/.claude.json` (user scope) and `[mcp_servers.*]` of
`~/.codex/config.toml`, and writes to neither. A project's `.mcp.json` and Claude Code's local scope are on the card's
list. Formats: https://code.claude.com/docs/en/mcp and https://learn.chatgpt.com/docs/extend/mcp?surface=cli

`scan` is one sheet with ticks: each server's kind, what it runs or which host it opens, the names of its `env` or
headers, and how many keys it has, never a key. `add` takes the ticked ones, reads the file again, and adds what the
sheet showed (`digest`), or nothing.

- **`npx` and `uvx`** go the CAP4 way, through `plugin_package`'s reading of that line: pinned, locked, scanned, tested,
  tool-pinned and sandboxed. **A remote** is added as written, since this click is the deliberate one: neither is held to
  the one-click list, and the sheet shows each host, as `httpx` will read it.
- **Keys** are read here and stored encrypted, as `capability_install` stores a typed one. Every `env` or header value
  counts as one, since Arslan can't tell a key from a setting. One in an address or an argument moves into the server's
  encrypted `secrets`, leaving a `${NAME}` that `discovery.runtime_dict` fills at each start (SEC1). A name with no value
  (`${VAR}`, `Bearer ${VAR}`, `env_vars`, `bearer_token_env_var`, `env_http_headers`) is a key `add` must be given.
- **A custom program** (anything but bare `npx` or `uvx`) is the user's decision of 2026-11-07, which loosens the card's
  rule: offered and unticked, with its command, arguments and `env` names shown, and added as the hand-add form adds one,
  so it runs as the other tool runs it, with no sandbox. Its `env` can load other code, so no name is refused and each is
  named. The sheet says so in words.
- **A server `enabled = false` in Codex,** or one with `enabled_tools` or `disabled_tools` (which don't come along), is
  listed and starts unticked, and a tick still takes it. So does the second tool's copy of a server (`same_as`).

**Stated limits:** a key that doesn't look like one to SEC1 (short, after an option with an ordinary name) shows as an
argument and stays as written. A package with no key gets no network (CAP4's rule), and a folder in its arguments isn't
granted (the dossier grants one). `cwd`, timeouts, approval modes and pre-registered OAuth clients don't come along.
`PATH` in a package's `env` is dropped: programs there start by absolute path, and hand-written configs often set it.
A program's relative path that reads like a key (24 or more characters with a digit) shows masked and is one server with
another such: the file it comes from already runs it in the other tool.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, MCPServer
from server.orchestrator import untrusted
from server.services import capability_flow, capability_install, capability_runtime
from server.services import connection_secrets as cs
from server.services import mcp_pin, mcp_service, plugin_package
from server.services.plugin_package import Refused

logger = logging.getLogger(__name__)

SOURCE = "import"                     # `capability_install.prepare` reads it: there's no repository for its license gate
#: A variable the user's other tool would fill: wholly the value, or after a scheme word (`Bearer ${API_KEY}`).
_ASKED = re.compile(r"((?:bearer|basic|token) )?\$\{([A-Za-z_][A-Za-z0-9_]*)\}", re.I)
_COMMAND_OF = {runtime: command for command, (runtime, _) in plugin_package._RUNTIMES.items()}
#: Keyed: a plain hash of what holds a key could be tried against guesses. A restart only means scanning again.
_DIGEST_KEY = secrets.token_bytes(32)
_ONE_AT_A_TIME = asyncio.Lock()       # two clicks at once would each find the server not here yet


def _digest(tool: str, name: str, raw) -> str:
    return hmac.new(_DIGEST_KEY, json.dumps([tool, name, raw], sort_keys=True, default=str).encode(), "sha256").hexdigest()


def _blind(text: str) -> str:
    """A secret's mask and its placeholder read the same, so a key that moved doesn't make it another server."""
    return cs.PLACEHOLDER.sub(cs._MASK, text)


def _url_identity(url: str) -> str:
    return _blind(cs.shown(url, [])[0] or "").rstrip("/")


def _line_identity(command: str, args: list[str]) -> str:
    """What a stdio server runs. For a package, by name and without a version, so a pinned copy of it is the same.
    The name is never masked: SEC1 reads a long one as a key, and every masked name would be the same server."""
    line = list(args)
    package = []
    if command in plugin_package._RUNTIMES:
        while line and line[0] in ("-y", "--yes"):
            line.pop(0)
        if line:
            pinned = plugin_package._PINNED.fullmatch(line[0])
            package = [pinned.group(1) if pinned else line.pop(0)]
            if pinned:
                line.pop(0)
    return json.dumps([command, *package, *[_blind(arg) for arg in cs.shown(None, line)[1]]])


def _package_shown(package: str) -> str:
    """The package as written, even one SEC1 reads as a key by its look alone (a long name with a digit): it's what this
    click installs. A part of it that holds a key by where it sits (an address's password) stays masked."""
    return package if all(set(part) == {"where", "index"} for part in cs.find(None, [package])) else cs.shown(None, [package])[1][0]


@dataclass
class Found:
    """One server as its file has it. Only `view` leaves this module: the rest holds keys, as written."""
    id: str
    tool: str
    name: str
    digest: str
    on_there: bool = True
    tool_limits: bool = False
    kind: str = "unreadable"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    line: list[str] = field(default_factory=list)      # a package's, as `package_line` reads it: the package comes first
    url: str | None = None
    address: str | None = None
    fixed: dict[str, str] = field(default_factory=dict)
    asked: dict[str, tuple[str, str]] = field(default_factory=dict)     # setting -> (scheme word, variable)
    refused: str | None = None
    refused_part: str | None = None

    def identity(self) -> str:
        if self.url:
            return _url_identity(self.url)
        return _line_identity(self.command, self.line or self.args) if self.command else self.id

    def asks(self) -> list[str]:
        return sorted({variable for _, variable in self.asked.values()})

    def keys(self) -> int:
        return len(self.fixed) + len(cs.find(self.url, self.line[1:] if self.line else self.args))

    def _shown(self) -> list[str]:
        """The command and its arguments, every key masked. A package's own name isn't one, and what comes before it is `-y`."""
        if not self.line:
            return [self.command or "", *cs.shown(None, self.args)[1]]
        before = self.args[:len(self.args) - len(self.line)]
        return [self.command or "", *before, _package_shown(self.line[0]), *cs.shown(None, self.line[1:])[1]]

    def view(self, *, here: bool, same_as: str | None) -> dict:
        shown = [untrusted.clean_name(part, 500) for part in self._shown()]
        return {"id": self.id, "tool": self.tool, "name": self.name, "digest": self.digest, "kind": self.kind,
                "command": shown[0] or None, "arguments": shown[1:], "address": self.address,
                # What the sandbox will give it (`capability_install.grants_for`). A program runs outside it.
                "network": self.kind in ("remote", "program") or (self.kind == "package" and bool(self.keys() or self.asked)),
                # Names only, for all three kinds: `_add_one` starts each with these. In a program one can change what runs.
                "env": sorted({*self.fixed, *self.asked}),
                "keys": self.keys(), "asks": self.asks(), "on_there": self.on_there, "tool_limits": self.tool_limits,
                "here": here, "same_as": same_as, "refused": self.refused, "refused_part": self.refused_part,
                "tick": not (self.refused or here or same_as or self.tool_limits or not self.on_there or self.kind == "program")}


def _settings(name: str, settings, valid: re.Pattern, unsafe: re.Pattern | None) -> tuple[dict, dict]:
    """(the values as written, the ones to ask for). Anything else with a variable in it can't be read."""
    fixed, asked = {}, {}
    for key, value in plugin_package.setting_names(name, settings, valid, unsafe).items():
        if not isinstance(value, str):
            raise Refused("unreadable", name)
        match = _ASKED.fullmatch(value)
        if match:
            asked[key] = (match.group(1) or "", match.group(2))
        elif plugin_package._ANY_VAR.search(value):
            raise Refused("cannot_pin", name)
        else:
            fixed[key] = value
    return fixed, asked


def _address(url: str) -> str | None:
    """The scheme and host the connection will open, by the parser that opens it: `httpx` reads the host past a
    backslash, and writes a non-ASCII one as `xn--`, so one can't read as another. No user, path or query: a key rides there."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return None
    return f"{parsed.scheme}://{parsed.netloc.decode('ascii')}" if parsed.scheme in ("http", "https") and parsed.host else None


def _table(raw: dict, key: str) -> dict:
    value = raw.get(key)
    if value is not None and not isinstance(value, dict):
        raise Refused("unreadable", key)
    return value or {}


def _codex_shape(raw: dict) -> dict:
    """A Codex entry in Claude Code's shape, so one reader reads both."""
    if "url" in raw:
        headers = {**_table(raw, "http_headers"), **{header: f"${{{variable}}}" for header, variable
                                                     in _table(raw, "env_http_headers").items()}}
        if raw.get("bearer_token_env_var"):
            headers["Authorization"] = f"Bearer ${{{raw['bearer_token_env_var']}}}"
        return {"type": "http", "url": raw["url"], "headers": headers, "headersHelper": raw.get("http_headers_helper")}
    names = raw.get("env_vars") or []
    if not isinstance(names, list):
        raise Refused("unreadable", "env_vars")
    env = dict(_table(raw, "env"))
    for item in names:                  # a name, or `{ name, source }`
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str):
            raise Refused("unreadable", "env_vars")
        env[name] = f"${{{name}}}"
    return {"command": raw.get("command"), "args": raw.get("args", []), "env": env}


def _read_line(found: Found, name: str, spec: dict) -> None:
    transport = spec.get("type")
    if transport in (None, "stdio"):    # Claude Code reads an entry with no `type` as stdio, a `url` there or not
        command, args = spec.get("command"), spec.get("args", [])
        if not command or not isinstance(command, str) or not isinstance(args, list) or not all(
                isinstance(arg, str) for arg in args):
            raise Refused("unreadable", name)
        found.command, found.args = command, args
        if command not in plugin_package._RUNTIMES:
            found.kind = "program"
            found.fixed, found.asked = _settings(name, spec.get("env"), plugin_package._ENV_NAME, None)
            for part in [command, *args]:    # the sheet shows what runs, whole; a variable has no value to run with
                if plugin_package._ANY_VAR.search(plugin_package._whole(name, part)):
                    raise Refused("cannot_pin", name)
            return
        found.kind = "package"
        env = spec.get("env")
        if isinstance(env, dict):
            env = {key: value for key, value in env.items() if key.upper() != "PATH"}
        found.fixed, found.asked = _settings(name, env, plugin_package._ENV_NAME, plugin_package._UNSAFE_ENV)
        found.line = plugin_package.package_line(name, spec)[1]
        return
    found.kind = "remote"
    found.url = spec["url"] if isinstance(spec.get("url"), str) else None
    found.address = _address(found.url) if found.url else None
    found.fixed, found.asked = _settings(name, spec.get("headers"), plugin_package._HEADER_NAME, plugin_package._UNSAFE_HEADER)
    if spec.get("headersHelper"):       # a command Arslan won't run to get the headers
        raise Refused("runs_a_helper", name)
    if transport not in ("http", "streamable-http"):        # `sse`, `ws`, `sdk`: Arslan speaks streamable HTTP
        raise Refused("transport", name)
    plugin_package.remote_url(name, spec)
    if found.address is None:
        raise Refused("unreadable", name)


def _found(tool: str, name: str, raw) -> Found:
    # A file's name can hold a lone surrogate, which a response can't encode: the id is opaque, and only has to match.
    found = Found(id=f"{tool}:{name}".encode("utf-8", "backslashreplace").decode(), tool=tool,
                  name=untrusted.clean_name(name, 120), digest="")
    try:
        found.digest = _digest(tool, name, raw)
        if not isinstance(raw, dict):
            raise Refused("unreadable", name)
        found.on_there = raw.get("enabled") is not False
        found.tool_limits = "enabled_tools" in raw or "disabled_tools" in raw
        _read_line(found, name, _codex_shape(raw) if tool == "codex" else raw)
    except Refused as exc:
        found.refused, found.refused_part = exc.code, untrusted.clean_name(exc.part, 200)
    except (ValueError, RecursionError):    # one entry no parser can read (`.host` decodes a bad `xn--` label) or hash: the others stay
        found.refused, found.refused_part = "unreadable", found.name
    return found


def _servers_in(path: Path, parse, key: str) -> tuple[str, dict]:
    """(how the file read, its servers). A parser's message can quote the file, so none goes anywhere."""
    try:
        data = parse(path.read_bytes())
    except FileNotFoundError:
        return "missing", {}
    except (OSError, ValueError, RecursionError):
        return "malformed", {}
    servers = data.get(key, {}) if isinstance(data, dict) else None
    return ("read", servers) if isinstance(servers, dict) else ("malformed", {})


def _read_all() -> tuple[list[dict], list[Found]]:
    home = Path.home()
    files = (("claude_code", home / ".claude.json", json.loads, "mcpServers"),
             ("codex", home / ".codex" / "config.toml", lambda data: tomllib.loads(data.decode()), "mcp_servers"))
    tools, found = [], []
    for tool, path, parse, key in files:
        state, servers = _servers_in(path, parse, key)
        tools.append({"tool": tool, "state": state, "count": len(servers)})
        found += [_found(tool, name, raw) for name, raw in servers.items()]
    return tools, found


async def _here() -> set[str]:
    """What runs here now, by the same identity: every server row, and what an installed one came from. A source
    that holds no server (removed, or an install that failed before one) can be brought in again."""
    async with db_session.AsyncSessionLocal() as db:
        servers = (await db.execute(select(MCPServer))).scalars().all()
        sources = (await db.execute(select(CapabilitySource).where(
            CapabilitySource.kind == "mcp", CapabilitySource.mcp_server_id.is_not(None),
            CapabilitySource.state != "removed"))).scalars().all()
    here = {_url_identity(s.url) if s.url else _line_identity(s.command, s.args or []) for s in servers}
    for source in sources:
        package = (source.candidate or {}).get("package") or {}
        if source.runtime in _COMMAND_OF and package.get("identifier"):
            here.add(_line_identity(_COMMAND_OF[source.runtime], [
                package["identifier"], *[str(arg["value"]) for arg in package.get("arguments") or [] if arg.get("value")]]))
    return here


async def scan() -> dict:
    tools, found = await asyncio.to_thread(_read_all)
    here = await _here()
    first: dict[str, str] = {}
    rows = []
    for server in found:
        identity = server.identity()
        same_as = first.setdefault(identity, server.id)
        rows.append(server.view(here=identity in here, same_as=None if same_as == server.id else same_as))
    return {"tools": tools, "servers": rows}


def _moved(label: str, url: str | None, args: list[str]) -> tuple[str | None, list[str], dict]:
    """Each secret-looking part of an address or arguments out to its own name, a placeholder in its place."""
    values: dict[str, str] = {}
    for part in cs.find(url, args):
        name, n = cs.suggest_name(label, part), 1
        while name in values:
            n += 1
            name = f"{cs.suggest_name(label, part)[:58]}_{n}"
        url, args, values = cs.move(url, args, part, name, values)
    return url, args, values


async def _candidate(server: Found, env: dict) -> tuple[dict, dict]:
    """The candidate and its lock, as a one-click card has them. `needs` holds names: the values go in `env`."""
    if server.kind == "remote":
        url, _, moved = _moved(server.name, server.url, [])
        part = plugin_package._part_candidate({}, server.name, runtime="remote", version=None, package=None,
                                              remote={"url": url}, needs={"keys": [], "network": True})
    else:
        _, rest, moved = _moved(server.name, None, server.line[1:])
        part = (await plugin_package.pinned_package({}, server.name, server.command, [server.line[0], *rest], [],
                                                    server.fixed))["candidate"]
    part["needs"]["keys"] = [{"name": name, "required": True, "secret": True, "description": ""} for name in [*env, *moved]]
    candidate = {**part, "id": f"{SOURCE}:{server.id}", "source": SOURCE}
    return candidate, {**await capability_install.prepare(candidate), "secrets": moved}


async def _add_one(server: Found | None, tick: dict, here: set[str]) -> dict:
    if server is None:
        return {"state": "gone"}
    if server.digest != tick["digest"]:
        return {"state": "changed"}
    if server.refused:
        return {"state": "refused", "code": server.refused}
    if server.identity() in here:
        return {"state": "here"}
    given = {key: value.strip() for key, value in tick["keys"].items()}
    missing = [name for name in server.asks() if not given.get(name)]
    if missing:
        return {"state": "needs_keys", "keys": missing}
    env = {**server.fixed, **{setting: scheme + given[variable] for setting, (scheme, variable) in server.asked.items()}}
    locked = None
    try:
        if server.kind == "program":        # no lock, no test, no sandbox: as the hand-add form adds one
            _, args, moved = _moved(server.name, None, server.args)
            added = await mcp_service.add_server(server.name, server.command, args, env, secrets=moved)
            return {"state": "added", "server_id": added["id"]}
        candidate, locked = await _candidate(server, env)
        out = await capability_flow.install_mcp(candidate, folders=[], keys=env, prepared=locked)
    except Refused as exc:
        return {"state": "refused", "code": exc.code}
    except (mcp_pin.PinRefused, mcp_service.AddRefused):
        return {"state": "refused", "code": "cannot_pin"}
    except (capability_install.InstallFailure, capability_runtime.RuntimeFailure) as exc:
        return {"state": "failed", "stage": "install", "code": exc.code}
    except Exception as exc:  # noqa: BLE001 — one server's failure isn't the others'; its text could quote a key
        logger.warning("an imported connection did not install (%s)", type(exc).__name__)
        return {"state": "failed", "stage": "install", "code": type(exc).__name__}
    finally:
        capability_install.discard(locked)
    result = {key: out[key] for key in ("state", "source_id", "stage", "code") if key in out}
    if "detail" in out:
        result["detail"] = capability_flow._plain(str(out["detail"]), keep="\n")[:400]
    return {**result, "tools": len(out.get("tools") or [])}


async def add(ticked: list[dict]) -> list[dict]:
    """Each ticked server, from the file as it reads now, with its own result. The result's words: `on`,
    `needs_sign_in`, `failed` and `blocked` as a card's install, `added` for a custom program, whose start runs in the
    background as a hand-added one's does, or `refused`, `here`, `needs_keys`, or `gone` and `changed` when the file no
    longer holds what the sheet showed. Scan again after those two."""
    async with _ONE_AT_A_TIME:
        found = {server.id: server for server in (await asyncio.to_thread(_read_all))[1]}
        return [{"id": tick["id"], **await _add_one(found.get(tick["id"]), tick, await _here())} for tick in ticked]
