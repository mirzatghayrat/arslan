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



def _misuses_in(source: str, where: str) -> list[str]:
    """Every xfail pins `raises=` (not None) and stays strict, and nothing calls pytest.xfail().

    The step counts an xfail as ran whatever made it fail: a fixture that raises in
    setup or a NameError in the body is also `<skipped type="pytest.xfail">`. Pinning
    `raises=` turns those into `<failure>`. An explicit `strict=False` beats
    `-o xfail_strict=true`, `raises=None` means any exception, and `pytest.xfail()`
    is an xfail with no `raises=` at all. A mark used without a call (`@pytest.mark.xfail`,
    `pytestmark = ...`, `marks=...`) has no `raises=` either.
    """
    import ast

    def on_mark(base) -> bool:
        return (isinstance(base, ast.Attribute) and base.attr == "mark") or (
            isinstance(base, ast.Name) and base.id == "mark")

    tree = ast.parse(source)
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    found = []
    for node in ast.walk(tree):
        at = f"{where}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "xfail" and not on_mark(func.value):
                found.append(f"{at}: pytest.xfail() call")
                continue
            if not ((isinstance(func, ast.Attribute) and func.attr == "xfail")
                    or (isinstance(func, ast.Name) and func.id == "xfail")):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            raises = kw.get("raises")
            if raises is None or (isinstance(raises, ast.Constant) and raises.value is None):
                found.append(f"{at}: xfail without raises=")
            strict = kw.get("strict")
            if isinstance(strict, ast.Constant) and strict.value is False:
                found.append(f"{at}: xfail(strict=False)")
        elif id(node) not in called and (
                (isinstance(node, ast.Attribute) and node.attr == "xfail")
                or (isinstance(node, ast.Name) and node.id == "xfail" and isinstance(node.ctx, ast.Load))):
            found.append(f"{at}: xfail mark without a call, so without raises=")
    return found


GOOD = "import pytest\n@pytest.mark.xfail(raises=AssertionError)\ndef test_m(): assert False\n"


@pytest.mark.parametrize("source", [
    "import pytest\n@pytest.mark.xfail\ndef test_m(): pass\n",
    "import pytest\npytestmark = pytest.mark.xfail\n",
    "import pytest\n@pytest.mark.parametrize('n', [pytest.param(1, marks=pytest.mark.xfail)])\ndef test_m(n): pass\n",
    "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_m(): pass\n",
    "import pytest\n@pytest.mark.xfail(raises=None)\ndef test_m(): pass\n",
    "import pytest\n@pytest.mark.xfail(raises=AssertionError, strict=False)\ndef test_m(): pass\n",
    "import pytest\ndef test_m(): pytest.xfail('not built')\n",
    "from pytest import mark\n@mark.xfail\ndef test_m(): pass\n",
], ids=["bare mark", "pytestmark", "param marks", "no raises", "raises None", "strict False",
        "imperative", "bare imported mark"])
def test_the_guard_flags_each_misuse(source):
    assert _misuses_in(source, "probe") != []


@pytest.mark.parametrize("source", [
    GOOD,
    "from pytest import mark\n@mark.xfail(strict=True, raises=AssertionError)\ndef test_m(): assert False\n",
    "import pytest\n@pytest.mark.parametrize('n', [pytest.param(1, marks=pytest.mark.xfail(raises=OSError))])\n"
    "def test_m(n): raise OSError\n",
], ids=["pinned", "imported mark, pinned", "param marks, pinned"])
def test_the_guard_passes_a_pinned_strict_xfail(source):
    assert _misuses_in(source, "probe") == []


def test_every_xfail_pins_what_it_expects():
    root = CI.parents[2]
    found = []
    for path in sorted(root.joinpath("tests").rglob("*.py")):
        found += _misuses_in(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    assert found == []
