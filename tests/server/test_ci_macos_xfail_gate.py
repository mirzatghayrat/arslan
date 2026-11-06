"""The macOS job's "Assert they RAN" step, run against JUnit files it can meet.

SBX's p PRs add real-seatbelt tests for surfaces that aren't built yet as strict
expected failures (docs/plans/0164/SBX-sandbox.md, "Who writes what" and its
correction). pytest 9.1.1 writes such a test to JUnit as `<skipped type="pytest.xfail">`,
a real skip as `<skipped type="pytest.skip">`, and a strict xfail that passes as
`<failure>`. The step must count the first as ran and still fail on the other two.
The step is scripts/check_macos_counts.py, run here as ci.yml runs it.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
CHECK = ROOT / "scripts" / "check_macos_counts.py"
A, B = "tests.server.test_a", "tests.server.sbx.test_b"
MANIFEST = """
["server/sbx/test_b.py"]
markers = 1
cases = 6
xfail = 0

["server/test_a.py"]
markers = 2
cases = 5
xfail = 2
"""


def _passed(n: int, classname: str = A) -> list[str]:
    return [f'<testcase classname="{classname}" name="p{i}" />' for i in range(n)]


def _xfail(n: int = 1, classname: str = A) -> list[str]:
    return [f'<testcase classname="{classname}" name="x{i}"><skipped type="pytest.xfail" message="not built" /></testcase>'
            for i in range(n)]


SKIP = f'<testcase classname="{A}" name="s"><skipped type="pytest.skip" message="no seatbelt">why</skipped></testcase>'
XPASS = f'<testcase classname="{A}" name="x"><failure message="[XPASS(strict)] not built">x</failure></testcase>'
ERROR = f'<testcase classname="{A}" name="e"><error message="fixture">x</error></testcase>'


def _run(tmp_path, cases: list[str], manifest: str = MANIFEST) -> subprocess.CompletedProcess:
    (tmp_path / "macos-results.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest">'
        + "".join(cases) + "</testsuite></testsuites>", encoding="utf-8")
    (tmp_path / "expected.toml").write_text(manifest, encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(CHECK), "macos-results.xml", "expected.toml"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)


def _good() -> list[str]:
    return _passed(3) + _xfail(2) + _passed(6, B)


def test_the_expected_mix_is_green(tmp_path):
    result = _run(tmp_path, _good())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ran=11 skipped=0 xfailed=2 failed=0" in result.stdout


def test_a_class_in_the_classname_still_counts_for_its_file(tmp_path):
    result = _run(tmp_path, _passed(3, f"{A}.TestThing") + _xfail(2, f"{A}.TestThing") + _passed(6, B))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("bad", [SKIP, XPASS, ERROR], ids=["a real skip", "a strict xfail that passed", "an error"])
def test_a_skip_or_an_unexpected_pass_is_red_even_when_every_count_matches(tmp_path, bad):
    """In place of a pass, so the failure can only come from the case itself. A skip isn't a case that ran, so the count
    moves for it too, and the message has to name it."""
    result = _run(tmp_path, _passed(2) + _xfail(2) + _passed(6, B) + [bad])
    assert result.returncode != 0
    assert ("SKIPPED" if bad is SKIP else "failed or errored") in result.stdout


@pytest.mark.parametrize("cases", [_passed(2) + _xfail(2) + _passed(6, B), _passed(4) + _xfail(2) + _passed(6, B)],
                         ids=["one fewer", "one more"])
def test_a_file_whose_cases_differ_from_its_pin_is_red(tmp_path, cases):
    result = _run(tmp_path, cases)
    assert result.returncode != 0
    assert "server/test_a.py:" in result.stdout and "pinned 5" in result.stdout


def test_dropping_tests_in_one_file_and_adding_as_many_in_another_is_red(tmp_path):
    """The one total this replaced let this through: the sum still matched."""
    result = _run(tmp_path, _passed(1) + _xfail(2) + _passed(8, B))
    assert result.returncode != 0
    assert "server/test_a.py:" in result.stdout and "server/sbx/test_b.py:" in result.stdout


@pytest.mark.parametrize("cases", [_passed(4) + _xfail(1) + _passed(6, B), _passed(2) + _xfail(3) + _passed(6, B)],
                         ids=["one fewer xfail", "one more xfail"])
def test_the_xfail_count_is_pinned(tmp_path, cases):
    """#620 review: an adapter registered under the wrong key keeps all of a p PR's cases xfailing, and a gate whose
    failure an xfail absorbs adds one. Either way the cases still match, so only the pinned xfails catch it."""
    result = _run(tmp_path, cases)
    assert result.returncode != 0
    assert "strict xfails, pinned 2" in result.stdout


def test_a_file_in_the_manifest_with_no_results_is_red(tmp_path):
    result = _run(tmp_path, _passed(3) + _xfail(2))
    assert result.returncode != 0
    assert "server/sbx/test_b.py: in the manifest but no case of it ran" in result.stdout


def test_results_from_a_file_with_no_table_are_red(tmp_path):
    result = _run(tmp_path, _good() + _passed(1, "tests.server.test_new"))
    assert result.returncode != 0
    assert "server/test_new.py: results but no table" in result.stdout and "cases = 1" in result.stdout


def test_results_that_name_no_test_file_are_red(tmp_path):
    result = _run(tmp_path, _good() + ['<testcase classname="" name="tests.server.test_broken" />'])
    assert result.returncode != 0
    assert "(no test file)" in result.stdout and "results but no table" in result.stdout


def test_a_strict_xfail_that_also_really_skipped_is_red(tmp_path):
    """Its fixture calls pytest.skip in teardown, so the case has two <skipped>; reading only the first would count it as
    an xfail that ran."""
    both = (f'<testcase classname="{A}" name="b"><skipped type="pytest.xfail" message="not built" />'
            '<skipped type="pytest.skip" message="teardown">why</skipped></testcase>')
    result = _run(tmp_path, _passed(3) + _xfail(1) + [both] + _passed(6, B))
    assert result.returncode != 0
    assert "1 SKIPPED" in result.stdout


def test_a_failure_says_how_to_read_it(tmp_path):
    result = _run(tmp_path, _passed(2) + _xfail(2) + _passed(6, B))
    assert "two PRs combined: the second PR's author recounts that file in a pin-only PR" in result.stdout


def test_the_macos_run_makes_every_xfail_strict():
    """JUnit doesn't record strictness, so the step can't tell a lenient xpass from a pass."""
    text = CI.read_text(encoding="utf-8")
    run = re.search(r"run: (\.venv/bin/pytest tests/ -m macos .*)", text).group(1)
    assert "-o xfail_strict=true" in run
    assert "x" in re.search(r" -r(\w+)", run).group(1), "the log lists each xfail (-rx)"


def _misuses_in(source: str, where: str) -> list[str]:
    """Every xfail pins `raises=` (not None) and stays strict, and nothing calls pytest.xfail().

    The step counts any matched xfail as ran. `raises=` rejects only exceptions
    outside its type or matcher; a broad AssertionError also absorbs real gate
    failures. Use a dedicated type or message match. An explicit `strict=False` beats
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
