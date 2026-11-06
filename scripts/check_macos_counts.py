#!/usr/bin/env python3
"""The macOS job's "Assert they RAN, and did not skip": its JUnit file against tests/macos_expected.toml.

pytest exits 0 when every selected test is skipped, so without this the job would go green on a runner that lacks Vision
or refuses seatbelt. A skip here is a silent pass. And a strict xfail that goes on failing is not the same as a surface
that was built: an adapter registered under the wrong key keeps a p PR's cases xfailing with the job green. So every file
has its own pins, for the cases that ran and for the strict xfails among them.

Per file, not one total, so PRs that touch different files don't touch the same lines, and so dropping tests in one file
and adding as many in another fails. Red on any skip, any failure, a file whose numbers differ from its pins, a file in the
manifest with no results, and results from a file with no table.

    scripts/check_macos_counts.py macos-results.xml tests/macos_expected.toml
"""
from __future__ import annotations

import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

RECOUNT = ("A pin that differs right after a merge means two PRs combined; recount that file. Otherwise a number moves "
           "only with the tests that move it, from what this job printed.")


def file_of(classname: str) -> str | None:
    """The test file a JUnit classname comes from, relative to tests/: `tests.server.test_x.TestY` is
    `server/test_x.py`. None when it names no test file."""
    parts = classname.split(".")
    parts = parts[1:] if parts[:1] == ["tests"] else parts
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[:index + 1]) + ".py"
    return None


def read_results(junit: Path) -> tuple[dict[str, dict[str, int]], list[str], list[str]]:
    """Per file {cases, xfail}, the cases that were really skipped, and the ones that failed.

    pytest writes a strict xfail that failed as expected as `<skipped type="pytest.xfail">`: it ran, so it counts as ran.
    A strict xfail that passed is a `<failure>`."""
    seen: dict[str, dict[str, int]] = {}
    skipped: list[str] = []
    failed: list[str] = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        classname = case.get("classname", "")
        label = f"{classname}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(label)
        skip = case.find("skipped")
        if skip is not None and skip.get("type") != "pytest.xfail":
            skipped.append(label)
            continue
        counts = seen.setdefault(file_of(classname) or f"(no test file) {classname}", {"cases": 0, "xfail": 0})
        counts["cases"] += 1
        counts["xfail"] += skip is not None
    return seen, skipped, failed


def problems(manifest: dict[str, dict[str, int]], seen: dict[str, dict[str, int]], skipped: list[str],
             failed: list[str]) -> list[str]:
    found = []
    if skipped:
        found.append(f"{len(skipped)} SKIPPED, and a skip here is a silent pass: {', '.join(skipped[:5])}")
    if failed:
        found.append(f"{len(failed)} failed or errored: {', '.join(failed[:5])}")
    for path, pins in manifest.items():
        got = seen.get(path)
        if got is None:
            found.append(f"{path}: in the manifest but no case of it ran; if it was deleted on purpose, delete its table")
            continue
        if got["cases"] != pins["cases"]:
            found.append(f"{path}: {got['cases']} cases ran, pinned {pins['cases']}")
        if got["xfail"] != pins["xfail"]:
            found.append(f"{path}: {got['xfail']} strict xfails, pinned {pins['xfail']}: a surface was built, or a "
                         "gate's failure was absorbed, without moving the number")
    found.extend(f"{path}: results but no table in the manifest (cases = {got['cases']}, xfail = {got['xfail']})"
                 for path, got in seen.items() if path not in manifest)
    return found


def main(argv: list[str]) -> int:
    junit, manifest_path = Path(argv[0]), Path(argv[1])
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    seen, skipped, failed = read_results(junit)
    ran, xfailed = sum(c["cases"] for c in seen.values()), sum(c["xfail"] for c in seen.values())
    print(f"files={len(seen)} ran={ran} skipped={len(skipped)} xfailed={xfailed} failed={len(failed)}")
    found = problems(manifest, seen, skipped, failed)
    if found:
        for line in found:
            print(f"::error::{line}")
        print(RECOUNT)
        return 1
    print(f"all {ran} macOS-only cases in {len(seen)} files executed on the shipping platform")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
