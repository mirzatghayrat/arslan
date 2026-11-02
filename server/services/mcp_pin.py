"""A hand-added `npx` or `uvx` package is pinned to one version, or refused (v0.1.64 CAP5c; the CAP card, "a
hand-added MCP package's version": a package with no version is looked up and written as that exact version, and
one that cannot be looked up is refused).

Without a version, `npx -y pkg` and `uvx pkg` run whatever the registry serves at each start: a new release runs
with nobody having asked. A one-click install already pins its lock before the card (CAP4a-2); this is the same
floor for the form in Capabilities.

- **What is read before the package** (#623 review M-1): for npx, `-y`, `--yes`, `-q`, `--quiet`, and `--registry`
  and `--cache` with their values; for uvx (and `uv tool run`, the same command), `--isolated`, `-q`, `--quiet`, and
  `--python`/`-p`, `--index-url`, `--default-index`, `--index` and `--extra-index-url` with their values. The
  package is the value of `-p`/`--package` (npx) or `--from` (uvx), else the first argument after those. Any other
  option before it is refused (`--with` among them: it adds packages of its own), since Arslan cannot tell whether
  it takes a value; the message names what Arslan reads, and never asks to move an option past the package (uv
  and npx would then hand it to the server).
- **The version:** an exact one is kept as written, whatever comes before it (npm's `=1.2.3` and `v1.2.3` are
  written as `1.2.3`). None, or a dist-tag (`@latest`, `@next`), is looked up on the public npm registry or PyPI
  and written as the exact version it names. A range (`@^1.2`, `>=1`) is refused with what to write instead
  (⓪Plan's call: the card names only "no version", and the message says what to write).
- **Another registry** (#623 review L-2, re-check R-2): when the line names one (`--registry`, a uv index option) or
  the connection's env does (`npm_config_registry`, a scope's `npm_config_@acme:registry`, `npm_config_userconfig`,
  `npm_config_globalconfig`, `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_INDEX`, `UV_EXTRA_INDEX_URL`, `UV_FIND_LINKS`,
  `UV_CONFIG_FILE`; any case), a version that is not exact is refused: the public answer says nothing about that
  registry.
- **Refused too:** a spec that is not a registry package (a git or file spec, a URL, a path, an archive).

**Stated limits:**
- **Other launchers and wrappers are left as written:** `bunx`, `bun x`, `pnpm dlx`, `npm exec`, `npm x`,
  `yarn dlx`, `pipx run`, `uv run`, `env npx …`, `docker`, a shell (`sh -c "npx …"`, `bash -lc "…"`: shell strings
  are not parsed), and a command that is a path to a program. Their packages are not pinned. `uv tool run` is read
  only when those are uv's first two arguments (`uv --offline tool run …` is left as written).
- **A short option written with `=`** (`-p=3.12`) is not split: it is refused as an option Arslan does not read.
- **Registry settings outside the connection are not read** (`~/.npmrc`, a project's `.npmrc`, `uv.toml`,
  `pyproject.toml`). When the package's name is on such a registry and also on the public one, Arslan writes the
  public registry's latest version, and the user's registry is then asked for that version: it may not have it, or
  serve something else under it.
- **Only the named package is pinned,** not its dependencies.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote

import httpx

from arslan.aio import within
from server.services import connection_secrets

NPM_REGISTRY = "https://registry.npmjs.org"
PYPI = "https://pypi.org/pypi"
TIMEOUT_S = 10.0
#: One limit for everything a pin asks (#623 review I-2).
DEADLINE_S = 20.0
#: npm's dist-tags document is a few hundred bytes; PyPI's JSON lists every release.
MAX_BYTES = {"npm": 256 * 1024, "pypi": 8 * 1024 * 1024}

#: What Arslan reads before the package (#623 review M-1).
_OPTIONS = {
    "npx": {"plain": {"-y", "--yes", "-q", "--quiet"}, "value": {"--registry", "--cache"},
            "package": {"-p", "--package"}, "registry": {"--registry"}},
    "uvx": {"plain": {"--isolated", "-q", "--quiet"},
            "value": {"--python", "-p", "--index-url", "--default-index", "--index", "--extra-index-url"},
            "package": {"--from"}, "registry": {"--index-url", "--default-index", "--index", "--extra-index-url"}},
}
_READS = {"npx": "-y, --yes, -q, --quiet, -p, --package, --registry and --cache",
          "uvx": "--from, --python, -p, --index-url, --default-index, --index, --extra-index-url, --isolated, -q "
                 "and --quiet"}
#: The public registries: naming one of them is not naming another.
_PUBLIC = {"npx": {"https://registry.npmjs.org"}, "uvx": {"https://pypi.org/simple"}}
#: Env that sends the tool to another registry or index (#623 review L-2, re-check R-2), case-blind: npm's
#: registry, a scope's registry (`npm_config_@acme:registry`), its user and global config files; uv's index options,
#: `--find-links` and config file.
_REGISTRY_ENV = {"npx": re.compile(r"npm_config_((@[^:]+:)?registry|userconfig|globalconfig)", re.I),
                 "uvx": re.compile(r"uv_(index_url|default_index|index|extra_index_url|find_links|config_file)", re.I)}

_NPM_NAME = re.compile(r"(@[A-Za-z0-9~][A-Za-z0-9._~-]*/)?[A-Za-z0-9~][A-Za-z0-9._~-]*")
#: SemVer 2.0.0's own pattern (semver.org).
_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                     r"(-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
                     r"(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?")
#: A dist-tag: a word that npm would not read as a range (`v1`, `x` and `X` are ranges).
_NPM_TAG = re.compile(r"(?![vV]?\d)(?![xX]$)[A-Za-z][A-Za-z0-9._-]*")
_PYPI_NAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(\[[A-Za-z0-9._,\s-]*\])?")
#: PEP 440's version grammar (the `packaging` library's VERSION_PATTERN): one version, no operator.
_PEP440 = re.compile(r"""v?([0-9]+!)?[0-9]+(\.[0-9]+)*
                         ([-_.]?(alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?
                         (-[0-9]+|[-_.]?(post|rev|r)[-_.]?[0-9]*)?
                         ([-_.]?dev[-_.]?[0-9]*)?
                         (\+[a-z0-9]+([-_.][a-z0-9]+)*)?""", re.X | re.I)
_ARCHIVE = re.compile(r"\.(tgz|tbz|txz|tar|tar\.(gz|bz2|xz|zst)|whl|zip)$", re.I)
#: The one redirect PyPI's JSON gives, from a name to its canonical form (#623 review L-4).
_PYPI_JSON = re.compile(r"https://pypi\.org/pypi/[A-Za-z0-9._-]+/json")


class PinRefused(ValueError):
    """The form's message: what was read and why it was not pinned."""


class ResponseTooLarge(ValueError):
    """A registry answer past `MAX_BYTES`."""


_URL_INSIDE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


def _shown(text: str) -> str:
    """An argument as the form may echo it: SEC1's masking (#623 review L-6), so a token in a URL stays out. SEC1
    reads an argument that is a URL; a URL inside one (`name@https://…`) is masked as an address of its own."""
    masked = connection_secrets.shown(None, [text])[1][0]
    return _URL_INSIDE.sub(lambda m: connection_secrets.shown(m.group(0), [])[0] or m.group(0), masked)


def _spec_shown(spec: str, name_ok: bool) -> str:
    """A spec as a refusal echoes it (#623 re-check R-1): as typed when it reads as a package name and a version
    (SEC1's entropy check would hide an ordinary `.whl` name), and masked when it is anything else."""
    return spec if name_ok and not re.search(r"[:/]", spec.lstrip("@").split("/", 1)[-1]) else _shown(spec)


def _option_shown(arg: str) -> str:
    """An option Arslan does not read, by its name alone (#623 re-check R-1): `--x=…`, never what follows `=`."""
    name, eq, _ = arg.partition("=")
    return _shown(name) + ("=…" if eq else "")


async def _get_json(client: httpx.AsyncClient, url: str, kind: str):
    """The JSON at `url`, at most `MAX_BYTES[kind]`. No redirect is followed, but PyPI's one from a name to its
    canonical form, and only to another `https://pypi.org/pypi/<name>/json`."""
    for hop in (0, 1):
        async with client.stream("GET", url) as r:
            target = str(r.url.join(r.headers.get("location", ""))) if r.is_redirect else ""
            if kind == "pypi" and hop == 0 and _PYPI_JSON.fullmatch(target):
                url = target
                continue
            r.raise_for_status()
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES[kind]:
                    raise ResponseTooLarge(f"over {MAX_BYTES[kind]} bytes")
            return json.loads(bytes(body))
    raise ResponseTooLarge("a second redirect")                # unreachable: hop 1 never continues


async def _lookup(kind: str, name: str, tag: str) -> str:
    """The exact version `tag` names for `name` on the npm registry (`kind` "npm") or PyPI ("pypi", latest only).
    Tests stub this."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
        if kind == "npm":
            tags = await _get_json(client, f"{NPM_REGISTRY}/-/package/{quote(name, safe='@')}/dist-tags", kind)
            version = tags.get(tag) if isinstance(tags, dict) else None
        else:
            doc = await _get_json(client, f"{PYPI}/{quote(name, safe='')}/json", kind)
            info = doc.get("info") if isinstance(doc, dict) else None
            version = info.get("version") if isinstance(info, dict) else None
    return version if isinstance(version, str) else ""


async def _exact(kind: str, name: str, tag: str) -> str:
    where = "npm registry" if kind == "npm" else "PyPI"
    try:
        version = await _lookup(kind, name, tag)
    except httpx.HTTPStatusError as exc:
        raise PinRefused(f"{where}: no version found for {name}@{tag} (HTTP {exc.response.status_code}). Check the "
                         f"name, or write an exact version.") from exc
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise PinRefused(f"{where}: no answer for {name}@{tag} ({type(exc).__name__}). Try again online, or write "
                         f"an exact version.") from exc
    if not (_SEMVER if kind == "npm" else _PEP440).fullmatch(version):
        raise PinRefused(f"{where}: no version found for {name}@{tag}. Write an exact version.")
    return version


def _elsewhere(label: str, spec: str, where: str, example: str) -> PinRefused:
    return PinRefused(f"{label}: {_spec_shown(spec, True)} has no exact version, and this connection names its own "
                      f"registry ({where}), so Arslan can't look the version up. Write an exact version, as {example}.")


async def _pin_npm(spec: str, elsewhere: str | None) -> str:
    """`name`, `name@tag` or `name@1.2.3` (scoped names too), as `name@<exact>`."""
    at = spec.rfind("@")
    name, version = (spec[:at], spec[at + 1:]) if at > 0 else (spec, "")
    if not _NPM_NAME.fullmatch(name) or _ARCHIVE.search(spec) or ":" in version or "/" in version:
        raise PinRefused(f"npx: {_spec_shown(spec, bool(_NPM_NAME.fullmatch(name)))} is not a package on the npm "
                         f"registry, so it can't be pinned. Write name@1.2.3.")
    exact = re.fullmatch(r"=?v?(.+)", version)                  # npm reads `=1.2.3` and `v1.2.3` as 1.2.3
    if exact and _SEMVER.fullmatch(exact.group(1)):
        return spec if exact.group(1) == version else f"{name}@{exact.group(1)}"
    if version and not _NPM_TAG.fullmatch(version):
        raise PinRefused(f"npx: {_spec_shown(spec, True)} names a range. Write an exact version, as {name}@1.2.3.")
    if elsewhere:
        raise _elsewhere("npx", spec, elsewhere, f"{name}@1.2.3")
    return f"{name}@{await _exact('npm', name, version or 'latest')}"


async def _pin_pypi(spec: str, sep: str, elsewhere: str | None, label: str) -> str:
    """`name`, `name@latest` or an exact version, as `name<sep><exact>`; extras are kept. `sep` is `@` for the
    package uvx runs and `==` after `--from`."""
    for op in ("==", "@"):
        if op in spec:
            name, version = spec.split(op, 1)
            break
    else:
        name, version = spec, ""
        if re.search(r"[<>=!~]", spec) and not re.search(r"[:/]", spec):    # `name>=1`, `name~=1.2`
            name, version = re.split(r"\s*[<>=!~]", spec, maxsplit=1)[0], "*"
    name, version = name.strip(), version.strip()
    if not _PYPI_NAME.fullmatch(name) or _ARCHIVE.search(spec) or ":" in version or "/" in version:
        raise PinRefused(f"{label}: {_spec_shown(spec, bool(_PYPI_NAME.fullmatch(name)))} is not a package on "
                         f"PyPI, so it can't be pinned. Write name{sep}1.2.3.")
    if version and version != "latest":
        if _PEP440.fullmatch(version):
            return spec
        raise PinRefused(f"{label}: {_spec_shown(spec, True)} names a range. Write an exact version, as "
                         f"{name}{sep}1.2.3.")
    if elsewhere:
        raise _elsewhere(label, spec, elsewhere, f"{name}{sep}1.2.3")
    return f"{name}{sep}{await _exact('pypi', name.split('[', 1)[0], 'latest')}"


async def _pin(tool: str, label: str, args: list[str], env: dict) -> list[str]:
    opts, public = _OPTIONS[tool], _PUBLIC[tool]
    elsewhere = next((key for key, value in env.items() if _REGISTRY_ENV[tool].fullmatch(str(key))
                      and str(value).strip().rstrip("/") not in public), None)
    out, targets, i = list(args), [], 0          # targets: (where in out, "--flag" when written `--flag=spec`, sep)
    while i < len(out):
        arg = out[i]
        flag, eq, value = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        if arg in opts["plain"]:
            i += 1
            continue
        if flag in opts["value"] or flag in opts["package"]:
            if not eq and i + 1 >= len(out):
                raise PinRefused(f"{label}: {flag} has no value after it.")
            given = value if eq else out[i + 1]
            if flag in opts["package"]:
                targets.append((i, flag, "==") if eq else (i + 1, None, "=="))
            elif flag in opts["registry"] and given.strip().rstrip("/") not in public:
                elsewhere = elsewhere or flag
            i += 1 if eq else 2
            continue
        if arg.startswith("-"):
            raise PinRefused(f"{label}: {_option_shown(arg)} comes before the package. Before it, Arslan reads only "
                             f"{_READS[tool]}, so it can't tell which argument is the package.")
        if not targets:                        # the package itself; with -p or --from, this is the command it runs
            targets.append((i, None, "@"))
        break
    if not targets:
        raise PinRefused(f"{label}: no package to run was found in the arguments.")
    for at, flag, sep in targets:
        spec = out[at][len(flag) + 1:] if flag else out[at]
        pinned = await (_pin_npm(spec, elsewhere) if tool == "npx" else _pin_pypi(spec, sep, elsewhere, label))
        out[at] = f"{flag}={pinned}" if flag else pinned
    return out


async def pin(command: str, args: list[str], env: dict | None = None) -> list[str]:
    """`args` with the package pinned when `command` is npx, uvx or `uv tool run`; as given for any other command.
    The command is matched case-blind, as the Mac's file system finds `Npx` (#623 review L-1)."""
    tool, prefix, rest = os.path.basename((command or "").strip()).lower(), [], list(args or [])
    if tool == "uv" and rest[:2] == ["tool", "run"]:          # #623 review L-3: the same command as uvx
        tool, prefix, rest = "uvx", rest[:2], rest[2:]
    if tool not in _OPTIONS:
        return list(args or [])
    label = "uv tool run" if prefix else tool
    try:
        return prefix + await within(_pin(tool, label, rest, env or {}), DEADLINE_S)
    except TimeoutError as exc:
        raise PinRefused(f"{label}: the registry did not answer within {DEADLINE_S:.0f} seconds. Try again online, "
                         f"or write an exact version.") from exc
