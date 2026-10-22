"""Kernel bench (scripts/kernel_bench): checkers, run-end logic, cost accounting, report.

The sample bake-off found three bugs in its own tooling — a date glued to a number, an
unreadable .xlsx, and heartbeats resetting the driver's idle timer. Each has a test here.
"""
import json
import os
import subprocess
import sys
import time
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


def test_each_turn_records_when_its_first_answer_text_and_its_end_arrived():
    """K8's M1 is first-token latency per task: seconds from sending a turn to its first
    stream_chunk, and to its stream_end. A turn that never streamed says so (None)."""
    t = TurnTracker("/r")
    t.start_turn(now=100)
    t.on_frame({"type": "note", "content": "looking"}, now=101)          # narration is not the answer
    t.on_frame({"type": "stream_chunk", "content": ""}, now=102)         # nor is an empty chunk (②Main's 🟡)
    t.on_frame({"type": "stream_chunk", "content": "Hel"}, now=103.5)
    t.on_frame({"type": "stream_chunk", "content": "lo"}, now=104)
    t.on_frame({"type": "stream_end"}, now=108)
    t.on_frame({"type": "stream_end"}, now=120)                          # a later end does not move it
    assert t.next_turn(now=121) == "Hello"
    t.start_turn(now=200)
    t.on_frame({"type": "stream_end"}, now=203)
    t.next_turn(now=204)
    assert t.timings == [{"first_chunk_s": 3.5, "stream_end_s": 8.0}, {"first_chunk_s": None, "stream_end_s": 3.0}]


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


def test_a_write_card_with_choices_is_answered_for_the_conversation():
    """0.1.61 PR 2b: a scope-less yes is once only, so the bench says "in this conversation" when
    the card offers it — one write card per run, as the bench measured before."""
    t = TurnTracker("/runs/a")
    reply = t.on_frame({"type": "propose_workspace_write", "call_id": "1", "path": "/runs/a/x.md",
                        "options": ["once", "conversation"]}, 1)
    assert reply == {"type": "confirm_workspace_write", "call_id": "1", "scope": "conversation"}
    old = t.on_frame({"type": "propose_workspace_write", "call_id": "2", "path": "/runs/a/y.md"}, 1)
    assert old == {"type": "confirm_workspace_write", "call_id": "2"}


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


def test_action_cards_are_approved_only_where_that_app_is_the_task(monkeypatch):
    """③Hands, 2026-10-19: approving every propose_action let an AppleScript or Hands reach the
    user's real apps. Only T1's Reminders script and T12's synthetic fixture app are approved."""
    from scripts.kernel_bench import arslan_driver
    monkeypatch.setattr(arslan_driver, "DECLINE_CARDS", False)

    def ans(run_dir, kind, target, detail=""):
        t = TurnTracker(run_dir)
        return t.on_frame({"type": "propose_action", "call_id": "c", "kind": kind, "target": target,
                           "detail": detail}, 1.0)["type"]
    reminders = 'tell application "Reminders"\n  make new list with properties {name:"x"}\nend tell'
    assert ans("/b/runs/arslan-T1-r1", "mac_script", "Reminders", reminders) == "confirm_action"
    assert ans("/b/runs/arslan-T1-r1", "mac_script", "Reminders",
               reminders + '\ndo shell script "ls ~"') == "cancel_action"          # a step past Reminders
    assert ans("/b/runs/arslan-T1-r1", "mac_script", "Reminders",
               reminders + '\ntell application "Finder" to get name of home') == "cancel_action"
    assert ans("/b/runs/arslan-T1-r1", "mac_shortcut", "Reminders", "Add to Reminders") == "cancel_action"
    assert ans("/b/runs/arslan-T5-r1", "mac_script", "Reminders", reminders) == "cancel_action"
    assert ans("/b/runs/arslan-T12-r1", "desktop_app", "Hands Fixture") == "confirm_action"
    assert ans("/b/runs/arslan-T12-r1", "desktop_risky", "Hands Fixture · “Delete”") == "cancel_action"
    assert ans("/b/runs/arslan-T12-r1", "desktop_app", "Notes") == "cancel_action"
    assert ans("/b/runs/arslan-T12-r1", "mac_script", "Hands Fixture") == "cancel_action"
    assert ans("/b/runs/arslan-T2-r1", "browser_site", "example.com") == "cancel_action"
    assert ans("/b/runs/arslan-T2-r1", "desktop_takeover", "screen") == "cancel_action"
    t = TurnTracker("/b/runs/arslan-T11-r1")
    t.on_frame({"type": "propose_action", "call_id": "c", "kind": "mac_shortcut", "target": "x"}, 1.0)
    assert (t.approvals, t.actions_declined, t.declined) == (1, 1, 0)     # T11 scores `declined` only


def test_sandboxed_rounds_answer_cards_like_a_user_and_never_let_commands_out(monkeypatch):
    """0.1.51 P3: inside Arslan's sandbox, deleting/installing are approved; leaving the
    sandbox, outward actions and other apps are declined — Reminders only for T1."""
    from scripts.kernel_bench import arslan_driver
    monkeypatch.setattr(arslan_driver, "DECLINE_CARDS", False)
    monkeypatch.setattr(arslan_driver, "CARDS", "sandboxed")
    t = TurnTracker("/b/runs/arslan-T5-r1")

    def ans(frame):
        return t.on_frame({"type": "propose_run_command", "call_id": "c", **frame}, 1.0)["type"]
    assert ans({"rule": "delete"}) == "confirm_run_command"
    assert ans({}) == "confirm_run_command"
    assert ans({"rule": "delete", "sandbox": "retry"}) == "cancel_run_command"
    assert ans({"sandbox": "outside"}) == "cancel_run_command"
    assert ans({"rule": "send-mail"}) == "cancel_run_command"
    assert ans({"rule": "apple-events"}) == "cancel_run_command"
    assert (t.sandbox_cards, t.declined, t.approvals) == (2, 4, 6)
    # Every other kind inside the sandbox is approved, new ones included (K2a's T5 got a heredoc-script card);
    # every outward kind is declined.
    assert ans({"rule": "unreadable"}) == "confirm_run_command"          # S2a-2: inside the sandbox it holds them
    assert ans({"rule": "delete-outside"}) == "confirm_run_command"
    assert ans({"rule": "some-rule-added-later"}) == "confirm_run_command"
    for rule in ("upload", "shortcuts", "send-message", "remote-shell", "git-push", "publish"):
        assert ans({"rule": rule}) == "cancel_run_command", rule
    from server.services import terminal_policy
    assert arslan_driver.OUTWARD == terminal_policy.OUTBOUND_RULES    # the bench weighs what the product calls outward
    # Inside the seatbelt yet carried out by a system daemon (launchd, cron, cfprefsd): declined (③Hands, #242).
    for rule in ("login-items", "sudo", "keychain-secrets", "arslan-keys", "macos-roots",
                 "keychain-write", "system-settings", "open-app", "force-kill", "screen-clipboard"):
        assert ans({"rule": rule}) == "cancel_run_command", rule
    known = {r[0] for r in terminal_policy._FORBID + terminal_policy._ASK}
    assert arslan_driver.ESCAPES_SANDBOX <= known                   # a renamed rule must not silently slip through
    t1 = TurnTracker("/b/runs/arslan-T1-r2")
    assert t1.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "apple-events"}, 1.0)["type"] == \
        "confirm_run_command"


def test_without_the_outer_sandbox_no_card_may_let_a_command_out(monkeypatch, tmp_path):
    """Option A (BENCH_SANDBOX=none): Arslan's sandbox is all that stands between a command and the real
    disk, so the driver answers cards the sandboxed way whatever BENCH_CARDS says (③Hands, #234)."""
    import importlib
    from scripts.kernel_bench import arslan_driver, runner
    try:
        for cards in ("", "anything"):
            monkeypatch.setenv("BENCH_SANDBOX", "none")
            monkeypatch.setenv("BENCH_CARDS", cards)
            monkeypatch.delenv("BENCH_DECLINE_CARDS", raising=False)
            driver = importlib.reload(arslan_driver)
            assert driver.CARDS == "sandboxed"
            t = driver.TurnTracker("/b/runs/arslan-T2-r1-base")
            for frame in ({"sandbox": "outside"}, {"sandbox": "retry"}, {"rule": "delete", "sandbox": "retry"}):
                answer = t.on_frame({"type": "propose_run_command", "call_id": "c", **frame}, 1.0)["type"]
                assert answer == "cancel_run_command", frame
            t1 = driver.TurnTracker("/b/runs/arslan-T1-r2-base")
            assert t1.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "apple-events",
                                "sandbox": "outside"}, 1.0)["type"] == "cancel_run_command"
        monkeypatch.delenv("BENCH_SANDBOX")
        monkeypatch.setenv("BENCH_CARDS", "")
        assert importlib.reload(arslan_driver).CARDS == ""                     # with the outer sandbox: as before
        monkeypatch.setenv("BENCH_SANDBOX", "none")
        _, env = runner.command("arslan", "arslan-T2-r1", tmp_path, "go", "sb")
        assert env.get("BENCH_SANDBOX") == "none"                              # the driver sees it
    finally:
        monkeypatch.undo()
        importlib.reload(arslan_driver)


# ── M1a (0.1.62 round): waiting counts as failure, turns, a decline with a note, two models ──

def test_an_arslan_run_passes_only_when_it_ended_cleanly_and_the_checker_gives_three():
    from scripts.kernel_bench import runner
    assert runner.judge({"score": 3}, end="done") is True
    assert runner.judge({"score": 2}, end="done") is False
    for end in ("task_waiting_user", "task_failed", "task_cancelled", "timeout", "job_blocked",
                "job_out_of_budget", None):                       # None: the driver never reported
        assert runner.judge({"score": 3}, end=end, who="arslan") is False, end
    assert runner.judge({"score": 3}, end=None, who="hermes") is True        # outside entrants report no end


def test_succeeded_is_the_phase_that_ends_a_run_cleanly_and_completed_is_not_a_phase():
    t = TurnTracker("/r")
    t.on_frame({"type": "task_state", "phase": "completed"}, now=1)
    assert not t.turn_done
    t.on_frame({"type": "task_state", "phase": "succeeded"}, now=5)
    assert t.finished(now=5 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "done"


def test_a_task_turn_is_over_only_at_its_final_state_even_after_the_answer_ended():
    t = TurnTracker("/r")
    t.on_frame({"type": "task_state", "phase": "running"}, now=1)
    t.on_frame({"type": "stream_end"}, now=2)
    assert not t.finished(now=2 + IDLE_AFTER_TURN_S * 3, started=0)      # the review runs after the answer
    t.on_frame({"type": "task_state", "phase": "waiting_user"}, now=100)
    assert t.finished(now=100 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "task_waiting_user"


def test_a_background_job_that_ends_blocked_or_out_of_budget_is_how_the_run_ended():
    for outcome in ("blocked", "out_of_budget", "partial", "stopped"):
        t = TurnTracker("/r")
        t.on_frame({"type": "job_update", "job_id": "j", "phase": "running"}, now=1)
        t.on_frame({"type": "stream_end"}, now=2)
        t.on_frame({"type": "job_update", "job_id": "j", "phase": "finished", "outcome": outcome}, now=50)
        assert t.finished(now=50 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == f"job_{outcome}"
    ok = TurnTracker("/r")
    ok.on_frame({"type": "job_update", "job_id": "j", "phase": "finished", "outcome": "done"}, now=1)
    ok.on_frame({"type": "stream_end"}, now=2)
    assert ok.finished(now=2 + IDLE_AFTER_TURN_S, started=0) and ok.end_reason == "done"


def test_a_turn_that_ended_waiting_still_counts_after_a_later_turn_succeeds():
    t = TurnTracker("/r")
    t.on_frame({"type": "task_state", "phase": "waiting_user"}, now=1)
    t.next_turn(now=2)
    t.on_frame({"type": "task_state", "phase": "succeeded"}, now=3)
    assert t.finished(now=3 + IDLE_AFTER_TURN_S, started=0) and t.end_reason == "task_waiting_user"


def test_by_default_the_stand_in_declines_apple_events_except_for_reminders_in_t1():
    t = TurnTracker("/b/runs/arslan-T5-r1")
    assert t.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "apple-events"}, 1)["type"] == \
        "cancel_run_command"
    assert t.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "delete"}, 1)["type"] == \
        "confirm_run_command"
    t1 = TurnTracker("/b/runs/arslan-T1-r1")
    assert t1.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "apple-events"}, 1)["type"] == \
        "confirm_run_command"


def test_run_one_judges_with_the_end_the_driver_printed(tmp_path, monkeypatch):
    """The end has to travel from Arslan's driver output into the judge (a stub driver here)."""
    import sys
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setitem(runner.CHECKS, "T9", lambda run, reply, ctx: {"score": 3})
    waits = []
    monkeypatch.setattr(runner, "settle", lambda label, since, ended=0.0, **k: waits.append((since, ended)) or 0.0)
    for end, passed in (("task_waiting_user", False), ("done", True)):
        script = f"import json; print(json.dumps({{'end': '{end}', 'final': 'ok'}}))"
        monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
        rec = runner.run_one("T9", "arslan", 1, {"T9": "edit {dir}"}, "sb")
        assert (rec["end"], rec["passed"], rec["judge"]) == (end, passed, runner.JUDGE_VERSION)
    assert len(waits) == 2 and all(ended > since > 0 for since, ended in waits)   # quiet counts from the exit


def test_the_record_keeps_the_timing_the_driver_printed(tmp_path, monkeypatch):
    import sys
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setitem(runner.CHECKS, "T9", lambda run, reply, ctx: {"score": 3})
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    script = ("import json; print(json.dumps({'end': 'done', 'final': 'ok', "
              "'timing': [{'first_chunk_s': 2.5, 'stream_end_s': 9.0}]}))")
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    rec = runner.run_one("T9", "arslan", 1, {"T9": "edit {dir}"}, "sb")
    assert rec["timing"] == [{"first_chunk_s": 2.5, "stream_end_s": 9.0}]
    saved = json.loads(Path(tmp_path / "runs" / f"{rec['run']}.record.json").read_text())
    assert saved["timing"] == rec["timing"]


def test_the_round_is_in_the_run_label_so_a_later_round_starts_fresh(tmp_path, monkeypatch):
    """The meter caps a label over its whole life: a reused label was refused with 402 (K1 after-runs).
    The round names the label, its folder and the meter's key; T1's list carries the model once."""
    import sys
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    seen = {}
    monkeypatch.setitem(runner.CHECKS, "T1", lambda run, reply, ctx: seen.update(run=run, list=ctx["list"]) or {"score": 3})
    labels = []
    script = "import json; print(json.dumps({'end': 'done', 'final': 'ok'}))"
    monkeypatch.setattr(runner, "command", lambda who, label, *a, **k: labels.append(label) or ([sys.executable, "-c", script], {}))
    for round_, label in (("", "arslan-T1-r1"), ("k1after", "arslan-T1-r1-k1after")):
        monkeypatch.setattr(runner, "ROUND", round_)
        rec = runner.run_one("T1", "arslan", 1, {"T1": "make {list}"}, "sb", models={"arslan": "claude-sonnet-5"})
        assert (rec["run"], labels[-1], Path(seen["run"]).name) == (label, label, label)
        assert seen["list"] == f"对比测试-{label}-claude-sonnet-5"
    assert (tmp_path / "runs" / "arslan-T1-r1").is_dir() and (tmp_path / "runs" / "arslan-T1-r1-k1after").is_dir()


def test_a_runs_usage_is_its_own_label_from_when_it_started(tmp_path, monkeypatch):
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    row = {"cand": "arslan-T9-r1", "model": "deepseek-v4-pro", "secs": 1.0, "out": 1, "hit": 0, "miss": 1}
    (tmp_path / "usage.jsonl").write_text("\n".join(json.dumps(row | {"t": t, "usd_peak": u})
                                                    for t, u in ((100.0, 0.5), (200.0, 0.01), (201.0, 0.02))) + "\n")
    assert runner.usage("arslan-T9-r1", since=150.0)["usd_peak"] == 0.03          # an earlier round's 0.5 left out
    assert runner.usage("arslan-T9-r1")["model_calls"] == 3


def test_usage_is_read_only_once_the_runs_label_has_gone_quiet(tmp_path, monkeypatch):
    import time
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    now = time.time()
    row = {"model": "deepseek-v4-pro", "secs": 1.0, "out": 1, "hit": 0, "miss": 1, "usd_peak": 0.01}
    log = tmp_path / "usage.jsonl"
    log.write_text(json.dumps(row | {"cand": "arslan-T9-r1", "t": now - 60}) + "\n"
                   + json.dumps(row | {"cand": "hermes-T9-r1", "t": now}) + "\n")
    assert runner.settle("arslan-T9-r1", since=now - 120, quiet_s=5) == 0      # another label's call ignored
    # A call still running when the driver exits has no row yet: quiet counts from the exit too.
    assert runner.settle("arslan-T9-r1", since=now - 120, ended=time.time(), quiet_s=1.5, max_s=10) >= 1
    log.write_text(log.read_text() + json.dumps(row | {"cand": "arslan-T9-r1", "t": time.time()}) + "\n")
    assert runner.settle("arslan-T9-r1", since=now - 120, quiet_s=1.5, max_s=10) >= 1   # after-turn call waited for
    assert runner.settle("arslan-T9-r1", since=now - 120, quiet_s=60, max_s=2) == 2     # never past max_s


def test_a_line_the_meter_is_still_writing_is_skipped(tmp_path, monkeypatch):
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    row = {"cand": "arslan-T9-r1", "model": "deepseek-v4-pro", "secs": 1.0, "out": 1, "hit": 0, "miss": 1,
           "t": 100.0, "usd_peak": 0.5}
    (tmp_path / "usage.jsonl").write_text(json.dumps(row) + "\n" + '{"cand": "arslan-T9-r1", "mod')
    assert runner.usage("arslan-T9-r1")["model_calls"] == 1
    assert runner.settle("arslan-T9-r1", since=0.0, quiet_s=1) == 0


def test_the_report_keeps_rows_judged_by_the_old_rule_apart():
    old = _rec("T5", "arslan", 1, True) | {"model": "m"}
    new = _rec("T5", "arslan", 1, False) | {"model": "m", "judge": 2}
    rows = report.summarise([old, new])
    assert sorted((r["passes"], r["old_rule"]) for r in rows) == [(0, False), (1, True)]
    assert "arslan (old rule)" in report.render(rows)


def test_a_decline_pattern_catches_every_name_the_same_deletion_comes_under():
    t = TurnTracker("/r", decline_rules=frozenset({r"delete|\brm\b|unlink"}), decline_note="n")
    for rule in ("delete", "hermes:find -delete", "hermes:xargs rm"):
        assert t.on_frame({"type": "propose_run_command", "call_id": "c", "rule": rule}, 1.0)["type"] == \
            "cancel_run_command", rule
    assert t.on_frame({"type": "propose_run_command", "call_id": "c", "rule": "upload"}, 1.0)["type"] == \
        "confirm_run_command"


def test_the_driver_is_imported_from_the_runners_own_checkout(tmp_path):
    from scripts.kernel_bench import runner
    _, env = runner.command("arslan", "arslan-T9-r1", tmp_path / "r", "go", "sb")
    assert env["PYTHONPATH"] == str(runner.HERE.parents[1])


def test_a_declined_card_can_carry_the_users_note():
    t = TurnTracker("/r", decline_rules=frozenset({"delete"}), decline_note="改成移到 trash 文件夹")
    assert t.on_frame({"type": "propose_run_command", "call_id": "c1", "rule": "delete"}, 1.0) == {
        "type": "cancel_run_command", "call_id": "c1", "note": "改成移到 trash 文件夹"}
    assert t.on_frame({"type": "propose_run_command", "call_id": "c2", "rule": ""}, 1.0)["type"] == \
        "confirm_run_command"
    assert (t.approvals, t.declined) == (2, 1)


def test_prompts_are_one_text_or_a_json_list_of_turns(tmp_path):
    from scripts.kernel_bench import arslan_driver
    (tmp_path / "one.prompt").write_text("  do it \n")
    (tmp_path / "many.prompt").write_text(json.dumps(["write", "shorten", "add a table"]))
    assert arslan_driver.load_prompts(str(tmp_path / "one.prompt")) == ["do it"]
    assert arslan_driver.load_prompts(str(tmp_path / "many.prompt")) == ["write", "shorten", "add a table"]


class _FakeArslan:
    """A stand-in for the Arslan socket: every user message starts a turn that rewrites
    report.md, streams one chunk and ends. Records how many frames had been delivered
    when each message was sent."""

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.queue = [{"type": "history", "messages": []}]
        self.sent, self.delivered = [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append((msg, len(self.delivered)))
        if msg["type"] == "user_message":
            n = sum(1 for m, _ in self.sent if m["type"] == "user_message")
            (self.run_dir / "report.md").write_text(f"turn {n}\n")
            self.queue += [{"type": "stream_chunk", "content": f"answer {n}"}, {"type": "stream_end"}]

    async def recv(self):
        import asyncio
        if not self.queue:
            await asyncio.sleep(10)
        frame = self.queue.pop(0)
        self.delivered.append(frame)
        return json.dumps(frame)


def test_the_next_turn_is_sent_only_after_the_last_one_ended_and_the_folder_is_kept_between(tmp_path):
    import asyncio
    from scripts.kernel_bench import arslan_driver
    run_dir = tmp_path / "arslan-T8-r1"
    run_dir.mkdir()
    fake = _FakeArslan(run_dir)
    out = asyncio.run(arslan_driver.run("http://x/api/v1", str(run_dir), ["write", "shorten"],
                                        str(tmp_path / "frames.jsonl"), connect=lambda *a, **k: fake,
                                        idle_after_s=0, recv_timeout=0.01))
    users = [(m["content"], seen) for m, seen in fake.sent if m["type"] == "user_message"]
    assert [c for c, _ in users] == ["write", "shorten"]
    first_end = next(i for i, f in enumerate(fake.delivered) if f["type"] == "stream_end")
    assert users[1][1] > first_end                    # turn 1's end was read before turn 2 went out
    assert out["replies"] == ["answer 1", "answer 2"] and out["final"] == "answer 2"
    # each turn's clock starts when that turn is sent (K8's M1 reads these from the record)
    assert len(out["timing"]) == 2 and all(0 <= t["first_chunk_s"] <= t["stream_end_s"] < 5 for t in out["timing"])
    assert (tmp_path / "arslan-T8-r1.turn1" / "report.md").read_text() == "turn 1\n"
    assert (run_dir / "report.md").read_text() == "turn 2\n"


def test_the_test_instance_is_pointed_at_claude_through_the_anthropic_provider():
    from scripts.kernel_bench import arslan_driver
    body = arslan_driver.provider_body("anthropic", "claude-sonnet-5-5", "http://127.0.0.1:8901/c/l/v1")
    assert body == {"label": "bench", "provider": "anthropic", "model": "claude-sonnet-5-5",
                    "base_url": "http://127.0.0.1:8901/c/l/v1", "api_key": "bench-dummy"}
    assert arslan_driver.provider_body("openai", "deepseek-v4-pro", "http://p/c/l")["provider"] == "openai"


def test_each_entrant_gets_its_own_model_and_claude_models_go_through_the_anthropic_proxy():
    from scripts.kernel_bench import runner
    models = runner.parse_models("arslan=claude-sonnet-5-5,claude-code=claude-sonnet-5-5")
    assert runner.model_for("arslan", models) == "claude-sonnet-5-5"
    assert runner.model_for("hermes", models) == runner.MODEL
    assert runner.proxy_for("claude-sonnet-5-5") == runner.ANTHROPIC_PROXY
    assert runner.proxy_for("deepseek-v4-pro") == runner.PROXY


def test_arslan_on_claude_uses_the_anthropic_provider_and_the_second_proxy(tmp_path):
    from scripts.kernel_bench import runner
    run = tmp_path / "arslan-T7-r1"
    cmd, _ = runner.command("arslan", "arslan-T7-r1", run, ["go"], "sb", model="claude-sonnet-5-5")
    assert cmd[cmd.index("--provider") + 1] == "anthropic"
    assert f"{runner.ANTHROPIC_PROXY}/arslan-T7-r1/v1" in cmd
    assert json.loads(Path(f"{run}.prompt").read_text()) == ["go"]


def test_claude_code_runs_bare_in_the_sandbox_with_a_dummy_key_and_resumes_its_session(tmp_path):
    from scripts.kernel_bench import runner
    run = tmp_path / "claude-code-T8-r1"
    first, env = runner.command("claude-code", "claude-code-T8-r1", run, "write", "sb",
                                model="claude-sonnet-5-5", turn=0, session="s-1")
    later, _ = runner.command("claude-code", "claude-code-T8-r1", run, "shorten", "sb",
                              model="claude-sonnet-5-5", turn=1, session="s-1")
    assert first[:3] == ["sandbox-exec", "-f", "sb"]
    for flag in ("--bare", "-p", "--strict-mcp-config", "--dangerously-skip-permissions"):
        assert flag in first
    assert first[first.index("--model") + 1] == "claude-sonnet-5-5"
    assert first[first.index("--session-id") + 1] == "s-1" and "--resume" not in first
    assert later[later.index("--resume") + 1] == "s-1" and "--session-id" not in later
    assert env["ANTHROPIC_BASE_URL"] == f"{runner.ANTHROPIC_PROXY}/claude-code-T8-r1"
    _, on_deepseek = runner.command("claude-code", "claude-code-T7-r1", run, "go", "sb", model="deepseek-v4-pro")
    assert on_deepseek["ANTHROPIC_BASE_URL"] == f"{runner.PROXY}/claude-code-T7-r1/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "bench-dummy"
    assert env["HOME"].startswith(str(runner.ROOT))


def test_claude_codes_temporary_folder_is_inside_what_the_sandbox_lets_it_write(tmp_path, monkeypatch):
    """Its Bash tool makes a folder under /tmp/claude-<uid> by default, which the bench sandbox
    refuses: every command failed and four M1B cells were invalid. CLAUDE_CODE_TMPDIR moves it
    under the bench root, the one place the profile lets it write."""
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    _, env = runner.command("claude-code", "claude-code-T3-r1", tmp_path / "run", "go", "sb", model="claude-sonnet-5")
    folder = Path(env["CLAUDE_CODE_TMPDIR"])
    assert folder.is_dir() and tmp_path in folder.parents
    assert '(subpath "{ROOT}")' in (runner.HERE / "sandbox.sb.template").read_text()


def test_claude_codes_reply_is_the_result_of_its_last_turn(tmp_path):
    from scripts.kernel_bench import runner
    run = tmp_path / "claude-code-T8-r1"
    Path(f"{run}.stdout").write_text(json.dumps({"type": "result", "result": "first"}) + "\n"
                                     + json.dumps({"type": "result", "result": "second"}) + "\n")
    assert runner.reply_text("claude-code", run) == "second"


def test_the_report_keeps_two_models_apart():
    a = _rec("T5", "arslan", 1, True) | {"model": "deepseek-v4-pro"}
    b = _rec("T5", "arslan", 1, False) | {"model": "claude-sonnet-5-5"}
    rows = report.summarise([a, b])
    assert [(r["model"], r["passes"]) for r in rows] == [("claude-sonnet-5-5", 0), ("deepseek-v4-pro", 1)]
    assert "| claude-sonnet-5-5 |" in report.render(rows)


def test_claude_prices_and_cache_writes_cost_more_than_plain_input():
    from scripts.kernel_bench import meter
    acc = {"hit": 0, "miss": 0, "out": 0}
    meter.scan({"type": "message_start", "message": {"usage": {
        "input_tokens": 100_000, "cache_creation_input_tokens": 400_000,
        "cache_read_input_tokens": 500_000, "output_tokens": 0}}}, acc)
    assert acc == {"hit": 500_000, "miss": 500_000, "out": 0, "write": 400_000}
    plain = meter.cost("claude-sonnet-5-5", 500_000, 500_000, 0)
    assert meter.cost("claude-sonnet-5-5", 500_000, 500_000, 0, write=400_000) > plain
    assert meter.PRICE["claude-sonnet-5-5"] == (0.20, 2.00, 10.00)


def test_the_anthropic_upstream_gets_only_its_key_header_and_no_openai_stream_option():
    from scripts.kernel_bench import meter
    h = meter.auth_headers({"anthropic-version": "2023-06-01"}, "k", anthropic=True)
    assert h == {"anthropic-version": "2023-06-01", "x-api-key": "k", "accept-encoding": "identity"}
    assert meter.auth_headers({}, "k", anthropic=False) == {"authorization": "Bearer k", "x-api-key": "k",
                                                             "accept-encoding": "identity"}
    assert meter.cost("claude-unlisted-9", 0, 1_000_000, 0) == meter.PRICE["claude-fable-5-1"][1]
    assert meter.wants_usage_option(True, {"messages": []}, "/v1/messages", anthropic=True) is False
    assert meter.wants_usage_option(True, {"messages": []}, "/v1/chat/completions", anthropic=False) is True


def test_a_fresh_instance_answers_during_the_run_and_is_gone_after(tmp_path, monkeypatch):
    """U10: each run gets an Arslan on an empty data folder; nothing it learns reaches the next run."""
    import socket
    from scripts.kernel_bench import runner
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    site = tmp_path / "site"
    (site / "api/v1").mkdir(parents=True)
    (site / "api/v1/health").write_text("ok")
    script = tmp_path / "start.sh"                 # stands in for start_arslan.sh <name> <port>
    script.write_text(f'#!/bin/bash\necho "$1" > {tmp_path}/name\n'
                      f'exec {sys.executable} -m http.server "$2" --bind 127.0.0.1 --directory {site}\n')
    script.chmod(0o755)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "START_ARSLAN", script)
    monkeypatch.setattr(runner, "ARSLAN_API", f"http://127.0.0.1:{port}/api/v1")
    left = tmp_path / "data" / "fresh-arslan-T9-r1"
    left.mkdir(parents=True)
    (left / "arslan.db").write_text("an earlier attempt")
    with runner.fresh_instance("arslan-T9-r1", "arslan") as data:
        assert runner._healthy(runner.ARSLAN_API)
        assert data == left and not (left / "arslan.db").exists()       # wiped before the start
        leaving = time.monotonic()
    assert time.monotonic() - leaving < 10                                # SIGTERM, not the 30 s fallback
    assert (tmp_path / "name").read_text().strip() == "fresh-arslan-T9-r1"
    assert not runner._healthy(runner.ARSLAN_API)                         # stopped with its group


def test_a_fresh_instance_refuses_a_port_that_already_answers(tmp_path, monkeypatch):
    """A leftover instance on the port would silently be the one under test."""
    import pytest
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_healthy", lambda api: True)
    started = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(SystemExit):
        with runner.fresh_instance("arslan-T9-r1", "arslan"):
            pass
    assert started == []


def test_with_fresh_instances_each_arslan_run_has_its_own_until_it_settles(tmp_path, monkeypatch):
    import contextlib
    from scripts.kernel_bench import runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    events = []

    @contextlib.contextmanager
    def fake(label, who):
        events.append(("up", label))
        yield tmp_path / "data" / f"fresh-{label}"
        events.append(("down", label))
    monkeypatch.setattr(runner, "fresh_instance", fake)
    monkeypatch.setattr(runner, "settle", lambda label, *a, **k: events.append(("settle", label)) or 0.0)
    seen = []
    monkeypatch.setitem(runner.CHECKS, "T9", lambda run, reply, ctx: seen.append(ctx.get("arslan_data")) or {"score": 3})
    script = "import json; print(json.dumps({'end': 'done', 'final': 'ok'}))"
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    monkeypatch.setattr(runner, "FRESH", True)
    for n in (1, 2):
        runner.run_one("T9", "arslan", n, {"T9": "edit {dir}"}, "sb")
    assert events == [("up", "arslan-T9-r1"), ("settle", "arslan-T9-r1"), ("down", "arslan-T9-r1"),
                      ("up", "arslan-T9-r2"), ("settle", "arslan-T9-r2"), ("down", "arslan-T9-r2")]
    assert seen == [str(tmp_path / "data" / "fresh-arslan-T9-r1"), str(tmp_path / "data" / "fresh-arslan-T9-r2")]
    monkeypatch.setattr(runner, "FRESH", False)
    runner.run_one("T9", "arslan", 3, {"T9": "edit {dir}"}, "sb")
    assert events[6:] == [("settle", "arslan-T9-r3")] and seen[-1] is None     # off: the shared instance


def test_rerun_passes_the_model_through(monkeypatch, capsys):
    """U10 reruns single cells on Claude too; without --models they ran on the default model."""
    from scripts.kernel_bench import rerun, runner
    calls = []
    monkeypatch.setattr(runner, "sandbox_profile", lambda: "sb")
    monkeypatch.setattr(runner, "run_one", lambda task, who, n, prompts, sb, models=None: calls.append(
        (task, who, n, models)) or {"run": f"{who}-{task}-r{n}", "model": (models or {}).get(who, "default"),
                                    "passed": True, "rc": 0, "check": {"score": 3}, "usage": {"usd_peak": 0, "span_s": 0}})
    rerun.main(["--models", "arslan=claude-sonnet-5", "T5:arslan:2", "T9:arslan:3"])
    rerun.main(["T1:arslan:1"])
    assert calls == [("T5", "arslan", 2, {"arslan": "claude-sonnet-5"}), ("T9", "arslan", 3, {"arslan": "claude-sonnet-5"}),
                     ("T1", "arslan", 1, {})]
    assert '"model": "claude-sonnet-5"' in capsys.readouterr().out


def test_a_command_in_its_own_session_does_not_outlive_its_fresh_instance(tmp_path, monkeypatch):
    """Arslan starts commands with start_new_session: the group signal misses them, and a slow one
    would keep running into the next run (③Hands' review of #228)."""
    import socket
    from scripts.kernel_bench import runner
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    site = tmp_path / "site"
    (site / "api/v1").mkdir(parents=True)
    (site / "api/v1/health").write_text("ok")
    server = tmp_path / "server.py"                # stands in for uvicorn with a command in flight
    server.write_text(
        "import http.server, functools, subprocess, sys\n"
        "child = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
        f"open({str(tmp_path / 'child')!r}, 'w').write(str(child.pid))\n"
        f"handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory={str(site)!r})\n"
        "http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), handler).serve_forever()\n")
    script = tmp_path / "start.sh"
    script.write_text(f'#!/bin/bash\nexec {sys.executable} {server} "$2"\n')
    script.chmod(0o755)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "START_ARSLAN", script)
    monkeypatch.setattr(runner, "ARSLAN_API", f"http://127.0.0.1:{port}/api/v1")
    with runner.fresh_instance("arslan-T7-r1", "arslan"):
        child = int((tmp_path / "child").read_text())
        assert runner._alive(child) and os.getpgid(child) == child           # its own session
    time.sleep(0.2)
    assert not runner._alive(child) or _zombie(child)
    assert "killed 1 process" in (tmp_path / "runs" / "arslan-T7-r1.instance.log").read_text()


def _zombie(pid: int) -> bool:
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return out.strip().startswith("Z")


def test_a_reused_pid_is_not_killed(monkeypatch):
    """Only a leftover whose start time still matches is killed: a pid recycled during the stop
    may be one of the user's own processes (③Hands' review of #228)."""
    from scripts.kernel_bench import runner
    snapshots = iter([{10: (1, "Mon Oct 19 10:00:00 2026"), 11: (10, "Mon Oct 19 10:00:01 2026"),
                       12: (10, "Mon Oct 19 10:00:02 2026")},
                      {11: (1, "Mon Oct 19 10:00:01 2026"), 12: (1, "Mon Oct 19 10:09:59 2026")}])
    monkeypatch.setattr(runner, "_processes", lambda: next(snapshots))
    tree = runner._descendants(10)
    assert tree == {11: "Mon Oct 19 10:00:01 2026", 12: "Mon Oct 19 10:00:02 2026"}
    assert runner._survivors(tree) == [11]          # 12 is a new process on a recycled pid


def test_the_bench_never_ends_a_run_before_arslans_own_limits_do():
    """0.1.63 K4b gate: a 15-minute bench cap cut off an inline T2 turn that Arslan's own limits allowed.
    The driver's cap is above the standard tier's hard wall clock, and the process limit above the driver's."""
    from arslan.execution_budget import DEFAULT_TIER, HARD_OVER_SOFT, TIERS
    from scripts.kernel_bench import runner
    assert RUN_TIMEOUT_S > TIERS[DEFAULT_TIER]["wall_seconds"] * HARD_OVER_SOFT
    assert runner.TIMEOUT > RUN_TIMEOUT_S


def test_an_ab_cell_sets_extra_settings_but_never_the_workspace(monkeypatch):
    import pytest

    from scripts.kernel_bench.arslan_driver import settings_body
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    assert settings_body("/run") == {"workspace_dir": "/run"}
    monkeypatch.setenv("BENCH_ARSLAN_SETTINGS", '{"tools_all_resident": "true", "workspace_dir": "/elsewhere"}')
    assert settings_body("/run") == {"tools_all_resident": "true", "workspace_dir": "/run"}
    monkeypatch.setenv("BENCH_ARSLAN_SETTINGS", '{"tools_all_resident": true}')
    with pytest.raises(ValueError):
        settings_body("/run")
