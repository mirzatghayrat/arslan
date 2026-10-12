"""GitHub-shaped tar.gz archives built in memory, for the skills tests (0.1.61 §C2).

A codeload archive has one top folder (`owner-repo-<short sha>`) and a global pax header whose
`comment` is the commit — `git archive` writes it there, and the importer pins to it.
"""
from __future__ import annotations

import io
import tarfile
import uuid
from pathlib import Path

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def tarball(files: dict, *, commit: str = COMMIT, top: str = "example-org-example-skills-0123456") -> bytes:
    """`files`: path -> str | bytes (a file, 0644) | ("exec", text) (0755) | ("mode", mode, text) |
    ("link", target) (a symlink) | ("hardlink", path) | ("fifo",)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": commit}) as tar:
        root = tarfile.TarInfo(top)
        root.type, root.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(root)
        for path, spec in files.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            if isinstance(spec, tuple) and spec[0] == "link":
                info.type, info.linkname = tarfile.SYMTYPE, spec[1]
                tar.addfile(info)
                continue
            if isinstance(spec, tuple) and spec[0] == "hardlink":
                info.type, info.linkname = tarfile.LNKTYPE, f"{top}/{spec[1]}"
                tar.addfile(info)
                continue
            if isinstance(spec, tuple) and spec[0] == "fifo":
                info.type = tarfile.FIFOTYPE
                tar.addfile(info)
                continue
            mode, text = 0o644, spec
            if isinstance(spec, tuple) and spec[0] == "exec":
                mode, text = 0o755, spec[1]
            elif isinstance(spec, tuple) and spec[0] == "mode":
                mode, text = spec[1], spec[2]
            data = text.encode("utf-8") if isinstance(text, str) else text
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def case_insensitive(folder: Path) -> bool:
    """Whether this disk treats README.md and readme.md as one name (a Mac's default disk does)."""
    probe = folder / f"Case-{uuid.uuid4().hex[:6]}"
    probe.write_text("x")
    try:
        return (folder / probe.name.lower()).exists()
    finally:
        probe.unlink()
