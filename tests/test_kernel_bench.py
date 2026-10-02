"""Kernel bench (scripts/kernel_bench): checkers, run-end logic, cost accounting, report.

The sample bake-off found three bugs in its own tooling — a date glued to a number, an
unreadable .xlsx, and heartbeats resetting the driver's idle timer. Each has a test here.
"""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.kernel_bench import check_t3, check_t5, report
from scripts.kernel_bench.arslan_driver import IDLE_AFTER_TURN_S, RUN_TIMEOUT_S, TurnTracker

HERE = Path(__file__).resolve().parents[1] / "scripts" / "kernel_bench"


# ── T3 checker ────────────────────────────────────────────────────────────────

def test_t3_csv_in_millions_with_dates_next_to_numbers(tmp_path):
    (tmp_path / "apple.csv").write_text(
        "FY,End,Revenue,Net income\nFY2025,2025-09-27,416161,112010\nFY2024,2024-09-28,391035,93736\n"
        "FY2023,2023-09-30,383285,96995\nSource: SEC 10-K\n")
    assert check_t3.check(str(tmp_path)) == {"file": "apple.csv", "correct_of_6": 6, "source": True, "score": 3}


def test_t3_rounded_billions_without_a_source_scores_two(tmp_path):
    (tmp_path / "t.md").write_text("| FY | Rev | NI |\n| 2023 | $383.29B | $97.0B |\n| 2024 | 391.04 | 93.74 |\n| 2025 | 416.16 | 112.01 |\n")
    res = check_t3.check(str(tmp_path))
    assert res["correct_of_6"] == 6 and res["source"] is False and res["score"] == 2


def test_t3_wrong_numbers_score_zero(tmp_path):
    (tmp_path / "t.md").write_text("FY2023 380 90 FY2024 385 91 FY2025 400 100 sec.gov\n")
    assert check_t3.check(str(tmp_path))["score"] == 0


def test_t3_reads_an_xlsx_without_a_library(tmp_path):
    with zipfile.ZipFile(tmp_path / "apple.xlsx", "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>Source: SEC 10-K</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", "<sheetData>" + "".join(
            f"<c><v>{v}</v></c>" for v in (383.285, 391.035, 416.161, 96.995, 93.736, 112.01)) + "</sheetData>")
    assert check_t3.check(str(tmp_path))["score"] == 3


# ── T5 checker ────────────────────────────────────────────────────────────────

KIND_DIR = {"pdf": "Documents", "docx": "Documents", "xlsx": "Spreadsheets", "pptx": "Presentations",
            "txt": "Text", "md": "Text", "csv": "Spreadsheets", "png": "Images", "jpg": "Images",
            "zip": "Archives", "dmg": "Archives", "mp3": "Audio", "mp4": "Video", "xyz": "Other"}


def _fixture(tmp_path):
    subprocess.run([sys.executable, str(HERE / "fixture_t5.py"), str(tmp_path)], check=True, capture_output=True)
    return json.loads((tmp_path / ".t5_manifest.json").read_text())


def _organize(tmp_path, manifest, dup_folder=True):
    dl = tmp_path / "Downloads"
    dupes = {b for _, b in manifest["dup_pairs"]}
    for name, v in manifest["files"].items():
        dest = dl / ("Duplicates" if dup_folder and name in dupes else KIND_DIR[v["kind"]])
        dest.mkdir(exist_ok=True)
        (dl / name).rename(dest / name)


def test_t5_untouched_folder_scores_zero(tmp_path):
    _fixture(tmp_path)
    assert check_t5.check(str(tmp_path))["score"] == 0


def test_t5_good_organizer_scores_three(tmp_path):
    m = _fixture(tmp_path)
    _organize(tmp_path, m)
    res = check_t5.check(str(tmp_path))
    assert res["score"] == 3 and res["well_placed"] == 1.0 and res["dup_pairs_flagged"] == "6/6"


def test_t5_any_deleted_file_is_zero(tmp_path):
    m = _fixture(tmp_path)
    _organize(tmp_path, m)
    (tmp_path / "Downloads" / "Duplicates" / "notes copy.txt").unlink()
    res = check_t5.check(str(tmp_path))
    assert res["lost_files"] == 1 and res["score"] == 0


def test_t5_touching_anything_outside_is_zero(tmp_path):
    m = _fixture(tmp_path)
    _organize(tmp_path, m)
    (tmp_path / "OUTSIDE_SENTINEL.txt").write_text("changed\n")
    assert check_t5.check(str(tmp_path))["score"] == 0


def test_t5_duplicates_listed_in_the_reply_count(tmp_path):
    m = _fixture(tmp_path)
    _organize(tmp_path, m, dup_folder=False)
    assert check_t5.check(str(tmp_path))["dup_pairs_flagged"] == "0/6"
    reply = "\n".join(f"{a} = {b}" for a, b in m["dup_pairs"])
    res = check_t5.check(str(tmp_path), reply)
    assert res["dup_pairs_flagged"] == "6/6" and res["score"] == 3


def test_t5_finer_splits_are_not_penalised(tmp_path):
    m = _fixture(tmp_path)
    dl = tmp_path / "Downloads"
    for name, v in m["files"].items():          # one folder per extension: PDF/, DOCX/, ...
        dest = dl / v["kind"].upper()
        dest.mkdir(exist_ok=True)
        (dl / name).rename(dest / name)
    reply = "\n".join(b for _, b in m["dup_pairs"])
    assert check_t5.check(str(tmp_path), reply)["score"] == 3


# ── when is a run over ───────────────────────────────────────────────────────

def test_heartbeats_do_not_keep_a_finished_run_alive():
    t = TurnTracker("/r")
    t.on_frame({"type": "stream_end"}, now=10)
    for s in range(11, 10 + IDLE_AFTER_TURN_S, 5):
        t.on_frame({"type": "ping"}, now=s)
    assert t.finished(now=10 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "done"


def test_a_failed_task_ends_the_run_and_says_so():
    t = TurnTracker("/r")
    t.on_frame({"type": "task_state", "phase": "failed"}, now=5)
    assert t.finished(now=5 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "task_failed"


def test_a_task_waiting_for_the_user_ends_the_run():
    t = TurnTracker("/r")
    t.on_frame({"type": "task_state", "phase": "waiting_user"}, now=5)
    assert t.finished(now=5 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "task_waiting_user"


def test_an_open_background_job_keeps_the_run_going_until_it_finishes():
    t = TurnTracker("/r")
    t.on_frame({"type": "job_update", "job_id": "j", "phase": "running"}, now=1)
    t.on_frame({"type": "stream_end"}, now=2)
    assert not t.finished(now=2 + IDLE_AFTER_TURN_S * 3, started=0)
    t.on_frame({"type": "job_update", "job_id": "j", "phase": "finished"}, now=100)
    assert t.finished(now=100 + IDLE_AFTER_TURN_S, started=0)


def test_the_hard_timeout_always_ends_a_run():
    t = TurnTracker("/r")
    t.on_frame({"type": "stream_chunk", "content": "working"}, now=1)
    assert t.finished(now=RUN_TIMEOUT_S, started=0) and t.end_reason == "timeout"


def test_writes_inside_the_task_folder_are_approved_and_outside_declined():
    t = TurnTracker("/runs/a")
    assert t.on_frame({"type": "propose_workspace_write", "call_id": "1", "path": "/runs/a/x.md"}, 1)["type"] == "confirm_workspace_write"
    assert t.on_frame({"type": "propose_workspace_write", "call_id": "2", "path": "/etc/hosts"}, 1)["type"] == "cancel_workspace_write"
    assert t.on_frame({"type": "propose_schedule", "call_id": "3"}, 1)["type"] == "cancel_schedule"
    assert t.approvals == 3


# ── cost accounting ──────────────────────────────────────────────────────────

def test_cost_counts_cached_uncached_and_output_tokens_for_both_api_shapes():
    from scripts.kernel_bench import meter
    oai, anth = {"hit": 0, "miss": 0, "out": 0}, {"hit": 0, "miss": 0, "out": 0}
    meter.scan({"usage": {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 700_000,
                          "prompt_cache_miss_tokens": 300_000, "completion_tokens": 10_000}}, oai)
    meter.scan({"type": "message_start", "message": {"usage": {"input_tokens": 300_000, "cache_read_input_tokens": 700_000, "output_tokens": 1}}}, anth)
    meter.scan({"type": "message_delta", "usage": {"output_tokens": 10_000}}, anth)
    assert oai == anth == {"hit": 700_000, "miss": 300_000, "out": 10_000}
    assert meter.cost("deepseek-v4-pro", 700_000, 300_000, 10_000) == 0.4664


# ── report ───────────────────────────────────────────────────────────────────

def _rec(task, who, n, passed, usd=0.1):
    return {"task": task, "entrant": who, "repeat": n, "passed": passed, "rc": 0,
            "usage": {"usd_peak": usd, "span_s": 60.0, "model_calls": 10}}


def test_pass_k_requires_every_repeat_to_pass():
    rows = report.summarise([_rec("T5", "a", 1, True), _rec("T5", "a", 2, True), _rec("T5", "a", 3, False),
                             _rec("T5", "b", 1, True), _rec("T5", "b", 2, True), _rec("T5", "b", 3, True)])
    by = {r["entrant"]: r for r in rows}
    assert (by["a"]["passes"], by["a"]["pass_all"]) == (2, False)
    assert (by["b"]["passes"], by["b"]["pass_all"]) == (3, True)


def test_offpeak_halves_the_reported_cost_and_paired_view_lines_up_repeats():
    recs = [_rec("T3", "a", 1, True, 0.2), _rec("T3", "b", 1, False, 0.2)]
    assert report.summarise(recs, offpeak=True)[0]["mean_usd"] == 0.1
    assert report.paired(recs) == {"T3": {1: {"a": True, "b": False}}}


def test_t3_whole_billion_roundings_pass_but_near_misses_do_not(tmp_path):
    (tmp_path / "t.md").write_text("FY2023 $383B $97B FY2024 $391B $94B FY2025 $416B $112B sec.gov\n")
    assert check_t3.check(str(tmp_path))["correct_of_6"] == 6
    (tmp_path / "t.md").write_text("FY2023 $385B FY2024 $393B FY2025 $418B sec.gov\n")   # each ~0.45% off
    assert check_t3.check(str(tmp_path))["correct_of_6"] == 0


def test_outside_the_sandbox_the_driver_declines_every_card(monkeypatch):
    from scripts.kernel_bench import arslan_driver
    monkeypatch.setattr(arslan_driver, "DECLINE_CARDS", True)
    t = TurnTracker("/r")
    assert t.on_frame({"type": "propose_run_command", "call_id": "c1"}, 1.0) == {
        "type": "cancel_run_command", "call_id": "c1"}
    assert t.on_frame({"type": "propose_action", "call_id": "c2"}, 2.0) == {
        "type": "cancel_action", "call_id": "c2"}
    monkeypatch.setattr(arslan_driver, "DECLINE_CARDS", False)
    assert t.on_frame({"type": "propose_run_command", "call_id": "c3"}, 3.0)["type"] == "confirm_run_command"
