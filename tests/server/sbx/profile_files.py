"""HR-1 #813 review 11: sandbox-exec takes the profile as a file (`-f`). For tests that read what a product wrapper
(`command_sandbox.wrapper`, `outside_wrapper`) or `capability_sandbox.wrap` starts: the profile's text, from the file
its argv names."""
from __future__ import annotations

from pathlib import Path

from server.services import command_sandbox


def profile_file(argv) -> Path:
    """The profile file a sandbox-exec prefix or an MCP server's args name with `-f`; fails when there is none."""
    path = command_sandbox.profile_path(argv)
    assert path is not None, f"no -f profile in {list(argv)[:3]}"
    return path


def read_profile(argv) -> str:
    """The text of that file."""
    return profile_file(argv).read_text(encoding="utf-8")


def with_profile_text(argv) -> tuple:
    """A launched sandbox-exec argv with the file's path replaced by its text (`argv[2]`, where `-p` had it), read at
    launch: the caller removes the file once the process has exited. Any other argv as it is."""
    argv = tuple(argv)
    if command_sandbox.profile_path(argv) is None or argv[:1] != (command_sandbox._SANDBOX_EXEC,):
        return argv
    return (*argv[:2], read_profile(argv), *argv[3:])
