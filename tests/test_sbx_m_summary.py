"""SBX-M's summary (scripts/dev/sbx_m_summary.py): counts what the run measured and quotes nothing else.

The corpus README says the report records ids, versions, hashes, outcomes, gaps and card costs only,
never raw command arguments, profile text or service output. A failure's text can hold all three, so the
summary keeps the result and drops the text, except an errno assertion in the listener-refusal loop.
"""
import json
import pathlib
import subprocess

from scripts.dev import sbx_m_summary as summary

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = "tests.server.sbx.corpus.test_sbx2_corpus"
KERNEL = "tests.server.sbx.test_sbx2_kernel"
LISTENER = "test_listener_refusal_and_arslan_port_exclusion"
SMOKE = [{"base": "default-deny", "network": "none", "probe": "fixture-smoke", "profile_override": False,
          "profile_sha256": "ab" * 32, "result": "completed", "returncode": 0, "sequence": 1}]


def case(classname, name, *, body="", **props):
    rows = "".join(f'<property name="{key}" value="{value}"/>' for key, value in props.items())
    return f'<testcase classname="{classname}" name="{name}"><properties>{rows}</properties>{body}</testcase>'


def junit(*cases):
    return f'<testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


def listener_run(failing=None, message=""):
    rows = []
    for mode in ("proxy", "any-declared", "port-22"):
        body = f'<failure message="{message}">trace</failure>' if mode == failing else ""
        rows.append(case(KERNEL, f"{LISTENER}[{mode}-default-deny]", body=body, base="default-deny"))
    return junit(*rows)


def run_folder(tmp_path):
    (tmp_path / "loop").mkdir()
    (tmp_path / "preflight.txt").write_text(
        "commit: 0123456789abcdef0123456789abcdef01234567\nmacos: 26.6.2 (25G83)\nhardware: arm64, Mac15,9\n"
        "firewall: Firewall is disabled. (State = 0)\nnote: /Users/someone/folder\n", encoding="utf-8")
    executions = json.dumps(SMOKE).replace('"', "&quot;")
    (tmp_path / "results.xml").write_text(junit(
        case(CORPUS, "test_git_init[default-deny]", base="default-deny", outcome="ok", executions=executions),
        case(CORPUS, "test_temp[/private/var/folders/xy/T/a-default-deny]", base="default-deny", outcome="timeout"),
        case(CORPUS, "test_git_clone[legacy-commands]", base="legacy-commands", outcome="tool-failed",
             body='<failure message="AssertionError: /Users/someone/secret path&#10;service output">x</failure>'),
        case(CORPUS, "test_swift_build[default-deny]", base="default-deny", outcome="tool-unavailable",
             missing_tools="/Users/someone/bin/swift"),
        case(CORPUS, "test_future_gate[default-deny]", body='<skipped type="pytest.xfail" message="SBX-3p"/>'),
        case(CORPUS, "test_optional[default-deny]", body='<skipped type="pytest.skip" message="no socket"/>'),
    ), encoding="utf-8")
    (tmp_path / "loop" / "001.xml").write_text(listener_run(), encoding="utf-8")
    (tmp_path / "loop" / "002.xml").write_text(listener_run(
        "any-declared", "AssertionError: assert 0 in (1, 13)&#10; +  where 0 = probe.errno"), encoding="utf-8")
    (tmp_path / "loop" / "003.xml").write_text(listener_run(
        "proxy", "AssertionError: assert 0 in (1, 13) /Users/someone/x"), encoding="utf-8")
    (tmp_path / "loop" / "004.xml").write_text("<testsuites><testsuite", encoding="utf-8")     # cut short
    return tmp_path


def test_the_summary_counts_results_and_outcomes(tmp_path):
    pasted = summary.main(run_folder(tmp_path))
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert pasted.splitlines() == [
        "SBX-M at 0123456789ab · macos: 26.6.2 (25G83)",
        "corpus: 6 cases, 3 passed, 1 failed, 0 error, 1 skipped, 1 xfailed; 5 rows need a look",
        "loop (4 runs, passed/ran): any-declared-default-deny 2/3 · port-22-default-deny 3/3 · "
        "proxy-default-deny 2/3",
    ]
    assert "passed 3 · failed 1 · error 0 · skipped 1 · xfailed 1" in text
    assert "| default-deny | ok | 1 |" in text and "| default-deny | timeout | 1 |" in text
    assert "| default-deny | tool-unavailable | 1 |" in text and "| legacy-commands | tool-failed | 1 |" in text
    assert "| default-deny | none | no | 1 |" in text                     # the sandboxed runs, by base
    assert "Runs with no results (pytest did not start, collect or finish): 004" in text


def test_a_row_needs_a_look_unless_it_passed_with_a_result(tmp_path):
    summary.main(run_folder(tmp_path))
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    looked = [line for line in text.splitlines() if line.startswith("| `tests/server/sbx/corpus/")]
    assert [line.split("`")[1].split("::")[1] for line in looked] == [
        "test_temp[_]", "test_git_clone[legacy-commands]", "test_swift_build[default-deny]",
        "test_future_gate[default-deny]", "test_optional[default-deny]"]           # a local path in an id is cut
    assert "| xfailed |" in looked[3] and "| skipped |" in looked[4]


def test_no_failure_text_or_local_path_reaches_the_summary(tmp_path):
    pasted = summary.main(run_folder(tmp_path))
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    for leaked in ("/Users/", "/private/", "secret path", "service output", "where 0", "trace"):
        assert leaked not in text and leaked not in pasted, leaked
    assert "missing_tools=_Users_someone_bin_swift" in text                # a property, with no slash left
    assert "- note: _Users_someone_folder" in text                         # a preflight line, the same


def test_the_loop_quotes_an_errno_assertion_and_nothing_longer(tmp_path):
    summary.main(run_folder(tmp_path))
    rows = {line.split("`")[1].rsplit("[", 1)[-1]: line
            for line in (tmp_path / "summary.md").read_text(encoding="utf-8").splitlines()
            if line.startswith(f"| `tests/server/sbx/test_sbx2_kernel.py::{LISTENER}[")}
    assert rows["any-declared-default-deny]"].endswith("| 2 | 1 | 0 | 0 | 002: AssertionError: assert 0 in (1, 13) |")
    assert rows["proxy-default-deny]"].endswith("| 2 | 1 | 0 | 0 | 003: failed |")       # a path after it
    assert rows["port-22-default-deny]"].endswith("| 3 | 0 | 0 | 0 | - |")


def test_a_part_that_was_not_run_says_so(tmp_path):
    (tmp_path / "preflight.txt").write_text("commit: 0123456789abcdef\nmacos: 26.6.2 (25G83)\n", encoding="utf-8")
    assert summary.main(tmp_path).splitlines()[1:] == ["corpus: not run", "loop: not run"]
    (tmp_path / "results.xml").write_text("<testsuites><testsuite", encoding="utf-8")         # cut short
    assert summary.main(tmp_path).splitlines()[1] == "corpus: not run"


def test_the_runner_script_parses():
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts/dev/sbx_m.sh")], capture_output=True).returncode == 0
