"""Check a cargo `vendor/` tree against its own `.cargo-checksum.json` files.

Cargo verifies these when it builds offline, but here that build only happens on
a Mac release run (agent-desktop is macOS-only). This check runs anywhere in
seconds, so a vendored file that git never received fails the pull request, not
the release build. Measured: the fork's `.vim/` ignore rule kept memchr's and
aho-corasick's `.vim/coc-settings.json` out of the vendoring commit; a checkout
that still had them on disk built, a clean fetch did not.

    python3 scripts/verify_vendored_checksums.py third_party/agent-desktop/vendor
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys


def problems(vendor: pathlib.Path) -> list[str]:
    """Every listed file that is missing or differs, per crate; [] when the tree is whole."""
    crates = sorted(p for p in vendor.iterdir() if p.is_dir()) if vendor.is_dir() else []
    if not crates:
        return [f"{vendor}: no vendored crates"]
    found = []
    for crate in crates:
        sums = crate / ".cargo-checksum.json"
        if not sums.is_file():
            found.append(f"{crate.name}: no .cargo-checksum.json")
            continue
        for rel, expected in sorted(json.loads(sums.read_text()).get("files", {}).items()):
            path = crate / rel
            if not path.is_file():
                found.append(f"{crate.name}/{rel}: missing")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                found.append(f"{crate.name}/{rel}: checksum differs")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify_vendored_checksums.py <vendor dir>", file=sys.stderr)
        return 2
    found = problems(pathlib.Path(argv[1]))
    for line in found:
        print(line)
    print(f"{len(found)} vendored file problem(s)" if found else "every vendored file matches its checksum")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
