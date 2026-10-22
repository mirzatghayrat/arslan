import xml.etree.ElementTree as ET

from scripts.acceptance_contracts import CASES, summarize


def test_catalog_has_twenty_five_unique_stable_contracts():
    # 30 until C7b-3 (v0.1.63) removed recipes and its five contracts.
    assert len(CASES) == 25
    assert len({c[0] for c in CASES}) == 25
    assert len({c[1:] for c in CASES}) == 25


def test_missing_and_skipped_evidence_never_passes():
    root = ET.fromstring('''<testsuite>
      <testcase classname="tests.server.test_host_run" name="test_host_run_persists_trace_usage_and_output">
        <skipped message="platform unavailable"/>
      </testcase>
    </testsuite>''')
    results = summarize(root)
    assert results[0]["status"] == "skipped"
    assert results[1]["status"] == "missing"
    assert all(r["status"] != "passed" for r in results)


def test_one_failed_parameter_fails_whole_contract():
    root = ET.fromstring('''<testsuite>
      <testcase classname="tests.server.test_host_run" name="test_host_run_persists_trace_usage_and_output[a]" time="1"/>
      <testcase classname="tests.server.test_host_run" name="test_host_run_persists_trace_usage_and_output[b]" time="2">
        <failure message="not persisted"/>
      </testcase>
      <testcase classname="tests.server.test_host_run" name="test_host_run_persists_trace_usage_and_output[c]">
        <skipped/>
      </testcase>
    </testsuite>''')
    result = summarize(root)[0]
    assert result["status"] == "failed"
    assert result["parameter_cases"] == 3
    assert result["seconds"] == 3
    assert "not persisted" in result["reasons"]
