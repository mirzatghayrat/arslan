"""Writing seatbelt profiles: the one place Arslan turns paths and permissions into SBPL (SBX-1, v0.1.64).

The profiles Arslan starts processes under are written with this module: commands in and out of
the sandbox (`command_sandbox.profile`, `minimal_profile`), `run_python` and the artifact checks
(`code_sandbox.computation_profile`), installed MCP servers (`capability_sandbox.profile`) and
`ssh_run` (`ssh_exec.ssh_profile`). Each of those keeps its own rules; SBX-1 moved how they are
written here without changing a byte of what they produce, and SBX-1b changed how a path is spelt
(below). SBX-2 adds the default-deny base that SBX-3 and SBX-4 move them onto
(docs/plans/0164/SBX-sandbox.md). Two texts are still written by hand: `command_sandbox.available()`'s
probe, which SBX-3 replaces with the real commands profile, and `code_sandbox._SEATBELT_PROFILE`,
which no product caller reaches and SBX-4 deletes.

What every profile relies on:

- Seatbelt applies the LAST matching rule (measured 2026-10-03), so the order of the rules is the
  policy: a deny written after an allow wins over it, and the other way round.
- Rules match real paths, so callers resolve every path before it goes in (`real`).
- A path is written as an SBPL string (`sbpl_string`): its own UTF-8, with `\\` and `"` escaped, so a
  folder name cannot add rules, and control characters as `\\xHH`. sandbox-exec decodes those but
  not `\\uXXXX`, which is how `json.dumps` wrote every non-ASCII character until SBX-1b: a rule on a
  CJK- or accent-named path then landed on a path that does not exist, so a deny on such a folder
  missed and an allow on one refused (②Main's review of #471; measured on macOS 26.6.2). Unicode
  normalization does not matter: a rule written in NFC matches a folder stored in NFD, and the other
  way round (measured).
- A rule without a filter matches everything: `(allow file-read*)` opens every file. So `allow_paths`
  leaves the rule out when its list is empty, instead of writing it bare. A deny is written as the
  profile asks: over no paths it denies everything, which fails closed.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path


def real(path) -> Path:
    """`path` with `~` expanded and every link resolved: what seatbelt compares against."""
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def sbpl_string(text: str) -> str:
    """`text` as an SBPL string literal: its own characters, `\\` and `"` escaped, control characters
    (below U+0020, and U+007F) as `\\xHH`. For printable ASCII this is exactly what `json.dumps` wrote."""
    out = []
    for ch in text:
        if ch in ('\\', '"'):
            out.append("\\" + ch)
        elif ch < " " or ch == "\x7f":
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def subpath(path) -> str:
    """The path and everything under it."""
    return f"(subpath {sbpl_string(str(path))})"


def literal(path) -> str:
    """Exactly this path."""
    return f"(literal {sbpl_string(str(path))})"


def file_or_folder(path: Path) -> str:
    """`literal` for an existing file, `subpath` for a folder or a path that does not exist (yet)."""
    return literal(path) if path.is_file() else subpath(path)


def remote_tcp(host: str, port: int) -> str:
    """An outbound TCP destination. The host must be `*` or `localhost`: sandbox-exec rejects an
    address (measured 2026-08-21, `ssh_exec`)."""
    return f"(remote tcp {sbpl_string(f'{host}:{port}')})"


class Profile:
    """The rules of one profile, in the order they are added (the last matching rule wins)."""

    def __init__(self, default: str):
        self._lines = ["(version 1)", f"({default} default)"]

    def allow(self, operations: str, *filters: str) -> None:
        self._lines.append(_rule("allow", operations, filters))

    def deny(self, operations: str, *filters: str) -> None:
        self._lines.append(_rule("deny", operations, filters))

    def allow_paths(self, operations: str, paths: Iterable, kind: Callable[[Path], str] = subpath) -> None:
        """One allow rule over `paths`; none at all when there are none."""
        filters = [kind(path) for path in paths]
        if filters:
            self.allow(operations, *filters)

    def text(self) -> str:
        return "\n".join(self._lines) + "\n"


def _rule(verb: str, operations: str, filters: tuple[str, ...]) -> str:
    return "(" + " ".join((verb, operations, *filters)) + ")"
