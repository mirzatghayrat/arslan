"""0.1.49 S9: long tool output is never silently cut — head and tail in
context, the full text saved locally, and read_file can page through it."""
import json
import os
import stat
import time

import pytest

from server.orchestrator import tool_loop
from server.registry import file_tools
from server.services import terminal_exec, tool_outputs
from tests.server.test_file_tools import ws  # noqa: F401 — fixture


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))


def test_saved_copy_is_private_local_and_pruned(tmp_path):
    old = tool_outputs.outputs_dir(create=True) / "old.txt"
    old.write_text("stale")
    week_ago = time.time() - 8 * 86400
    os.utime(old, (week_ago, week_ago))
    path = tool_outputs.save("full text", label="web/search ../x")
    assert path.parent == (tmp_path / "data" / "tool_outputs").resolve()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.read_text() == "full text"
    assert "/" not in path.name.replace(path.suffix, "") and ".." not in path.name
    assert not old.exists()


def test_excerpt_keeps_head_tail_and_names_the_copy(tmp_path):
    text = "H" * 7000 + "MIDDLE" + "T" * 2000
    out = tool_outputs.excerpt(text, tmp_path / "f.txt")
    assert out.startswith("H" * 6000) and out.endswith("T" * 1500) and "MIDDLE" not in out
    assert "characters omitted" in out and str(tmp_path / "f.txt") in out and "read_file" in out
    assert tool_outputs.excerpt("short", None) == "short"
    assert "could not be saved" in tool_outputs.excerpt(text, None)


def test_long_result_is_saved_whole_and_the_model_is_told_where():
    convo, trace = [], []
    rows = [{"i": i, "text": f"row {i}"} for i in range(2000)]
    result = {"ok": True, "external": False, "rows": rows}
    tool_loop._record_tool_result("query_db", {}, result, lambda e: None, trace, "{}", convo)
    content = convo[-1]["content"]
    assert len(content) < 9000 and "characters omitted" in content
    saved = content.split("saved to ", 1)[1].split(";", 1)[0]
    assert json.loads(open(saved).read())["rows"] == rows        # the middle is on disk
    assert trace[-1]["result"]["rows"] == rows                    # the trace keeps everything


def test_a_failed_save_still_says_something_was_omitted(monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(tool_outputs, "save", broken)
    convo = []
    tool_loop._record_tool_result("t", {}, {"ok": True, "external": False, "blob": "x" * 20000},
                                  lambda e: None, [], "{}", convo)
    assert "could not be saved" in convo[-1]["content"]


async def test_read_file_pages_a_saved_output_without_widening_other_reads(ws):  # noqa: F811
    path = tool_outputs.save("".join(f"line {i}\n" for i in range(100)), label="command")
    page = await file_tools.ReadFileExecutor().execute({"path": str(path), "offset": 10, "limit": 3})
    assert page["ok"] and page["content"] == "line 10\nline 11\nline 12\n"
    assert page["total_lines"] == 100 and page["truncated"] is True
    for bad_args in ({"offset": -1}, {"limit": 0}, {"limit": "3"}):
        bad = await file_tools.ReadFileExecutor().execute({"path": str(path), **bad_args})
        assert not bad["ok"], bad_args
    outside = await file_tools.ReadFileExecutor().execute({"path": str(path.parent.parent / "arslan.db")})
    assert not outside["ok"]                                      # only the outputs folder was added
    listing = await file_tools.ListDirExecutor().execute({})
    assert "tool_outputs" not in json.dumps(listing)              # readable, not listable


def test_read_file_schema_offers_paging():
    schema = tool_loop._NATIVE_PARAM_SCHEMAS["read_file"]
    assert {"offset", "limit"} <= set(schema["properties"])
    assert tool_loop._schema_problem({"path": "a", "offset": "10"}, schema) == "'offset' must be integer"


async def test_long_command_output_is_saved_with_its_middle(tmp_path):
    script = "python3 -c \"print('A'*20000); print('MIDDLE-MARK'); print('Z'*20000)\""
    result = await terminal_exec.run(script, cwd=tmp_path)
    assert result["truncated"] and "MIDDLE-MARK" not in result["stdout"]
    full = open(result["full_output_path"]).read()
    assert "MIDDLE-MARK" in full and full.startswith("$ python3")
