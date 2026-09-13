"""Thirty fixed deterministic acceptance contracts, not a live-agent quality score.

uv run python -m scripts.acceptance_contracts --output /path/to/new-results
Uses synthetic test fixtures, a scrubbed environment and isolated storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Stable IDs are versioned with the exact behavior-test selector, not fuzzy -k matches.
CASES = [
    ("run-durable", "host_run", "host_run_persists_trace_usage_and_output"),
    ("run-cancel", "host_run", "host_cancel_preserves_partial_and_caller"),
    ("run-outer-cancel", "host_run", "outer_cancel_is_not_swallowed"),
    ("artifact-download", "artifact_store", "store_and_download_roundtrip"),
    ("artifact-link-refusal", "artifact_store", "workspace_links_inputs_and_limits_are_not_exported"),
    ("artifact-real-python", "artifact_store", "real_python_output_survives_temporary_workspace_cleanup"),
    ("budget-nested", "execution_budget", "nested_governed_calls_share_one_budget"),
    ("budget-parallel", "execution_budget", "parallel_admission_is_atomic"),
    ("budget-many-tools", "execution_budget", "many_tools_in_one_model_reply_cannot_bypass_shared_limit"),
    ("budget-timeout", "execution_budget", "wall_timeout_finalizes_host_and_preserves_budget"),
    ("backup-roundtrip", "backup", "backup_restore_preserves_salt_ciphertext_and_artifacts"),
    ("backup-overwrite-refusal", "backup", "refuses_overwrite_and_symlink_assets"),
    ("backup-live-wal", "backup", "snapshot_includes_committed_wal_while_writer_remains_open"),
    ("checkpoint-boot", "run_checkpoint", "boot_preserves_last_checkpoint_without_replaying_tools"),
    ("checkpoint-final", "run_checkpoint", "pending_checkpoint_cannot_overwrite_final_output"),
    ("recipe-dependencies", "recipes", "dag_executes_parallel_then_dependency_with_shared_budget"),
    ("recipe-approval-resume", "recipes", "approval_resume_reuses_completed_steps"),
    ("recipe-failure", "recipes", "failure_blocks_dependents_and_requires_explicit_retry"),
    ("recipe-parent-cancel", "recipes", "parent_run_cancel_stops_children_and_records_interruption"),
    ("recipe-immutable-idempotent", "recipes", "versions_are_immutable_and_start_requests_idempotent"),
    ("auth-remote-http", "remote_auth_boundary", "remote_http_denied_without_token_even_with_local_host"),
    ("auth-remote-websocket", "remote_auth_boundary", "remote_websocket_denied_without_token"),
    ("browser-static-only", "managed_browser", "preview_only_static_operations_renderer_sandbox_on"),
    ("browser-cancel", "managed_browser", "visit_cancel_stops_browser_and_records_cancelled"),
    ("browser-private-network", "browser_proxy", "proxy_refuses_loopback_and_non_https"),
    ("provider-gemini-wire", "gemini_native_roundtrip", "signed_parallel_function_responses_roundtrip"),
    ("context-summary-cap", "context_budget", "compaction_second_oversized_cjk_summary_is_actually_bounded"),
    ("context-fact-cap", "context_budget", "oversized_first_fact_cannot_bypass_budget"),
    ("memory-spawn-scope", "retrieve_scoped", "partition_spawn_sees_well_and_bound_only"),
    ("memory-host-scope", "retrieve_scoped", "partition_arslan_sees_all_collections_never_wells"),
]


def summarize(root: ET.Element) -> list[dict]:
    results = []
    for case_id, module, test in CASES:
        matches = [node for node in root.iter("testcase")
                   if node.get("classname", "").endswith(f"test_{module}")
                   and node.get("name", "").split("[", 1)[0] == f"test_{test}"]
        status, reasons = "passed", []
        if not matches:
            status, reasons = "missing", ["No matching test result; collection may have failed"]
        for node in matches:
            for tag in ("failure", "error", "skipped"):
                child = node.find(tag)
                if child is not None:
                    if tag != "skipped" or status == "passed":
                        status = "skipped" if tag == "skipped" else "failed"
                    reasons.append((child.get("message") or child.text or tag)[:1000])
        results.append({"id": case_id, "selector": f"tests/server/test_{module}.py::test_{test}",
                        "status": status, "parameter_cases": len(matches),
                        "seconds": sum(float(n.get("time", 0)) for n in matches), "reasons": reasons})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)  # never overwrite prior evidence
    repo = Path(__file__).resolve().parents[1]
    selectors = [f"tests/server/test_{m}.py::test_{t}" for _, m, t in CASES]
    env = {k: v for k, v in os.environ.items() if k in (
        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT")}
    begin = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="arslan-acceptance-") as temp:
        env.update(ARSLAN_DATA_DIR=temp, ARSLAN_DB_PATH=str(Path(temp) / "isolated.db"),
                   ARSLAN_SECRET_KEY="synthetic-acceptance-only", ARSLAN_SECRET_KEY_FILE="",
                   ARSLAN_API_TOKEN="", PYTHONHASHSEED="0")
        with (output / "pytest.log").open("w") as log:
            run = subprocess.run([sys.executable, "-m", "pytest", *selectors, "-q",
                                  f"--junitxml={output / 'results.xml'}"],
                                 cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    xml = output / "results.xml"
    results = summarize(ET.parse(xml).getroot() if xml.exists() else ET.Element("missing"))
    source_files = sorted({s.split("::")[0] for s in selectors})
    report = {
        "kind": "deterministic engineering acceptance; not live-agent quality evaluation",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)),
        "platform": platform.platform(), "python": platform.python_version(),
        "config": {"storage": "temporary synthetic", "provider": "test doubles", "external_model_calls": 0,
                   "external_model_cost": 0, "permission_scope": "test fixtures only"},
        "catalog_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "test_source_sha256": {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in source_files},
        "wall_seconds": time.perf_counter() - begin, "pytest_exit_code": run.returncode,
        "cases": results, "passed": sum(c["status"] == "passed" for c in results),
        "total": len(CASES),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"], "report": str(output / "report.json")}))
    raise SystemExit(0 if run.returncode == 0 and report["passed"] == len(CASES) else 1)


if __name__ == "__main__":
    main()
