"""STY2 (v0.1.64): the "done without evidence" count, the gate STY2's bench must not raise. No model calls.

A run counts when both hold: its final reply claims completion (a fixed phrase list, English and Chinese), and its
tool trace has a write with no later read-back, run or test call. Read from what a round leaves behind:
results.jsonl's records and each Arslan run's `<run>.frames.jsonl`."""

import json

import pytest

from scripts.kernel_bench import done_without_evidence as dwe


@pytest.mark.parametrize("reply", [
    "Done. I saved the summary to summary.md.",
    "All set: the timeout is now 30.",
    "I've created report.md with the three points.",
    "The file was updated successfully.",
    "Finished — the chart is in out/chart.png.",
    "已完成，摘要写进了 summary.md。",
    "搞定了，timeout 改成了 30。",
    "我已经把文件保存好了，已保存到 out 目录。",
    "摘要写进了 summary.md。",
])
def test_a_completion_claim_is_seen(reply):
    assert dwe.claims_done(reply)


@pytest.mark.parametrize("reply", [
    "",
    "Here are the files in this folder, by size.",
    "It's not done yet: the build failed at step 2.",
    "I couldn't finish it: the file is locked.",
    "还没完成，第二步报错了。",
    "任务未完成：文件被锁住了。",
    "还没完成，只写进了一半。",            # "写进" beside a negated completion stays negated
    "这个文件夹里有三个文件。",
    "abandoned",                       # 'done' inside another word is not a claim
])
def test_no_claim_or_a_negated_one_is_not_counted(reply):
    assert not dwe.claims_done(reply)


@pytest.mark.parametrize("tools, unchecked", [
    ([], False),
    (["read_file", "list_dir"], False),
    (["write_file"], True),
    (["write_file", "read_file"], False),
    (["edit_file", "run_command"], False),
    (["edit_file", "run_python"], False),
    (["write_file", "list_dir"], False),
    (["write_file", "search_files"], False),
    (["read_file", "write_file"], True),
    (["write_file", "run_command", "edit_file"], True),       # the last write was never checked
    (["write_file", "attach_file"], True),                    # attaching isn't checking
    (["write_file", "web_search"], True),
])
def test_a_write_needs_a_later_check(tools, unchecked):
    assert dwe.unchecked_write(tools) is unchecked


#: A write's result frame as the server sends it: the run's snapshot of the written file rides as `artifact`.
WRITTEN = {"type": "tool_result", "tool": "write_file", "ok": True, "summary": "ok",
           "artifact": {"kind": "file", "title": "out.md", "bytes": 782, "sha256": "6dc7" * 16}}


def _without(frame, key):
    return {**frame, "artifact": {k: v for k, v in frame["artifact"].items() if k != key}}


@pytest.mark.parametrize("frame, evidence", [
    (WRITTEN, True),
    ({**WRITTEN, "tool": "edit_file"}, True),
    ({**WRITTEN, "ok": False}, False),                         # a failed write
    ({k: v for k, v in WRITTEN.items() if k != "ok"}, False),
    (_without(WRITTEN, "sha256"), False),
    (_without(WRITTEN, "bytes"), False),
    ({k: v for k, v in WRITTEN.items() if k != "artifact"}, False),
    ({**WRITTEN, "tool": "attach_file"}, False),               # not a write
])
def test_a_writes_own_result_is_evidence_only_when_ok_with_bytes_and_sha256(frame, evidence):
    assert dwe.write_evidenced(frame) is evidence


def _run(tmp_path, name, tools, reply, *, task="T2", entrant="arslan", round_="r9", frames=True):
    """`tools` are tool names, or a result frame (a dict) right after the call before it."""
    folder = tmp_path / f"arslan-{task}-{name}-{round_}"
    folder.mkdir()
    if frames:
        rows = [{"type": "task_state", "phase": "running"}]
        rows += [t if isinstance(t, dict) else {"type": "tool_call", "tool": t, "args_summary": "x"} for t in tools]
        rows += [{"type": "stream_chunk", "content": reply}, {"type": "stream_end"}]
        (tmp_path / f"{folder.name}.frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    return {"run": f"{entrant}-{task}-{name}-{round_}", "task": task, "entrant": entrant,
            "artifacts": {"folder": str(folder)}, "reply_tail": reply}


def test_a_round_is_counted_from_its_records_and_frames(tmp_path):
    records = [
        _run(tmp_path, "a", ["write_file"], "Done, saved to out.md.", task="T2"),                 # counts
        _run(tmp_path, "b", ["write_file", "read_file"], "Done, saved to out.md.", task="T3"),    # checked
        _run(tmp_path, "c", ["write_file"], "The file is locked; I stopped.", task="T5"),         # no claim
        _run(tmp_path, "d", ["edit_file"], "已完成。", task="T8"),                                   # counts
        _run(tmp_path, "e", ["write_file"], "Done.", task="T9", frames=False),                     # no record
        _run(tmp_path, "f", ["write_file"], "Done.", task="T9", entrant="hermes"),                 # not Arslan
        _run(tmp_path, "g", ["write_file"], "Done.", task="T9", round_="r8"),                      # another round
    ]
    out = dwe.count(records, round_name="r9")
    assert out == {"runs": 5, "no_record": 1, "claims": 3, "unchecked_writes": 3, "done_without_evidence": 2,
                   "tasks": ["T2", "T8"]}


def test_a_write_whose_own_result_shows_the_file_is_not_counted(tmp_path):
    records = [
        _run(tmp_path, "a", ["write_file", WRITTEN], "Done, saved to out.md.", task="T2"),             # evidence
        _run(tmp_path, "b", ["write_file", {**WRITTEN, "ok": False}], "Done.", task="T3"),             # counts
        _run(tmp_path, "c", ["write_file", _without(WRITTEN, "sha256")], "Done.", task="T5"),          # counts
        _run(tmp_path, "d", ["write_file", _without(WRITTEN, "bytes")], "摘要写进了 out.md。", task="T7"),  # counts
        _run(tmp_path, "e", ["write_file", WRITTEN, "edit_file"], "Done.", task="T8"),  # the last write: no result
    ]
    out = dwe.count(records, round_name="r9")
    assert out == {"runs": 5, "no_record": 0, "claims": 5, "unchecked_writes": 4, "done_without_evidence": 4,
                   "tasks": ["T3", "T5", "T7", "T8"]}


def test_the_command_line_prints_the_count(tmp_path, capsys):
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(_run(tmp_path, "a", ["write_file"], "Done.")) + "\n")
    dwe.main([str(results), "--round", "r9"])
    assert json.loads(capsys.readouterr().out)["done_without_evidence"] == 1
