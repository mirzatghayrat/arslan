"""K5: edit_file takes old_string / new_string, like the other agents' edit tools (card K5, ⓪Plan's Q7).

The schema shows only the new names. The old `old` / `new` still work until v0.1.64 (DELETE-BY: v0.1.64):
in the executor, and in the two places that show an edit afterwards, the window's edit view and the
phone's review. Their output keys stay the same, so the phone sees nothing new.
"""
from server.orchestrator import tool_loop
from server.registry import file_tools
from server.services import run_process, tool_review
from tests.server.test_file_tools import ws  # noqa: F401 — the workspace fixture


async def test_the_new_names_edit_the_file(ws):  # noqa: F811
    out = await file_tools.EditFileExecutor().execute(
        {"path": "notes.md", "old_string": "second line", "new_string": "SECOND LINE"})
    assert out["ok"] is True and "SECOND LINE" in (ws / "notes.md").read_text()


async def test_the_old_names_still_edit_the_file(ws):  # noqa: F811
    out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "old": "second line", "new": "2nd"})
    assert out["ok"] is True and "2nd" in (ws / "notes.md").read_text()


async def test_a_missing_old_string_is_named_in_the_new_words(ws):  # noqa: F811
    out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "new_string": "x"})
    assert out["ok"] is False and "old_string" in out["error"]


def test_the_schema_shows_only_the_new_names_and_lets_an_old_call_through():
    schema = tool_loop._NATIVE_PARAM_SCHEMAS["edit_file"]
    assert {"old_string", "new_string"} <= set(schema["properties"]) and "old" not in schema["properties"]
    assert tool_loop._schema_problem({"path": "a.md", "old": "x", "new": "y"}, schema) is None


def test_the_edit_view_and_the_phone_review_read_either_name():
    for args in ({"path": "a.md", "old_string": "before", "new_string": "after"},
                 {"path": "a.md", "old": "before", "new": "after"}):
        view = run_process.plain("edit_file", args, {"ok": True, "path": "a.md"}, ok=True)
        review = tool_review.capture("edit_file", args, {"ok": True, "path": "a.md"})
        assert (view["old"], view["new"]) == ("before", "after"), args
        assert (review["old"], review["new"]) == ("before", "after"), args
