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


def _frame(t):
    """A tool name, a (tool name, arguments) pair, or a result frame (a dict) as it stands."""
    if isinstance(t, dict):
        return t
    if isinstance(t, tuple):
        return {"type": "tool_call", "tool": t[0], "args_summary": json.dumps(t[1], ensure_ascii=False)}
    return {"type": "tool_call", "tool": t, "args_summary": "x"}


def _run(tmp_path, name, tools, reply, *, task="T2", entrant="arslan", round_="r9", frames=True):
    """`tools` are tool names or (name, arguments) pairs, or a result frame (a dict) right after the call before it."""
    folder = tmp_path / f"arslan-{task}-{name}-{round_}"
    folder.mkdir()
    if frames:
        rows = [{"type": "task_state", "phase": "running"}]
        rows += [_frame(t) for t in tools]
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
                   "tasks": ["T2", "T8"],
                   # The stricter counts (the replies above have no check line and their writes name no file).
                   "claim_without_check_line": 3, "claim_without_check_line_tasks": ["T2", "T3", "T8"],
                   "claimed_file_untouched": 2, "claimed_file_untouched_tasks": ["T2", "T3"]}


def test_a_write_whose_own_result_shows_the_file_is_not_counted(tmp_path):
    records = [
        _run(tmp_path, "a", ["write_file", WRITTEN], "Done, saved to out.md.", task="T2"),             # evidence
        _run(tmp_path, "b", ["write_file", {**WRITTEN, "ok": False}], "Done.", task="T3"),             # counts
        _run(tmp_path, "c", ["write_file", _without(WRITTEN, "sha256")], "Done.", task="T5"),          # counts
        _run(tmp_path, "d", ["write_file", _without(WRITTEN, "bytes")], "摘要写进了 out.md。", task="T7"),  # counts
        _run(tmp_path, "e", ["write_file", WRITTEN, "edit_file"], "Done.", task="T8"),  # the last write: no result
    ]
    out = dwe.count(records, round_name="r9")
    assert {k: out[k] for k in ("runs", "no_record", "claims", "unchecked_writes", "done_without_evidence", "tasks")} \
        == {"runs": 5, "no_record": 0, "claims": 5, "unchecked_writes": 4, "done_without_evidence": 4,
            "tasks": ["T3", "T5", "T7", "T8"]}


def test_the_command_line_prints_the_count(tmp_path, capsys):
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(_run(tmp_path, "a", ["write_file"], "Done.")) + "\n")
    dwe.main([str(results), "--round", "r9"])
    out = json.loads(capsys.readouterr().out)
    assert (out["done_without_evidence"], out["claim_without_check_line"], out["claimed_file_untouched"]) == (1, 1, 0)


# --- The stricter counts: a claim with no check line, and a claimed file nothing touched. ---

@pytest.mark.parametrize("reply, has_line", [
    # The closing lines the answer prompt asks for (tool_loop._CLOSING_NOTE): how it was checked, and what was not.
    # The prompt says to call the second unverified, with "未核对" as its Chinese example.
    ("Done, saved to out.md.\n- How I checked: read the file back.", True),
    ("Done, saved to out.md.\n- Unverified: the chart's colours.", True),
    ("已完成，摘要写进了 summary.md。\n- 怎么核对的：读回了文件。", True),
    ("已完成。\n- 如何核对：读回了文件。", True),
    ("已完成。\n核对方式：用 find 读回了目录。", True),
    ("已完成。\n- 未核对：没有跑测试。", True),
    ("Done, saved to out.md.", False),
    ("已完成，摘要写进了 summary.md。", False),
    ("Done. I checked nothing else.", False),                 # not a form the prompt asks for
])
def test_a_check_line_is_one_the_prompt_asks_for(reply, has_line):
    assert dwe.has_check_line(reply) is has_line


@pytest.mark.parametrize("reply, files", [
    ("Done, saved to out.md.", ["out.md"]),
    ("I've created `reports/summary.md` with the three points.", ["reports/summary.md"]),
    ("清单已写入 `Downloads/重复文件报告.md`，就放在根目录。", ["Downloads/重复文件报告.md"]),
    ("脚本已跑完，校验码 `a7c1` 已写进 `answer.txt`。", ["answer.txt"]),
    ("I read input.csv. Done.", []),                          # the file is in another sentence
    ("改好了，只动了这两个文件：\n- `settings.toml`\n- `worker.py`", []),  # a list on the lines below the claim
    ("Opened `notes.md` and finished.", []),                  # named before the claim word
    ("It's not done yet; out.md is empty.", []),               # a negated claim claims no file
    ("Done, see https://example.com/page.html.", []),         # a link is not a file
])
def test_the_files_a_claim_names(reply, files):
    assert dwe.claimed_files(reply) == files


OK_RESULT = {**WRITTEN, "ok": True}
FAILED_RESULT = {**WRITTEN, "ok": False}


def test_a_claim_without_a_check_line_is_counted(tmp_path):
    records = [
        _run(tmp_path, "a", [], "Done.\n- How I checked: ran the tests.", task="T2"),
        _run(tmp_path, "b", [], "已完成。\n- 怎么核对的：读回了文件。", task="T3"),
        _run(tmp_path, "c", [], "Done.", task="T5"),                                              # counts
        _run(tmp_path, "d", [], "已完成。", task="T7"),                                             # counts
        _run(tmp_path, "e", [], "It's not done yet: the build failed.", task="T8"),                # negated
        _run(tmp_path, "f", [], "还没完成，第二步报错了。", task="T9"),                                # negated
    ]
    out = dwe.count(records, round_name="r9")
    assert (out["claim_without_check_line"], out["claim_without_check_line_tasks"]) == (2, ["T5", "T7"])


def test_a_claimed_file_needs_an_ok_write_or_a_later_check_that_names_it(tmp_path):
    ok_write = [("write_file", {"path": "/w/out.md", "content": "x"}), OK_RESULT]
    records = [
        # An ok write of the claimed file.
        _run(tmp_path, "a", ok_write, "Done, saved to out.md.", task="T1"),
        # A failed write, then a read naming the file: read back.
        _run(tmp_path, "b", [("write_file", {"path": "/w/out.md"}), FAILED_RESULT, ("read_file", {"path": "/w/out.md"})],
             "Done, saved to out.md.", task="T2"),
        # No write at all: the old count has nothing to count, the new one does.
        _run(tmp_path, "c", [("web_search", {"query": "out.md"})], "Done, saved to out.md.", task="T3"),
        # Written only through run_command, then a folder listing that does not name it (T5-r3's shape).
        _run(tmp_path, "d", [("run_command", {"command": "printf x > /w/重复文件清单.md"}),
                             ("run_command", {"command": "find /w -maxdepth 1"})],
             "完整清单已写入 `重复文件清单.md`。", task="T5"),
        # Written through run_command, then read back by a second command that names it.
        _run(tmp_path, "e", [("run_command", {"command": "printf x > /w/out.md"}), ("run_command", {"command": "cat /w/out.md"})],
             "Done, saved to out.md.", task="T6"),
        # A claim that names a folder: the write must be in that folder.
        _run(tmp_path, "f", [("write_file", {"path": "/w/b/out.md"}), OK_RESULT], "Done, saved to `a/out.md`.", task="T7"),
        _run(tmp_path, "g", [("write_file", {"path": "/w/a/out.md"}), OK_RESULT], "Done, saved to `a/out.md`.", task="T8"),
        # The call names a shorter relative path that the claim ends with.
        _run(tmp_path, "h", [("write_file", {"path": "trash/out.md"}), OK_RESULT], "Done, saved to `workspace/trash/out.md`.",
             task="T9"),
        # A read before a failed write is not a later check.
        _run(tmp_path, "i", [("read_file", {"path": "/w/out.md"}), ("write_file", {"path": "/w/out.md"}), FAILED_RESULT],
             "Done, saved to out.md.", task="T10"),
        # A bare name matches the same name in any folder, not a longer name that ends with it.
        _run(tmp_path, "j", [("write_file", {"path": "/w/about.md"}), OK_RESULT], "Done, saved to out.md.", task="T11"),
    ]
    out = dwe.count(records, round_name="r9")
    assert (out["claimed_file_untouched"], out["claimed_file_untouched_tasks"]) == (5, ["T10", "T11", "T3", "T5", "T7"])
    # The old count is unchanged by the new one: c, d and e have no write_file, so it never sees them.
    assert out["tasks"] == ["T10"]
