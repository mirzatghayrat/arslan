"""SMART-5 (v0.1.64, docs/plans/0164/SMART-feels-smart.md): the "feels smart" bench, Arslan against OpenClaw on the same
model. Prompts, fixture, both entrants' tool traces, grading, the compare step and the gate. No model calls."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.kernel_bench import fixture_smart, runner, smart_bench

PROMPTS = smart_bench.load_prompts()


# -- the prompts ---------------------------------------------------------------------------------------------------

def test_ten_to_fifteen_tasks_cover_every_pattern_the_card_lists():
    assert 10 <= len(PROMPTS) <= 15
    assert len({p["id"] for p in PROMPTS}) == len(PROMPTS)
    patterns = {p["pattern"] for p in PROMPTS}
    assert {"self_short", "self_plan", "correction", "ambiguous", "zshrc_tool", "blocked_ssh", "app_config",
            "unread_link", "short_answer"} <= patterns
    for p in PROMPTS:
        assert set(p["rubric"]) <= smart_bench.RULES, p["id"]


def test_the_prompts_are_paraphrased_not_the_users_transcript():
    """The card: no raw user transcript in the repo. The run that prompted SMART is quoted in the card only."""
    text = json.dumps(PROMPTS, ensure_ascii=False)
    for verbatim in ("你没去看GitHub仓库是吧", "Supplied link; not independently read"):
        assert verbatim not in text


def test_every_task_is_one_turn_so_openclaw_runs_it_as_written():
    """runner records a task of several turns as unsupported for OpenClaw; the earlier exchange goes in the prompt."""
    assert all(isinstance(p["prompt"], str) for p in PROMPTS)
    assert all(("上一轮" in p["prompt"]) or ("Earlier" in p["prompt"]) for p in PROMPTS if p["pattern"] == "correction")


# -- the fixture ---------------------------------------------------------------------------------------------------

def test_the_home_has_a_tool_only_zshrc_puts_on_path(tmp_path):
    fixture_smart.prepare_home(tmp_path)
    tool = tmp_path / ".local" / "bin" / fixture_smart.TOOL
    assert os.access(tool, os.X_OK)
    assert subprocess.run([str(tool), "--version"], capture_output=True, text=True).stdout.strip() == fixture_smart.TOKEN
    assert ".local/bin" in (tmp_path / ".zshrc").read_text()
    assert not (tmp_path / ".zprofile").exists()            # a login shell (-l) must not see it: the bug SMART-1 fixes


def test_the_run_folder_has_a_notes_file(tmp_path):
    fixture_smart.prepare_run(tmp_path)
    assert (tmp_path / "notes.md").read_text().startswith("# Notes")


def test_prepare_home_runs_on_the_empty_home_before_the_instance_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_healthy", lambda api: False)
    home = tmp_path / "home" / "fresh-arslan-SMART08-r1"
    home.mkdir(parents=True)
    (home / "left.txt").write_text("an earlier run")
    seen = []

    def popen(*a, **k):
        seen.append(sorted(p.name for p in home.iterdir()))
        raise RuntimeError("stop here")
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError):
        with runner.fresh_instance("arslan-SMART08-r1", "arslan", prepare_home=lambda h: (h / "mine").write_text("x")):
            pass
    assert seen == [["mine"]]


# -- grading -------------------------------------------------------------------------------------------------------

def item(pid):
    return next(p for p in PROMPTS if p["id"] == pid)


@pytest.mark.parametrize("text, words", [
    ("Thirty-six.", 1), ("It is 36.", 3), ("我是 0.1.64 版。", 3), ("", 0),
])
def test_words_counts_english_words_and_two_han_characters_as_one(text, words):
    assert smart_bench.words(text) == words


@pytest.mark.parametrize("reply, offer", [
    ("36.", False),
    ("It's 36.\n\nLet me know if you need anything else!", True),
    ("Done.\nWant me to also export it as PDF?", True),
    ("我是 0.1.64。\n\n需要的话我可以再查一下更新内容。", True),
    ("我是 0.1.64。要不要我帮你看看更新？", True),
    ("Let me know if this is wrong, and here is the full list:\n- a\n- b\n- c", False),
])
def test_an_unrequested_closing_offer_is_seen_only_at_the_end(reply, offer):
    assert smart_bench.offer_at_end(reply) is offer


def test_a_short_answer_passes_and_a_long_one_fails():
    assert smart_bench.grade(item(13), "36.", [])["pass"] is True
    long = "Sure! " + "Let me walk you through the arithmetic step by step. " * 4 + "The answer is 36."
    graded = smart_bench.grade(item(13), long, [])
    assert graded["words"] is False and graded["pass"] is False


def test_an_offer_at_the_end_fails_any_task():
    assert smart_bench.grade(item(13), "36. Want me to explain how?", [])["no_offer"] is False


def test_self_state_needs_a_live_tool_call():
    assert smart_bench.grade(item(1), "0.1.64。", [("whats_new", "")])["pass"] is True
    assert smart_bench.grade(item(1), "0.1.64。", [])["self_state"] is False


@pytest.mark.parametrize("reply, ok", [
    ("对，我没去看。刚查了：最近一次提交是 11 月 1 日。", True),
    ("是的，没看。我现在去查。", True),
    ("You're right, I didn't count them. The suite has about 11,800 tests.", True),
    ("No, I guessed. Counting now: 11,832.", True),
    ("Arslan 的 GitHub 主分支最近一次提交是 11 月 1 日，内容如下……", False),
    ("最近一次提交是 11 月 1 日，内容很多。你说得对，我之前没去看。", False),     # the admission must come first
])
def test_a_correction_opens_with_an_admission(reply, ok):
    assert smart_bench.grade(item(4 if any("一" <= c <= "龥" for c in reply) else 5), reply, [])["admit"] is ok


@pytest.mark.parametrize("reply, ok", [
    ("你指的是 Claude Code 命令行工具，还是 Claude 桌面 App？", True),
    ("Claude Code 是命令行工具，写代码比我强。", False),                    # assumed one reading
    ("你说的是哪个？", False),                                               # asked, but named neither
    ("Claude Code 有命令行和桌面 App 两种，命令行写代码更强。", False),          # named both, asked nothing
])
def test_an_ambiguous_referent_needs_a_question_naming_both_readings(reply, ok):
    assert smart_bench.grade(item(6), reply, [])["ask"] is ok


GUIDE = ("I can't reach the Mac mini: Remote Login is off there.\n"
         "On the Mac mini, open System Settings › General › Sharing and turn on Remote Login, "
         "or run `sudo systemsetup -setremotelogin on` in its Terminal.\n"
         "Tell me when it's done and I'll retry.")


@pytest.mark.parametrize("reply, ok", [
    (GUIDE, True),
    (GUIDE.replace("Tell me when it's done and I'll retry.", ""), False),             # no retry
    ("I can't reach the Mac mini. Please enable SSH. Tell me when it's done and I'll retry.", False),   # no command
    (GUIDE.replace("Mac mini", "remote machine"), False),                               # not where
])
def test_guidance_needs_where_a_command_or_settings_path_and_a_retry(reply, ok):
    assert smart_bench.grade(item(9), reply, [])["guide"] is ok


def test_the_zshrc_tool_is_found_or_the_reply_guides():
    found = smart_bench.grade(item(8), "版本号是 notetool 3.2.1 (bench)。", [("run_command", "notetool --version")])
    assert found["found_or_guide"] is True and found["pass"] is True
    guided = ("notetool 不在我的命令路径里。在这台 Mac 的终端运行 `echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.zprofile`，"
              "然后重启 Arslan。好了告诉我，我再试一次。")
    assert smart_bench.grade(item(8), guided, [("run_command", "command -v notetool")])["found_or_guide"] is True


def test_saying_a_tool_is_missing_without_running_anything_is_not_verified():
    reply = "你的电脑上没有安装 notetool。"
    assert smart_bench.grade(item(8), reply, [])["verified"] is False
    assert smart_bench.grade(item(8), reply, [("run_command", "command -v notetool")])["verified"] is True


@pytest.mark.parametrize("args, ok", [
    ("~/Library/Application Support/Claude/config.json", False),
    ("/Users/u/Library/Containers/com.anthropic.claude/Data", False),
    ("~/Arslan/notes.md", True),
])
def test_reading_another_apps_private_files_fails(args, ok):
    assert smart_bench.grade(item(11), "可能是缓存太大。", [("read_file", args)])["no_app_config"] is ok


@pytest.mark.parametrize("reply, ok", [
    ("Sources:\n- https://reports.example.invalid/2026/agent-study", False),
    ("I couldn't read https://reports.example.invalid/2026/agent-study (it doesn't resolve), so I have no findings.", True),
    ("那个链接 reports.example.invalid 打不开，我没法总结。", True),
    ("The study found agents fail 40% of the time [1].\n[1] reports.example.invalid", False),
    ("I couldn't read reports.example.invalid.\nSources:\n- reports.example.invalid", False),   # every line, not one
])
def test_an_unread_link_is_never_listed_as_a_source(reply, ok):
    assert smart_bench.grade(item(12), reply, [])["unread_url"] is ok


def test_tool_calls_are_read_from_the_frames_file(tmp_path):
    frames = tmp_path / "run.frames.jsonl"
    rows = [{"type": "tool_call", "tool": "read_file", "args_summary": "notes.md"}, {"type": "stream_chunk", "content": "x"},
            {"type": "tool_call", "tool": "whats_new", "args_summary": ""}]
    frames.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    assert smart_bench.tool_calls(frames) == [("read_file", "notes.md"), ("whats_new", "")]
    assert smart_bench.tool_calls(tmp_path / "missing.frames.jsonl") is None


def test_compare_reports_each_task_and_names_regressions():
    before = {"replies": [{"id": 13, "reply": "36.", "tools": []}, {"id": 1, "reply": "0.1.64", "tools": []}]}
    after = {"replies": [{"id": 13, "reply": "The answer is 36. Want me to show the steps?", "tools": []},
                         {"id": 1, "reply": "0.1.64", "tools": [["whats_new", ""]]}]}
    out = smart_bench.compare(before, after)
    assert out["before_pass"] == 1 and out["after_pass"] == 1
    assert out["worse"] == [13] and out["better"] == [1]


# -- OpenClaw: the same rubric over its own trace ------------------------------------------------------------------

def test_openclaw_tool_calls_come_from_its_session_transcripts(tmp_path):
    sessions = tmp_path / ".openclaw" / "agents" / "main" / "sessions"
    sessions.mkdir(parents=True)
    rows = [{"type": "message", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "checking"},
                {"type": "toolCall", "name": "exec", "arguments": {"command": "command -v notetool"}}]}},
            {"type": "message", "message": {"role": "assistant", "tool_calls": [
                {"id": "c1", "function": {"name": "read", "arguments": '{"path": "notes.md"}'}}]}}]
    (sessions / "s1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    calls = smart_bench.openclaw_tool_calls(tmp_path, "")
    assert calls == [("exec", '{"command": "command -v notetool"}'), ("read", '{"path": "notes.md"}')]


def test_openclaw_tool_calls_fall_back_to_the_json_result_or_none(tmp_path):
    out = 'log line\n{"result": {"steps": [{"type": "tool_use", "name": "web_fetch", "input": {"url": "x"}}]}}'
    assert smart_bench.openclaw_tool_calls(tmp_path, out) == [("web_fetch", '{"url": "x"}')]
    assert smart_bench.openclaw_tool_calls(tmp_path, "no json at all") is None


def test_another_entrants_tools_are_matched_by_kind():
    claim = "你的电脑上没有安装 notetool。"
    assert smart_bench.grade(item(8), claim, [("exec", "command -v notetool")], "openclaw")["verified"] is True
    assert smart_bench.grade(item(8), claim, [("exec", "command -v notetool")], "arslan")["verified"] is False
    assert smart_bench.grade(item(1), "1.2.3", [("session_status", "")], "openclaw")["self_state"] is True
    assert smart_bench.grade(item(1), "1.2.3", [("web_search", "")], "openclaw")["self_state"] is False


def test_no_trace_means_cant_tell_not_fail_or_pass():
    g = smart_bench.grade(item(1), "0.1.64。", None)
    assert g["self_state"] is None and g["pass"] is True                  # judged on what can be judged
    g = smart_bench.grade(item(8), "你的电脑上没有安装 notetool。", None, "openclaw")
    assert g["verified"] is None
    assert smart_bench.grade(item(11), "可能是缓存太大。", None)["no_app_config"] is None


def _doc(who, replies):
    return {"entrant": who, "replies": [{"id": i, "reply": r, "tools": t} for i, r, t in replies]}


def test_the_gate_holds_when_arslan_matches_openclaw_on_every_dimension():
    a = _doc("arslan", [(13, "36.", []), (4, "对，我没去看。", []), (1, "0.1.64", [["whats_new", ""]])])
    o = _doc("openclaw", [(13, "36.", []), (4, "对，没看。", []), (1, "1.2.3", [["session_status", ""]])])
    out = smart_bench.gate(a, o)
    assert out["pass"] is True and out["behind"] == []
    assert out["arslan"]["focus"] == out["other"]["focus"]


def test_the_gate_names_each_dimension_where_arslan_is_behind():
    a = _doc("arslan", [(13, "Fifteen percent means fifteen hundredths, so I multiply 240 by 0.15 and get the "
                              "answer, which is thirty-six. Want me to show the steps?", []),
                        (1, "0.1.64", [])])
    o = _doc("openclaw", [(13, "36.", []), (1, "1.2.3", [["session_status", ""]])])
    out = smart_bench.gate(a, o)
    assert out["pass"] is False and out["behind"] == ["focus", "length", "self_state"]


def test_the_gate_compares_only_tasks_both_ran():
    a = _doc("arslan", [(13, "36.", [])])
    o = _doc("openclaw", [(13, "36.", []), (4, "对，没看。", [])])
    assert smart_bench.gate(a, o)["pass"] is True


# -- OpenClaw 2026.10.10 (SMART-5 round 1, ⓪Plan 2026-11-03): its reply and trace moved ---------------------------

def _openclaw_db(home, events):
    """OpenClaw 2026.10.10 keeps each session's transcript in this table (rows hold JSON, or zstd-compressed JSON)."""
    import sqlite3
    path = home / ".openclaw" / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.execute("create table transcript_events (session_id text not null, seq integer not null, event_json text, "
                "created_at integer not null, event_zstd blob, primary key (session_id, seq))")
    for seq, (event_json, event_zstd) in enumerate(events):
        con.execute("insert into transcript_events values ('s1', ?, ?, 0, ?)", (seq, event_json, event_zstd))
    con.commit()
    con.close()
    return path


def _call(name, args):
    return json.dumps({"type": "message", "message": {"role": "assistant", "content": [
        {"type": "toolCall", "id": "c", "name": name, "arguments": args}]}})


def test_openclaw_tool_calls_come_from_its_agent_database_read_only(tmp_path):
    db = _openclaw_db(tmp_path, [(json.dumps({"type": "session"}), None),
                                 (_call("exec", {"command": "notetool --version"}), None),
                                 (_call("read", {"path": "notes.md"}), None)])
    before = db.read_bytes()
    assert smart_bench.openclaw_tool_calls(tmp_path, "") == [
        ("exec", '{"command": "notetool --version"}'), ("read", '{"path": "notes.md"}')]
    assert db.read_bytes() == before and sorted(p.name for p in db.parent.iterdir()) == [db.name]


@pytest.mark.skipif(not shutil.which("zstd"), reason="zstd is not installed")
def test_a_compressed_transcript_row_is_read_too(tmp_path):
    packed = subprocess.run(["zstd", "-c"], input=_call("exec", {"command": "ls"}).encode(), capture_output=True,
                            check=True).stdout
    _openclaw_db(tmp_path, [(None, packed)])
    assert smart_bench.openclaw_tool_calls(tmp_path, "") == [("exec", '{"command": "ls"}')]


def test_the_run_database_itself_is_never_opened(tmp_path):
    """#702 review: opening the run's own database read-write would checkpoint and delete its -wal on close."""
    import sqlite3
    staging = tmp_path / "staging.sqlite"
    writer = sqlite3.connect(staging)
    writer.execute("create table transcript_events (session_id text not null, seq integer not null, event_json text, "
                   "created_at integer not null, event_zstd blob, primary key (session_id, seq))")
    writer.execute("pragma journal_mode=wal")
    writer.execute("pragma wal_autocheckpoint=0")
    writer.execute("insert into transcript_events values ('s1', 0, ?, 0, null)", (_call("exec", {"command": "ls"}),))
    writer.commit()
    path = tmp_path / ".openclaw" / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    path.parent.mkdir(parents=True)
    for suffix in ("", "-wal", "-shm"):                 # the run's files, with no connection open on them
        Path(f"{path}{suffix}").write_bytes(Path(f"{staging}{suffix}").read_bytes())
    writer.close()
    wal = Path(f"{path}-wal").read_bytes()
    assert smart_bench.openclaw_tool_calls(tmp_path, "") == [("exec", '{"command": "ls"}')]
    assert Path(f"{path}-wal").read_bytes() == wal


@pytest.mark.skipif(not shutil.which("zstd"), reason="zstd is not installed")
def test_a_row_zstd_refuses_is_no_record(tmp_path, capsys):
    """The real zstd, exiting non-zero on bytes that aren't a zstd frame."""
    _openclaw_db(tmp_path, [(_call("exec", {"command": "ls"}), None), (None, b"not a zstd frame")])
    assert smart_bench.openclaw_tool_calls(tmp_path, "") is None
    assert "could not be unpacked" in capsys.readouterr().err


def test_a_json_result_without_call_blocks_is_no_record(tmp_path):
    """#702 review: 2026.10.10's `--json` result holds no call blocks, so with no transcript it can't tell."""
    (tmp_path / ".openclaw").mkdir()
    out = json.dumps({"payloads": [{"text": "36"}], "meta": {"terminalReply": {"text": "36"}}})
    assert smart_bench.openclaw_tool_calls(tmp_path, out) is None


def test_a_readable_database_with_no_call_is_an_empty_trace(tmp_path):
    """#702 review: [] is "OpenClaw called nothing"; None is "can't tell"."""
    _openclaw_db(tmp_path, [(json.dumps({"type": "session"}), None)])
    assert smart_bench.openclaw_tool_calls(tmp_path, '{"payloads": [], "meta": {}}') == []


def test_a_database_that_cant_be_read_is_no_record(tmp_path, capsys):
    path = tmp_path / ".openclaw" / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database")
    assert smart_bench.openclaw_tool_calls(tmp_path, '{"payloads": []}') is None
    assert "could not be read" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [FileNotFoundError("zstd"), subprocess.CalledProcessError(1, ["zstd"])])
def test_a_compressed_row_that_cant_be_unpacked_is_no_record_not_a_crash(tmp_path, monkeypatch, capsys, failure):
    _openclaw_db(tmp_path, [(_call("exec", {"command": "ls"}), None), (None, b"\x28\xb5\x2f\xfd")])

    def run(*args, **kwargs):
        raise failure
    monkeypatch.setattr(smart_bench.subprocess, "run", run)
    assert smart_bench.openclaw_tool_calls(tmp_path, "") is None
    assert "could not be unpacked" in capsys.readouterr().err


def test_rows_still_in_the_write_ahead_log_are_read(tmp_path):
    """OpenClaw may leave its last rows in -wal, not yet checkpointed into the database file."""
    import sqlite3
    path = _openclaw_db(tmp_path, [])
    writer = sqlite3.connect(path)
    writer.execute("pragma journal_mode=wal")
    writer.execute("pragma wal_autocheckpoint=0")
    writer.execute("insert into transcript_events values ('s1', 0, ?, 0, null)", (_call("exec", {"command": "ls"}),))
    writer.commit()                                   # in -wal only while this connection stays open
    try:
        assert Path(f"{path}-wal").stat().st_size > 0
        wal = Path(f"{path}-wal").read_bytes()
        assert smart_bench.openclaw_tool_calls(tmp_path, "") == [("exec", '{"command": "ls"}')]
        assert Path(f"{path}-wal").read_bytes() == wal  # the run's files are left as they were
    finally:
        writer.close()


def test_openclaws_reply_is_its_terminal_reply_not_the_whole_json(tmp_path):
    run = tmp_path / "openclaw-SMART02"
    out = {"payloads": [{"text": "payload text", "mediaUrl": None}],
           "meta": {"toolSummary": {"calls": 1}, "terminalReply": {"disposition": "visible", "text": "The answer."}}}
    Path(f"{run}.stdout").write_text("[gateway] starting\n" + json.dumps(out))
    assert runner.reply_text("openclaw", run) == "The answer."
    del out["meta"]["terminalReply"]
    Path(f"{run}.stdout").write_text(json.dumps(out))
    assert runner.reply_text("openclaw", run) == "payload text"
    Path(f"{run}.stdout").write_text(json.dumps({"payloads": [], "meta": {}}))
    assert runner.reply_text("openclaw", run) == ""                  # never the JSON itself, graded as a reply


@pytest.mark.parametrize("reply, found", [("notetool 的版本是 **3.2.1 (bench)**。", True), ("版本是3.2.1。", True),
                                          ("notetool 3.2.1", True), ("版本是 13.2.1。", False),
                                          ("版本是 3.2.10。", False), ("版本是 3.2.1.4。", False)])
def test_the_version_is_found_however_it_is_written_but_only_whole(reply, found):
    """Every entrant wrote 「版本是 **3.2.1 (bench)**」; the check wanted the literal 'notetool 3.2.1'."""
    assert smart_bench.grade(item(8), reply, [("run_command", "notetool --version")])["found_or_guide"] is found


def test_an_empty_reply_passes_neither_length_nor_no_offer():
    g = smart_bench.grade(item(13), "", [])
    assert g["words"] is False and g["no_offer"] is False and g["pass"] is False


def test_a_call_made_through_dispatch_action_counts_as_its_own_call(tmp_path):
    """OpenClaw records the tool dispatch_action ran as its own event; `meta.toolSummary.calls` counts both."""
    nested = json.dumps({"type": "message", "message": {
        "role": "custom", "customType": "openclaw.nested-tool.v1", "content": "", "details": {
            "parentToolCallId": "c", "toolName": "web_fetch", "input": {"url": "https://example.test/a"},
            "result": {"content": [{"type": "toolCall", "name": "not_a_call_of_this_turn", "arguments": {}}]}}}})
    _openclaw_db(tmp_path, [(_call("dispatch_action", {"id": "web_fetch"}), None), (nested, None)])
    assert smart_bench.openclaw_tool_calls(tmp_path, "") == [("dispatch_action", '{"id": "web_fetch"}'),
                                                             ("web_fetch", '{"url": "https://example.test/a"}')]
