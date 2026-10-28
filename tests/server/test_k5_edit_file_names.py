"""K5: edit_file takes old_string / new_string, like the other agents' edit tools (card K5, ⓪Plan's Q7).

The old `old` / `new` worked for one version (v0.1.63) and are gone in v0.1.64 (C5b, the DELETE-BY the
card set): the executor refuses them, the schema requires the new names, and the window's edit view and
the phone's review read only the new names. Their output keys stay the same, so the phone sees nothing new.
"""
from server.orchestrator import tool_loop
from server.registry import file_tools
from server.services import run_process, tool_review
from tests.server.test_file_tools import ws  # noqa: F401 — the workspace fixture


async def test_the_new_names_edit_the_file(ws):  # noqa: F811
    out = await file_tools.EditFileExecutor().execute(
        {"path": "notes.md", "old_string": "second line", "new_string": "SECOND LINE"})
    assert out["ok"] is True and "SECOND LINE" in (ws / "notes.md").read_text()


async def test_the_old_names_no_longer_edit_the_file(ws):  # noqa: F811
    before = (ws / "notes.md").read_text()
    out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "old": "second line", "new": "2nd"})
    assert out["ok"] is False and "old_string" in out["error"]
    assert (ws / "notes.md").read_text() == before


async def test_a_missing_old_string_is_named_in_the_new_words(ws):  # noqa: F811
    out = await file_tools.EditFileExecutor().execute({"path": "notes.md", "new_string": "x"})
    assert out["ok"] is False and "old_string" in out["error"]


def test_the_schema_requires_the_new_names_and_stops_an_old_call():
    schema = tool_loop._NATIVE_PARAM_SCHEMAS["edit_file"]
    assert {"old_string", "new_string"} <= set(schema["properties"]) and "old" not in schema["properties"]
    assert set(schema["required"]) == {"path", "old_string", "new_string"}
    assert tool_loop._schema_problem({"path": "a.md", "old": "x", "new": "y"}, schema) is not None
    assert tool_loop._schema_problem({"path": "a.md", "old_string": "x", "new_string": "y"}, schema) is None


def test_the_edit_view_and_the_phone_review_read_the_new_names():
    args = {"path": "a.md", "old_string": "before", "new_string": "after"}
    view = run_process.plain("edit_file", args, {"ok": True, "path": "a.md"}, ok=True)
    review = tool_review.capture("edit_file", args, {"ok": True, "path": "a.md"})
    assert (view["old"], view["new"]) == ("before", "after")
    assert (review["old"], review["new"]) == ("before", "after")
    old = {"path": "a.md", "old": "before", "new": "after"}
    assert (run_process.plain("edit_file", old, {"ok": True, "path": "a.md"}, ok=True)["old"],
            tool_review.capture("edit_file", old, {"ok": True, "path": "a.md"})["old"]) == ("", "")


def test_the_package_has_no_version_string_of_its_own():
    """The app version lives only in desktop/src-tauri/tauri.conf.json (C5b, v0.1.63); the
    package's leftover `__version__` (read only by the deleted command line) is gone (R63's deadline)."""
    import arslan
    assert not hasattr(arslan, "__version__")
