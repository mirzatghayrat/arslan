"""A hand-added `npx` or `uvx` package is pinned to one version, or refused (v0.1.64 CAP5c; the CAP card, "a
hand-added MCP package's version": a package with no version is looked up and written as that exact version, and
one that cannot be looked up is refused).

Without a version, `npx -y pkg` and `uvx pkg` run whatever the registry serves at each start: a new release runs
with nobody having asked. A one-click install already pins its lock before the card (CAP4a-2); this is the same
floor for the form in Capabilities.

- **What is read:** the package from `-p`/`--package` (npx) or `--from` (uvx), else the first argument that is not a
  flag. Only `-y`, `--yes`, `-q` and `--quiet` may come before it; any other flag there is refused, since Arslan
  cannot tell whether it takes a value.
- **The version:** none, or a dist-tag (`@latest`, `@next`), is looked up on the npm registry or PyPI and written
  as the exact version it names. An exact version is kept as written. A range (`@^1.2`, `>=1`) is refused with what
  to write instead (⓪Plan's call: the card names only "no version", and the message says what to write).
- **Refused too:** a spec that is not a registry package (a git or file spec, a URL, a path).

**A stated limit:** other launchers are left as written: `bunx`, `pnpm dlx`, `npm exec`, `docker`, and a command
that is a path to a program. Their packages are not pinned.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote

import httpx

NPM_REGISTRY = "https://registry.npmjs.org"
PYPI = "https://pypi.org/pypi"
TIMEOUT_S = 10.0

#: Flags that take no value and may come before the package.
_PLAIN_FLAGS = {"npx": {"-y", "--yes", "-q", "--quiet"}, "uvx": {"-q", "--quiet"}}

_NPM_NAME = re.compile(r"(@[A-Za-z0-9~][A-Za-z0-9._~-]*/)?[A-Za-z0-9~][A-Za-z0-9._~-]*")
_SEMVER = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
#: A dist-tag: a word that npm would not read as a range (`v1`, `x` and `X` are ranges).
_NPM_TAG = re.compile(r"(?![vV]?\d)(?![xX]$)[A-Za-z][A-Za-z0-9._-]*")
_PYPI_NAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(\[[A-Za-z0-9._,\s-]*\])?")
#: An exact PEP 440 version: digits first, no operator, comma or wildcard.
_PEP440 = re.compile(r"\d[0-9A-Za-z.!+-]*")


class PinRefused(ValueError):
    """The form's message: what was read and why it was not pinned."""


async def _lookup(kind: str, name: str, tag: str) -> str:
    """The exact version `tag` names for `name` on the npm registry (`kind` "npm") or PyPI ("pypi", latest only).
    Tests stub this."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
        if kind == "npm":
            r = await client.get(f"{NPM_REGISTRY}/{quote(name, safe='@')}",
                                 headers={"Accept": "application/vnd.npm.install-v1+json"})
            r.raise_for_status()
            tags = r.json().get("dist-tags")
            version = tags.get(tag) if isinstance(tags, dict) else None
        else:
            r = await client.get(f"{PYPI}/{quote(name, safe='')}/json")
            r.raise_for_status()
            info = r.json().get("info")
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


async def _pin_npm(spec: str) -> str:
    """`name`, `name@tag` or `name@1.2.3` (scoped names too), as `name@<exact>`."""
    at = spec.rfind("@")
    name, version = (spec[:at], spec[at + 1:]) if at > 0 else (spec, "")
    if not _NPM_NAME.fullmatch(name) or ":" in version or "/" in version:
        raise PinRefused(f"npx: {spec} is not a package on the npm registry, so it can't be pinned. Write "
                         f"name@1.2.3.")
    if _SEMVER.fullmatch(version):
        return spec
    if version and not _NPM_TAG.fullmatch(version):
        raise PinRefused(f"npx: {spec} names a range. Write an exact version, as {name}@1.2.3.")
    return f"{name}@{await _exact('npm', name, version or 'latest')}"


async def _pin_pypi(spec: str, sep: str) -> str:
    """`name`, `name@latest` or an exact version, as `name<sep><exact>`; extras are kept. `sep` is `@` for the
    command uvx runs and `==` after `--from`."""
    for op in ("==", "@"):
        if op in spec:
            name, version = spec.split(op, 1)
            break
    else:
        name, version = spec, ""
        if re.search(r"[<>=!~]", spec) and not re.search(r"[:/]", spec):    # `name>=1`, `name~=1.2`
            name, version = re.split(r"\s*[<>=!~]", spec, maxsplit=1)[0], "*"
    name, version = name.strip(), version.strip()
    if not _PYPI_NAME.fullmatch(name) or ":" in version or "/" in version:
        raise PinRefused(f"uvx: {spec} is not a package on PyPI, so it can't be pinned. Write name{sep}1.2.3.")
    if version and version != "latest":
        if _PEP440.fullmatch(version):
            return spec
        raise PinRefused(f"uvx: {spec} names a range. Write an exact version, as {name}{sep}1.2.3.")
    return f"{name}{sep}{await _exact('pypi', name.split('[', 1)[0], 'latest')}"


async def pin(command: str, args: list[str]) -> list[str]:
    """`args` with the package pinned when `command` is npx or uvx; as given for any other command."""
    tool = os.path.basename((command or "").strip())
    if tool not in _PLAIN_FLAGS:
        return list(args)
    out, pinned, i = list(args), False, 0
    while i < len(out):
        arg = out[i]
        if arg in _PLAIN_FLAGS[tool]:
            i += 1
            continue
        value_flag = ("-p", "--package") if tool == "npx" else ("--from",)
        if arg in value_flag and i + 1 < len(out):
            out[i + 1] = await (_pin_npm(out[i + 1]) if tool == "npx" else _pin_pypi(out[i + 1], "=="))
            pinned, i = True, i + 2
            continue
        flag, _, value = arg.partition("=")
        if flag in value_flag and value:
            out[i] = f"{flag}={await (_pin_npm(value) if tool == 'npx' else _pin_pypi(value, '=='))}"
            pinned, i = True, i + 1
            continue
        if arg.startswith("-"):
            raise PinRefused(f"{tool}: {arg} comes before the package, and Arslan can't tell which package to pin. "
                             f"Put the package first, with an exact version.")
        if not pinned:                         # the package itself; with -p or --from, this is the command it runs
            out[i] = await (_pin_npm(arg) if tool == "npx" else _pin_pypi(arg, "@"))
        return out
    if not pinned:
        raise PinRefused(f"{tool}: no package to run was found in the arguments.")
    return out
