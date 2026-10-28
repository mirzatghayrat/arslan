"""Writing seatbelt profiles: the one place Arslan turns paths and permissions into SBPL (SBX-1, v0.1.64).

Every profile Arslan starts a process under is written with this module: commands in and out of
the sandbox (`command_sandbox.profile`, `minimal_profile`), `run_python` and the artifact checks
(`code_sandbox.computation_profile`), installed MCP servers (`capability_sandbox.profile`) and
`ssh_run` (`ssh_exec.ssh_profile`). Each of those keeps its own rules; SBX-1 moved how they are
written here without changing a byte of what they produce. SBX-2 adds the default-deny base that
SBX-3 and SBX-4 move them onto (docs/plans/0164/SBX-sandbox.md).

What every profile relies on:

- Seatbelt applies the LAST matching rule (measured 2026-10-03), so the order of the rules is the
  policy: a deny written after an allow wins over it, and the other way round.
- Rules match real paths, so callers resolve every path before it goes in (`real`).
- Paths are written as JSON strings, which are valid SBPL strings, so a folder name cannot add rules.
- A rule without a filter matches everything: `(allow file-read*)` opens every file. So `allow_paths`
  leaves the rule out when its list is empty, instead of writing it bare. A deny is written as the
  profile asks: over no paths it denies everything, which fails closed.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path


def real(path) -> Path:
    """`path` with `~` expanded and every link resolved: what seatbelt compares against."""
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def subpath(path) -> str:
    """The path and everything under it."""
    return f"(subpath {json.dumps(str(path))})"


def literal(path) -> str:
    """Exactly this path."""
    return f"(literal {json.dumps(str(path))})"


def file_or_folder(path: Path) -> str:
    """`literal` for an existing file, `subpath` for a folder or a path that does not exist (yet)."""
    return literal(path) if path.is_file() else subpath(path)


def remote_tcp(host: str, port: int) -> str:
    """An outbound TCP destination. The host must be `*` or `localhost`: sandbox-exec rejects an
    address (measured 2026-08-21, `ssh_exec`)."""
    return f"(remote tcp {json.dumps(f'{host}:{port}')})"


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
