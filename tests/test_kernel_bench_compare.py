"""H0 PR 1 (harness plan §4.2, §4.3): off/on runs of one settings switch, the results table keyed by commit and
switch, the failure-class field, and the off-against-on report. No model calls: the dry run drives a fake driver."""

import json
import sys

import pytest

from scripts.kernel_bench import compare, meter, runner


def row(task="T3", passed=True, *, arm="off", repeat=1, usd=0.10, steps=5, model="deepseek-v4-pro", commit="c0ffee",
        day="2026-11-14", switch="show_technical_details", round_name="h0-test", end="done", cls=None):
    r = {"commit": commit, "switch": switch, "arm": arm, "value": "true" if arm == "on" else "false",
         "model": model, "task": task, "repeat": repeat, "round": round_name, "day": day, "passed": passed,
         "end": end, "end_state": compare.end_state({"end": end}), "tool_steps": steps, "usd": usd,
         "failure_class": cls, "failure_cause": None, "class_source": None}
    if cls is None:
        r["failure_class"], r["failure_cause"] = compare.auto_class(r)
        r["class_source"] = "auto" if r["failure_class"] else None
    r["id"] = compare.row_id(r)
    return r


def arms(spec: dict, **kw) -> tuple[list, list]:
    """{task: (off passes, on passes, k)} -> rows for both arms."""
    off, on = [], []
    for task, (p_off, p_on, k) in spec.items():
        off += [row(task, n < p_off, arm="off", repeat=n + 1, **kw) for n in range(k)]
        on += [row(task, n < p_on, arm="on", repeat=n + 1, **kw) for n in range(k)]
    return off, on


# ── the table key ─────────────────────────────────────────────────────────────

def test_the_key_names_commit_and_switch():
    a, b = row(switch="alpha"), row(switch="beta")
    assert a["id"] != b["id"]
    assert "alpha" in a["id"] and "c0ffee" in a["id"]
    assert row(commit="other")["id"] != row()["id"]
    assert row(arm="on")["id"] != row()["id"]


def test_two_switches_on_one_commit_keep_their_own_rows_and_corrections(tmp_path):
    a = [row(switch="alpha", passed=False, end="task_waiting_user")]
    b = [row(switch="beta", passed=False, end="task_waiting_user")]
    compare.append(a + b, tmp_path)
    compare.correct(tmp_path, a[0]["id"], "facts", "The table cites no source.")
    rows = {r["switch"]: r for r in compare.load(tmp_path)}
    assert set(rows) == {"alpha", "beta"}
    assert rows["alpha"]["failure_class"] == "facts" and rows["alpha"]["class_source"] == "hand"
    assert rows["beta"]["failure_class"] == "wait" and rows["beta"]["class_source"] == "auto"


def test_a_rerun_of_the_same_key_replaces_the_row_but_keeps_the_hand_class(tmp_path):
    first = row(passed=False, end="done")
    compare.append([first], tmp_path)
    assert compare.load(tmp_path)[0]["failure_class"] is None        # done but failed: a reader decides
    compare.correct(tmp_path, first["id"], "incomplete", "Two of the six figures are missing.")
    again = dict(first, usd=0.2)
    compare.append([again], tmp_path)
    [got] = compare.load(tmp_path)
    assert got["usd"] == 0.2
    assert (got["failure_class"], got["failure_cause"], got["class_source"]) == (
        "incomplete", "Two of the six figures are missing.", "hand")


def test_a_hand_class_must_be_one_of_the_classes(tmp_path):
    with pytest.raises(SystemExit):
        compare.correct(tmp_path, "x", "laziness", "No.")
    with pytest.raises(SystemExit):
        compare.correct(tmp_path, "x", "wait", "")
    assert set(compare.CLASSES) == {"wait", "incomplete", "instruction", "facts", "tool", "bench", "regression",
                                    "other"}


# ── end state and the automatic class ─────────────────────────────────────────

@pytest.mark.parametrize("end, pause, state", [
    ("done", None, "done"),
    ("task_waiting_user", None, "waiting"),
    ("task_waiting_user", "task_no_progress", "waiting"),
    ("task_waiting_user", "task_budget_exhausted", "budget"),
    ("job_out_of_budget", None, "budget"),
    ("job_blocked", None, "waiting"),
    ("timeout", None, "timeout"),
    ("task_failed", None, "failed"),
    (None, None, "no_report"),
    ("job_partial", None, "job_partial"),
])
def test_end_state(end, pause, state):
    assert compare.end_state({"end": end}, pause) == state


def test_the_pause_reason_comes_from_the_last_task_state_frame(tmp_path):
    run = tmp_path / "arslan-T3-r1"
    run.mkdir()
    frames = [{"type": "task_state", "phase": "running", "pause_reason": None},
              {"type": "task_state", "phase": "waiting_user", "pause_reason": "task_budget_exhausted"}]
    (tmp_path / "arslan-T3-r1.frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames) + "\n")
    assert compare.pause_reason(str(run)) == "task_budget_exhausted"
    assert compare.pause_reason(str(tmp_path / "missing")) is None


@pytest.mark.parametrize("state, passed, rate_limited, cls", [
    ("waiting", False, 0, "wait"),
    ("budget", False, 0, "incomplete"),
    ("no_report", False, 0, "bench"),
    ("done", False, 2, "tool"),
    ("done", False, 0, None),            # finished but the checker failed it: a reader classifies
    ("timeout", False, 0, None),
    ("waiting", True, 0, None),          # a pass has no failure class
])
def test_the_bench_fills_the_class_where_it_can(state, passed, rate_limited, cls):
    got, cause = compare.auto_class({"end_state": state, "passed": passed, "rate_limited_429": rate_limited,
                                     "end": "task_waiting_user", "pause_reason": None})
    assert got == cls
    assert (cause is None) == (cls is None)


# ── the verdict (§4.3) ───────────────────────────────────────────────────────

def test_a_task_falling_from_every_run_to_two_short_is_a_veto():
    off, on = arms({"T1": (5, 3, 5), "T3": (5, 5, 5)})
    v = compare.verdict(off, on)
    assert v["judged"] and v["veto"] and v["verdict"] == "VETO"
    assert any("T1" in reason for reason in v["veto_reasons"])


def test_one_short_is_not_a_veto():
    off, on = arms({"T1": (5, 4, 5), "T3": (5, 5, 5)})
    v = compare.verdict(off, on)
    assert not v["veto"] and v["verdict"] == "NO EFFECT"


def test_a_task_that_was_not_perfect_off_does_not_trip_the_task_rule():
    off, on = arms({"T1": (4, 2, 5)})                 # 4/5 to 2/5: the total falls by 2, which is allowed
    assert not compare.verdict(off, on)["veto"]


def test_the_total_may_fall_by_two_but_not_three():
    off, on = arms({"T1": (4, 3, 5), "T2": (4, 3, 5), "T3": (4, 4, 5)})        # -2
    assert not compare.verdict(off, on)["veto"]
    off, on = arms({"T1": (4, 3, 5), "T2": (4, 3, 5), "T3": (4, 3, 5)})        # -3
    v = compare.verdict(off, on)
    assert v["veto"] and any("total" in reason for reason in v["veto_reasons"])


def test_cost_may_rise_a_quarter_but_not_more_without_a_gain():
    off, _ = arms({"T1": (3, 3, 5)})
    _, on = arms({"T1": (3, 3, 5)}, usd=0.125)                               # +25%
    assert not compare.verdict(off, on)["veto"]
    _, on = arms({"T1": (3, 3, 5)}, usd=0.126)                               # +26%
    v = compare.verdict(off, on)
    assert v["veto"] and any("cost" in reason for reason in v["veto_reasons"])
    _, on = arms({"T1": (3, 4, 5)}, usd=0.13)                                # +30% with one more pass
    assert not compare.verdict(off, on)["veto"]


def test_three_more_passes_counts_as_working():
    off, on = arms({"T1": (1, 2, 5), "T2": (1, 2, 5), "T3": (1, 2, 5)})
    v = compare.verdict(off, on)
    assert v["works"] and v["verdict"] == "WORKS"
    off, on = arms({"T1": (1, 2, 5), "T2": (1, 2, 5), "T3": (1, 1, 5)})
    v = compare.verdict(off, on)
    assert not v["works"] and v["verdict"] == "NO EFFECT"


@pytest.mark.parametrize("change", [{"model": "claude-opus-5-5"}, {"commit": "beef"}, {"day": "2026-11-15"}])
def test_arms_from_another_model_commit_or_day_are_not_judged(change):
    off, _ = arms({"T1": (3, 3, 3)})
    _, on = arms({"T1": (3, 3, 3)}, **change)
    v = compare.verdict(off, on)
    assert not v["judged"] and v["verdict"] == "NOT JUDGED"


def test_arms_with_different_runs_are_not_judged():
    off, on = arms({"T1": (3, 3, 3)})
    v = compare.verdict(off, on[:2])
    assert not v["judged"]


def test_the_report_prints_both_arms_and_labels_the_missing_sets():
    off, on = arms({"T1": (2, 2, 2), "T3": (2, 0, 2)})
    on[2]["failure_class"], on[3]["failure_class"] = "wait", None
    text = compare.render(off, on)
    assert "| T3 | 2/2 | 0/2 |" in text
    assert "Veto: yes" in text and "Counts as working: no" in text and "Verdict: VETO" in text
    assert "wait 1" in text and "unclassified 1" in text
    assert "no regression, capability, held-out or behaviour set yet" in text
    assert "median tool steps" in text and "$ per run" in text


# ── runs per task, the switch ─────────────────────────────────────────────────

def test_runs_per_task():
    assert compare.runs_per_task("2", ["T1", "T3"]) == {"T1": 2, "T3": 2}
    with pytest.raises(SystemExit):
        compare.runs_per_task("0", ["T1"])


@pytest.mark.parametrize("key", ["shell_confirm_policy", "workspace_dir"])
def test_the_driver_owned_settings_cannot_be_the_switch(key, monkeypatch):
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    with pytest.raises(SystemExit):
        compare.arm_settings(key, "x")


def test_the_switch_joins_the_other_bench_settings(monkeypatch):
    monkeypatch.setenv("BENCH_ARSLAN_SETTINGS", '{"folder_rules_enabled": "false"}')
    assert compare.arm_settings("show_technical_details", "true") == {
        "folder_rules_enabled": "false", "show_technical_details": "true"}
    monkeypatch.setenv("BENCH_ARSLAN_SETTINGS", '{"show_technical_details": "false"}')
    with pytest.raises(SystemExit):
        compare.arm_settings("show_technical_details", "true")


# ── what the model was sent (the metering proxy sees each request) ─────────────

def test_the_meter_records_the_offered_tools_and_request_settings():
    openai = {"model": "deepseek-v4-pro", "temperature": 0.7, "max_tokens": 8192,
              "tools": [{"type": "function", "function": {"name": "run_command"}},
                        {"type": "function", "function": {"name": "read_file"}}],
              "messages": [{"role": "user", "content": "secret prompt text"}]}
    got = meter.request_settings(openai)
    assert got == {"tools": ["run_command", "read_file"], "temperature": 0.7, "max_tokens": 8192}
    anthropic = {"model": "claude-opus-5-5", "max_tokens": 16384, "thinking": {"type": "adaptive"},
                 "output_config": {"effort": "high"}, "tools": [{"name": "web_search", "input_schema": {}}]}
    assert meter.request_settings(anthropic) == {"tools": ["web_search"], "max_tokens": 16384,
                                                 "thinking": {"type": "adaptive"}, "effort": "high"}
    assert "secret" not in json.dumps(meter.request_settings(openai))


def test_a_row_carries_what_the_requests_carried():
    usage_rows = [
        {"cand": "L", "model": "deepseek-v4-pro", "req": {"tools": ["a", "b"], "temperature": 0.7, "max_tokens": 8192}},
        {"cand": "L", "model": "deepseek-v4-pro", "req": {"tools": ["a", "c"], "temperature": 0.7, "max_tokens": 8192}},
        {"cand": "other", "model": "x", "req": {"tools": ["z"]}},
    ]
    sent = compare.requests_sent("L", usage_rows, 0.0)
    assert sent["source"] == "metering proxy (as sent)"
    assert sent["tools_offered"] == ["a", "b", "c"]
    assert sent["settings"] == {"model": ["deepseek-v4-pro"], "temperature": [0.7], "max_tokens": [8192]}
    assert compare.requests_sent("L", [{"cand": "L", "model": "m"}], 0.0)["source"].startswith("not observed")


def test_review_4_a_rerun_of_the_label_reads_only_its_own_requests():
    """#879 review, later item 4: a rerun of the same --round has the same label; only requests from when this run
    started (t >= started, as runner.usage reads them) are its own."""
    usage_rows = [
        {"t": 100.0, "cand": "L", "model": "old-model", "req": {"tools": ["old_tool"], "temperature": 0.2}},
        {"t": 205.0, "cand": "L", "model": "deepseek-v4-pro", "req": {"tools": ["a"], "temperature": 0.7}},
    ]
    sent = compare.requests_sent("L", usage_rows, since=200.0)
    assert sent["tools_offered"] == ["a"]
    assert sent["settings"] == {"model": ["deepseek-v4-pro"], "temperature": [0.7]}
    record = {"run": "L", "task": "T3", "repeat": 1, "started": 200.0, "usage": {}, "artifacts": {}}
    row = compare.table_row(record, commit="c", dirty=False, switch="s", arm="off", value="false", round_name="r",
                            day="d", usage_rows=usage_rows)
    assert row["tools_offered"] == ["a"] and "old-model" not in row["request_settings"]["model"]


def test_review_4_a_rerun_through_the_dry_run_drops_the_earlier_runs_requests(fake_bench):
    root, _ = fake_bench
    label = "arslan-T1-r1-h0-dry-show_technical_details-off"
    with open(root / "usage.jsonl", "a") as f:          # the same label, from an earlier run of this round
        f.write(json.dumps({"t": 1.0, "secs": 0.5, "cand": label, "model": "old-model", "status": 200, "hit": 1,
                            "miss": 1, "out": 1, "usd_peak": 0.01, "req": {"tools": ["old_tool"]}}) + "\n")
    compare.main(["run", "--tasks", "T1", "--runs", "1", "--switch", "show_technical_details",
                  "--off", "false", "--on", "true", "--round", "h0-dry"])
    table = [json.loads(line) for line in (root / compare.TABLE).read_text().splitlines()]
    off = next(r for r in table if r["run"] == label)
    assert off["tools_offered"] == ["web_search", "write_file"]
    assert off["request_settings"]["model"] == ["deepseek-v4-pro"]


# ── the dry run: both arms through runner.run_one with a fake driver ──────────

FAKE_DRIVER = r'''
import json, os, sys, time
run, label, root = sys.argv[1], sys.argv[2], sys.argv[3]
settings = json.loads(os.environ.get("BENCH_ARSLAN_SETTINGS") or "{}")
on = settings.get("show_technical_details") == "true"
fail = on and "-T3-" in label
frames = [{"type": "tool_call", "tool": "web_search"}, {"type": "tool_call", "tool": "write_file"},
          {"type": "tool_result", "tool": "write_file", "ok": True, "artifact": {"bytes": 10, "sha256": "ab"}},
          {"type": "task_state", "phase": "waiting_user" if fail else "succeeded", "pause_reason": None}]
open(run + ".frames.jsonl", "w").write("\n".join(json.dumps(f) for f in frames) + "\n")
open(os.path.join(run, "score.txt"), "w").write("0" if fail else "3")
with open(os.path.join(root, "usage.jsonl"), "a") as f:
    for _ in range(2):
        f.write(json.dumps({"t": time.time(), "secs": 0.5, "cand": label, "model": "deepseek-v4-pro", "status": 200,
                            "hit": 100, "miss": 50, "out": 20, "usd_peak": 0.01,
                            "req": {"tools": ["web_search", "write_file"], "temperature": 0.7}}) + "\n")
print(json.dumps({"end": "task_waiting_user" if fail else "done", "approvals": 1, "settings_seen": settings,
                  "final": "Done. I saved the table." + (" Should I go on?" if fail else "")}))
'''


@pytest.fixture
def fake_bench(tmp_path, monkeypatch):
    driver = tmp_path / "fake_driver.py"
    driver.write_text(FAKE_DRIVER)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "FRESH", False)
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    monkeypatch.setattr(runner, "entrant_version", lambda who: None)

    def command(who, label, run, prompt, sb, **kw):
        return [sys.executable, str(driver), str(run), label, str(tmp_path)], dict(__import__("os").environ)
    monkeypatch.setattr(runner, "command", command)
    score = {"score": None}

    def check(run, reply, ctx):
        return {"score": int((tmp_path / "runs" / __import__("pathlib").Path(run).name / "score.txt").read_text())}
    monkeypatch.setitem(runner.CHECKS, "T1", check)
    monkeypatch.setitem(runner.CHECKS, "T3", check)
    monkeypatch.setattr(compare, "commit_of", lambda: ("c0ffee1234567890", False))
    monkeypatch.delenv("BENCH_ARSLAN_SETTINGS", raising=False)
    monkeypatch.setattr(runner, "ROUND", "")
    return tmp_path, score


def test_the_dry_run_fills_the_table_and_the_report(fake_bench, capsys):
    root, _ = fake_bench
    compare.main(["run", "--tasks", "T1,T3", "--runs", "2", "--switch", "show_technical_details",
                  "--off", "false", "--on", "true", "--round", "h0-dry"])
    table = [json.loads(line) for line in (root / compare.TABLE).read_text().splitlines()]
    assert len(table) == 8
    assert {(r["arm"], r["task"], r["repeat"]) for r in table} == {
        (arm, task, n) for arm in ("off", "on") for task in ("T1", "T3") for n in (1, 2)}
    assert len({r["id"] for r in table}) == 8
    assert all(r["commit"] == "c0ffee1234567890" and r["switch"] == "show_technical_details" for r in table)
    # each arm's run got its own setting, and its own run label (meter caps and run folders are per label)
    for r in table:
        stdout = json.loads((root / "runs" / f"{r['run']}.stdout").read_text().splitlines()[-1])
        assert stdout["settings_seen"] == {"show_technical_details": r["value"]}
        assert r["run"].endswith(f"-h0-dry-show_technical_details-{r['arm']}")
    assert runner.ROUND == ""                                   # the arm's round is put back
    t3_on = [r for r in table if r["task"] == "T3" and r["arm"] == "on"]
    assert all(not r["passed"] and r["end_state"] == "waiting" and r["failure_class"] == "wait" for r in t3_on)
    one = table[0]
    for field in ("passed", "end_state", "tool_steps", "model_requests", "input_tokens", "output_tokens",
                  "cache_hit_tokens", "usd", "seconds", "cards_shown", "done_without_evidence", "failure_class",
                  "failure_cause", "tools_offered", "request_settings", "request_source"):
        assert field in one, field
    assert (one["tool_steps"], one["model_requests"], one["input_tokens"], one["output_tokens"],
            one["cache_hit_tokens"], one["cards_shown"]) == (2, 2, 300, 40, 200, 1)
    assert one["usd"] == pytest.approx(0.02)
    assert one["done_without_evidence"] is False                # the write's own result shows the file
    assert one["tools_offered"] == ["web_search", "write_file"]
    # the legacy results.jsonl still gets every run, as runner.main writes it
    assert len((root / "results.jsonl").read_text().splitlines()) == 8
    capsys.readouterr()
    compare.main(["report", "--switch", "show_technical_details"])
    out = capsys.readouterr().out
    assert "| T3 | 2/2 | 0/2 |" in out and "| T1 | 2/2 | 2/2 |" in out
    assert "Verdict: VETO" in out and "wait 2" in out
