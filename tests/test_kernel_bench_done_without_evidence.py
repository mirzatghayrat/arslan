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


def _run(tmp_path, name, tools, reply, *, task="T2", entrant="arslan", round_="r9", frames=True):
    folder = tmp_path / f"arslan-{task}-{name}-{round_}"
    folder.mkdir()
    if frames:
        rows = [{"type": "task_state", "phase": "running"}]
        rows += [{"type": "tool_call", "tool": t, "args_summary": "x"} for t in tools]
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


def test_the_command_line_prints_the_count(tmp_path, capsys):
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(_run(tmp_path, "a", ["write_file"], "Done.")) + "\n")
    dwe.main([str(results), "--round", "r9"])
    assert json.loads(capsys.readouterr().out)["done_without_evidence"] == 1
