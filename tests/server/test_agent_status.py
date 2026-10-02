"""<agent_status> (0.1.50 P2 S1): the pure pieces. Request-body behaviour is in
test_agent_status_requests.py."""
import os
import time
from pathlib import Path

from server.orchestrator import agent_status as st

BASE = dict(workspace=None, writers=[], own_folder=True, saved=[], plan="", tool_calls=0,
            model_calls=0, wrap_up_at=None, notes=[])


def _render(**kw):
    return st.render(**{**BASE, **kw})


def test_nothing_to_say_renders_nothing():
    assert _render() == ""


def test_own_folder_says_no_asking_and_names_only_wired_writers():
    out = _render(workspace="~/Arslan", writers=["write_file", "run_command"])
    assert out.startswith(st.OPEN) and out.endswith(st.CLOSE)
    assert "~/Arslan" in out and "without asking (write_file, run_command)" in out
    assert "edit_file" not in out


def test_a_chosen_folder_says_writes_are_approved_once():
    out = _render(workspace="~/proj", writers=["write_file", "edit_file"], own_folder=False)
    assert "approves writes once per session" in out and "without asking" not in out


def test_no_writers_means_no_workspace_line():
    """A workspace the model cannot write to is not a capability: no line."""
    assert _render(workspace="~/Arslan", writers=[]) == ""


def test_saved_plan_counts_and_notes_each_get_a_line():
    out = _render(saved=["a.md", "b.csv"], plan="[x] a  [ ] b", tool_calls=9, model_calls=7,
                  wrap_up_at=24, notes=["Tool budget exhausted. Text only.", "  "])
    lines = out.splitlines()[1:-1]
    assert lines == ["Saved this turn: a.md, b.csv", "Plan (your list): [x] a  [ ] b",
                     "Work so far: 9 tool calls (wrap-up at 24), 7 model calls.",
                     "Tool budget exhausted. Text only."]


def test_counts_are_omitted_before_any_work():
    assert "Work so far" not in _render(workspace="~/A", writers=["write_file"])
    assert "Work so far: 0 tool calls, 1 model call." in _render(model_calls=1)


def test_home_relative_hides_the_account_name():
    home = str(Path.home())
    assert st.home_relative(Path(home) / "Arslan") == "~/Arslan"
    assert st.home_relative(home) == "~"
    assert st.home_relative(home + "-other/x") == home + "-other/x"      # prefix, not a child
    assert st.home_relative("/tmp/ws") == "/tmp/ws"


def test_saved_by_tools_keeps_successful_writes_once_newest_last():
    trace = [{"tool": "write_file", "args": {}, "result": {"ok": True, "path": "a.md"}},
             {"tool": "write_file", "args": {}, "result": {"ok": False, "error": "x"}},
             {"tool": "edit_file", "args": {}, "result": {"ok": True, "path": "b.md"}},
             {"tool": "web_search", "args": {}, "result": {"ok": True, "path": "nope"}},
             {"tool": "write_file", "args": {}, "result": {"ok": True, "path": "a.md"}}]
    assert st.saved_by_tools(trace) == ["b.md", "a.md"]


def test_recent_files_finds_new_files_and_skips_old_hidden_and_deps(tmp_path):
    old = tmp_path / "old.txt"
    old.write_text("x")
    os.utime(old, (1, 1))
    since = time.time() - 5
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "table.csv").write_text("x")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")
    assert st.recent_files(tmp_path, since) == [os.path.join("out", "table.csv")]


def test_recent_files_is_bounded(tmp_path):
    for i in range(50):
        (tmp_path / f"f{i}.txt").write_text("x")
    assert len(st.recent_files(tmp_path, 0, max_entries=10)) < 10


def test_owned_outputs_scans_only_after_a_successful_command(tmp_path):
    since = time.time() - 5
    (tmp_path / "made.csv").write_text("x")
    write = {"tool": "write_file", "args": {}, "result": {"ok": True, "path": "r.md"}}
    cmd_ok = {"tool": "run_command", "args": {}, "result": {"ok": True}}
    cmd_bad = {"tool": "run_command", "args": {}, "result": {"ok": False}}
    assert st.owned_outputs([write], tmp_path, since) == ["r.md"]
    assert st.owned_outputs([write, cmd_bad], tmp_path, since) == ["r.md"]
    assert st.owned_outputs([write, cmd_ok], tmp_path, since) == ["r.md", "made.csv"]
    names = [{"tool": "write_file", "args": {}, "result": {"ok": True, "path": f"{i}.md"}} for i in range(15)]
    assert st.owned_outputs(names, None, since) == [f"{i}.md" for i in range(5, 15)]


def test_attach_appends_to_the_last_message_without_mutating_it():
    convo = [{"role": "user", "content": "q"},
             {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
             {"role": "tool", "tool_call_id": "c1", "content": "result"}]
    out = st.attach(convo, "<s>")
    assert out[-1] == {"role": "tool", "tool_call_id": "c1", "content": "result\n\n<s>"}
    assert convo[-1]["content"] == "result" and out[:-1] == convo[:-1]
    assert len(out) == len(convo)                      # never a new user turn


def test_attach_to_a_user_turn_and_to_parts():
    assert st.attach([{"role": "user", "content": "q"}], "<s>")[-1]["content"] == "q\n\n<s>"
    parts = st.attach([{"role": "user", "content": [{"type": "text", "text": "q"}]}], "<s>")
    assert parts[-1]["content"][-1] == {"type": "text", "text": "<s>"} and len(parts) == 1


def test_attach_nothing_is_identity():
    convo = [{"role": "user", "content": "q"}]
    assert st.attach(convo, "") is convo and st.attach([], "<s>") == []
