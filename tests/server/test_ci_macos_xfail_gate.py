"""The macOS job's "Assert they RAN" step, run against JUnit files it can meet.

SBX's p PRs add real-seatbelt tests for surfaces that aren't built yet as strict
expected failures (docs/plans/0164/SBX-sandbox.md, "Who writes what" and its
correction). pytest 9.1.1 writes such a test to JUnit as `<skipped type="pytest.xfail">`,
a real skip as `<skipped type="pytest.skip">`, and a strict xfail that passes as
`<failure>`. The step must count the first as ran and still fail on the other two.
The script is read out of ci.yml itself, so this tests the step that runs, not a copy.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _step() -> tuple[str, int]:
    text = CI.read_text(encoding="utf-8")
    start = text.index("- name: Assert they RAN, and did not skip")
    body = text[start:text.index("\n          PY\n", start)]
    script = body[body.index("<<'PY'\n") + len("<<'PY'\n"):]
    script = "\n".join(line[10:] for line in script.splitlines())
    return script, int(re.search(r"^EXPECTED = (\d+)$", script, re.M).group(1))


def _run(tmp_path, cases: list[str]) -> subprocess.CompletedProcess:
    script, _ = _step()
    skipped = sum("<skipped" in c for c in cases)
    failures = sum("<failure" in c for c in cases)
    (tmp_path / "macos-results.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="0" failures="{failures}" skipped="{skipped}" tests="{len(cases)}">'
        + "".join(cases) + "</testsuite></testsuites>", encoding="utf-8")
    return subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)


def _passed(n: int) -> list[str]:
    return [f'<testcase classname="t" name="p{i}" />' for i in range(n)]


XFAIL = '<testcase classname="t" name="x"><skipped type="pytest.xfail" message="not built" /></testcase>'
SKIP = '<testcase classname="t" name="s"><skipped type="pytest.skip" message="no seatbelt">why</skipped></testcase>'
XPASS = '<testcase classname="t" name="x"><failure message="[XPASS(strict)] not built">x</failure></testcase>'


def test_every_case_passed_is_green(tmp_path):
    _, expected = _step()
    assert _run(tmp_path, _passed(expected)).returncode == 0


def test_a_strict_xfail_counts_as_ran(tmp_path):
    _, expected = _step()
    result = _run(tmp_path, _passed(expected - 1) + [XFAIL])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "xfailed=1" in result.stdout


@pytest.mark.parametrize("bad", [SKIP, XPASS], ids=["a real skip", "a strict xfail that passed"])
def test_a_skip_or_an_unexpected_pass_is_red(tmp_path, bad):
    _, expected = _step()
    assert _run(tmp_path, _passed(expected - 1) + [bad]).returncode != 0


def test_a_missing_case_is_red(tmp_path):
    _, expected = _step()
    assert _run(tmp_path, _passed(expected - 1)).returncode != 0


def test_the_macos_run_makes_every_xfail_strict():
    """JUnit doesn't record strictness, so the step can't tell a lenient xpass from a pass."""
    text = CI.read_text(encoding="utf-8")
    run = re.search(r"run: (\.venv/bin/pytest tests/ -m macos .*)", text).group(1)
    assert "-o xfail_strict=true" in run


def _xfail_misuses() -> list[str]:
    """Every xfail in tests/ pins `raises=` and stays strict, and nothing calls pytest.xfail().

    The step counts an xfail as ran whatever made it fail: a fixture that raises in
    setup or a NameError in the body is also `<skipped type="pytest.xfail">`. Pinning
    `raises=` turns those into `<failure>`. An explicit `strict=False` beats
    `-o xfail_strict=true`, and `pytest.xfail()` is an xfail with no `raises=` at all.
    """
    import ast

    found = []
    for path in sorted(CI.parents[2].joinpath("tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            where = f"{path.relative_to(CI.parents[2])}:{node.lineno}"
            if name != "xfail":
                continue
            is_mark = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) \
                and func.value.attr == "mark"
            if not is_mark:
                found.append(f"{where}: pytest.xfail() call")
                continue
            kw = {k.arg: k.value for k in node.keywords}
            if "raises" not in kw:
                found.append(f"{where}: xfail without raises=")
            strict = kw.get("strict")
            if isinstance(strict, ast.Constant) and strict.value is False:
                found.append(f"{where}: xfail(strict=False)")
    return found


def test_every_xfail_pins_what_it_expects():
    assert _xfail_misuses() == []
