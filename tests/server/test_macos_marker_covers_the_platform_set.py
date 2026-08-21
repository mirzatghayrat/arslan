"""Keep the `macos` marker in step with the tests that actually need it.

BACKGROUND. Arslan ships a macOS dmg, and until 2026-08-06 no CI job had ever
run pytest on macOS — all three ci.yml jobs are ubuntu-latest, and release.yml's
macos-latest job builds the bundle without running tests. A measurement compared
the skip lists from both platforms and found 25 tests that skip on Linux and had
therefore never executed anywhere, including three that prove the seatbelt
sandbox denies a chmod-then-write/unlink escape.

Those 25 now carry `@pytest.mark.macos` so a macOS job can select them.

WHAT THIS FILE CAN AND CANNOT DO. It cannot prove the marker set is COMPLETE —
completeness was established by running the suite on both platforms and
intersecting the skip lists, and only redoing that proves it again. What it can
do is fail when the set DRIFTS, which is the realistic failure: someone adds a
macOS-gated test, forgets the marker, and it silently joins the population of
tests that run nowhere. That is a tripwire, and it is described as one rather
than dressed up as a proof.
"""
from __future__ import annotations

import pathlib
import re

# The WHOLE test tree, not this one directory. `parent` was tests/server/ and the
# glob was non-recursive, so the drift check silently ignored the other seven test
# directories — a macOS-gated test added under tests/llm/ or tests/tools/ would
# have been exactly the invisible case this file exists to catch, and the file
# would have reported no offenders while looking at almost nothing.
TESTS = pathlib.Path(__file__).parents[1]

#: The measured set, 2026-08-06. Files, not test names: names churn, the
#: platform boundary does not.
EXPECTED_FILES: dict[str, int] = {
    "server/test_code_sandbox.py": 8,
    "server/test_ocr_vision.py": 5,
    "server/test_command_sandbox_net.py": 3,
    "server/test_skill_script_failclosed.py": 3,
    "server/test_ocr_fallback.py": 3,
    "server/test_skill_import.py": 1,
    "server/test_chat_image_fallback.py": 1,
    "server/test_extract_api.py": 1,
    # 2026-08-21, P3b: the ssh transport's two kernel facts. Same platform
    # boundary as test_command_sandbox_net.py — they drive /usr/bin/sandbox-exec
    # directly, which exists on macOS and nowhere else. One asserts the profile
    # we ship is accepted, one asserts a per-host profile is REJECTED (the
    # measurement the design rests on), one asserts the port confinement
    # actually enforces.
    "server/test_ssh_exec.py": 3,
}
#: 🔴 MIRRORED in .github/workflows/ci.yml ("Assert they RAN, and did not skip").
#: That step re-derives this number from the junit XML, so changing one without
#: the other turns a green local run into a red CI run, or worse, hides drift
#: from the guard meant to catch it. Both, same commit, or neither.
EXPECTED_TOTAL = 28

#: Text that means "this test only means something on macOS". Kept broad on
#: purpose — a new gating phrase should trip the drift check and be added here
#: deliberately, rather than quietly creating a test that runs nowhere.
# A GATE, not merely a mention of the platform. The first version matched any
# `sys.platform != "darwin"` and flagged test_packaging_entry.py:64, which is
# `assert "Application Support" in str(resolved) or sys.platform != "darwin"` —
# a platform-conditional ASSERTION in a test that runs on both platforms and
# skips on neither. Checking for the platform is not the same as gating on it.
# Two gate flavours, found the hard way: some files gate on sys.platform, others
# on a runtime CAPABILITY (`not ocr_vision.is_available()`), which never mentions
# darwin at all. Matching only the platform string classified the availability
# ones as "marked but ungated" — i.e. as the dangerous case — when they are
# correctly gated.
_SKIPIF_DARWIN = re.compile(r'skipif\([^)]*darwin', re.S)
_SKIPIF_CAPABILITY = re.compile(r'skipif\(\s*not\s+\w+\.is_available\(\)', re.S)
_INBODY_SKIP = re.compile(r'pytest\.skip\(')
_PLATFORM_REASON = re.compile(
    r'no seatbelt|macOS seatbelt|REAL sandbox|Vision is a macOS|no system recogniser'
)

# A real decorator line, not the word appearing in prose. The first version used
# `"pytest.mark.macos" in src` and matched the module DOCSTRING of the two files
# whose premise says to use @pytest.mark.macos if they ever need it — so files
# carrying no marker at all counted as marked. Third time this session that a
# grep was satisfied by prose; anchoring to the start of a line is the fix.
_MARKER_LINE = re.compile(r'(?m)^@pytest\.mark\.(macos|linux_only)\b')
_HELPER_CALL = re.compile(r'(?m)^@(_NEEDS_REAL_SANDBOX|macos_only)\b')


def _gates_on_macos(src: str) -> bool:
    return bool(_SKIPIF_DARWIN.search(src)
                or _SKIPIF_CAPABILITY.search(src)
                or (_INBODY_SKIP.search(src) and _PLATFORM_REASON.search(src)))


def _is_marked(src: str) -> bool:
    return bool(_MARKER_LINE.search(src) or _HELPER_CALL.search(src))


def _test_files() -> list[pathlib.Path]:
    """Every test module under tests/, recursively, minus this one."""
    me = pathlib.Path(__file__).resolve()
    return sorted(p for p in TESTS.glob("**/test_*.py") if p.resolve() != me)


def _rel(p: pathlib.Path) -> str:
    """Path relative to tests/, e.g. "server/test_code_sandbox.py".

    Not the bare filename: with a recursive glob two directories may hold the
    same name, and a per-file count keyed on a colliding name would silently
    merge them.
    """
    return p.relative_to(TESTS).as_posix()


def test_every_platform_gated_file_uses_the_marker():
    """A file that gates on macOS must tag at least one test for selection.

    This is the drift catcher. A new macOS-only test in a file with no marker is
    invisible to `-m macos`, which means invisible to the macOS CI job, which
    means it runs nowhere — the exact state this whole round existed to end.
    """
    offenders = []
    for p in _test_files():
        src = p.read_text()
        if _gates_on_macos(src) and not _is_marked(src):
            offenders.append(_rel(p))
    assert not offenders, (
        "these files gate on macOS but tag nothing for selection, so a macOS CI "
        f"job cannot find them: {offenders}. Add @pytest.mark.macos ALONGSIDE the "
        "existing skip — never instead of it."
    )


def test_a_marking_file_still_contains_a_platform_gate():
    """FILE-level check: anything that marks must still contain a platform gate.

    🔴 SCOPE, stated because the name used to overstate it. This is per FILE, not
    per test, and mutation showed the difference matters: rewriting the composing
    helper to `pytest.mark.macos(fn)` — dropping the skip from every test in the
    file while the module still defines an unused skipif — leaves this GREEN. So
    this catches a file that marks with no gating anywhere, and does not catch a
    gate that stopped being applied.

    The real guarantee for that case is the Linux CI job, and it is a strong one:
    a dropped skip means those tests stop skipping and start FAILING there, on the
    very next push. Duplicating it here would need pytest-inside-pytest to read
    each item's own_markers, and would still be weaker than simply running them on
    the platform where the answer is real. Recorded rather than papered over.
    """
    broken = []
    for p in _test_files():
        src = p.read_text()
        if not _MARKER_LINE.search(src) and not _HELPER_CALL.search(src):
            continue
        if not _gates_on_macos(src):
            broken.append(_rel(p))
    assert not broken, (
        f"{broken} carry the macos marker but no platform skip — on Linux these "
        "would FAIL rather than skip. The marker is additive, not a replacement."
    )


def test_the_marked_population_matches_the_measurement():
    """Per-file counts, so a marker landing in the wrong place is visible.

    Not a proof of completeness — see the module docstring. If this fails because
    the platform boundary genuinely moved, re-run the two-platform measurement
    and update these numbers with the new evidence, rather than adjusting the
    number to match whatever is there.
    """
    actual = {
        _rel(p): len(_MARKER_LINE.findall(p.read_text()))
        for p in _test_files()
        if _MARKER_LINE.search(p.read_text())
    }
    actual.pop("server/test_code_sandbox.py", None)  # linux_only line, counted below
    # test_code_sandbox / test_ocr_vision mark via a composing helper applied at
    # each call site, so count those call sites instead of the decorator text.
    for name, needle in (("server/test_code_sandbox.py", "@_NEEDS_REAL_SANDBOX"),
                         ("server/test_ocr_vision.py", "@macos_only")):
        actual[name] = (TESTS / name).read_text().count(needle)

    assert actual == EXPECTED_FILES, (
        f"the macos-marked population changed.\n  expected: {EXPECTED_FILES}\n"
        f"  actual:   {actual}"
    )
    assert sum(actual.values()) == EXPECTED_TOTAL
