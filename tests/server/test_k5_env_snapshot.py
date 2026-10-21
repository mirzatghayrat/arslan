"""K5: an environment snapshot in the turn's reference block (⓪Plan's Q2: counts only).

The model learns the macOS version, which of the usual command-line tools are installed, and how much
is in the working folder: counts of folders and files, and files by type. It never sees a file or folder
name. Names can be private ("体检报告.pdf"), and the block rides every turn to the model without the
user doing anything; the model calls list_dir when a task needs names. The snapshot is cached per
conversation, so every turn carries the same bytes.
"""
import stat

import pytest

from server.orchestrator import arslan, env_snapshot, turn_context


@pytest.fixture(autouse=True)
def fresh():
    env_snapshot._cache.clear()
    yield
    env_snapshot._cache.clear()


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    for name in ("体检报告.pdf", "secret-plan.md", "notes.md", "draft.MD", "photo.JPG", "archive.tar.gz",
                 "README", "weird.health-2026-report", ".env", ".DS_Store"):
        (root / name).write_text("x")
    (root / "Taxes 2026").mkdir()
    (root / "Clients").mkdir()
    (root / ".hidden-folder").mkdir()
    return root


PRIVATE = ("体检报告", "secret-plan", "notes", "draft", "photo", "archive", "README", "weird", "health",
           "Taxes", "Clients", ".env", "DS_Store", "hidden-folder")


def test_the_working_folder_is_counted_never_named(folder):
    text = env_snapshot.describe(folder, path="")
    for name in PRIVATE:
        assert name not in text, name
    assert "2 folders, 8 files" in text                                  # dot-entries aren't counted
    assert "md 3" in text and "pdf 1" in text and "jpg 1" in text and "gz 1" in text
    assert "other 2" in text                       # no extension, and an extension that is really a name


def test_file_types_are_capped(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.e{i:02d}").write_text("x")
    text = env_snapshot.describe(tmp_path, path="")
    assert text.count(" 1") <= env_snapshot.MAX_TYPES + 1 and f"other {20 - env_snapshot.MAX_TYPES}" in text


def test_the_usual_command_line_tools_found_on_the_path_are_listed(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git", "ffmpeg"):
        exe = bin_dir / tool
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    text = env_snapshot.describe(None, path=str(bin_dir))
    assert "git" in text and "ffmpeg" in text and "pandoc" not in text
    assert "Working folder" not in text                                 # no workspace, no folder line


async def test_every_turn_of_a_conversation_carries_the_same_bytes(folder, monkeypatch):
    async def workspace():
        return folder
    monkeypatch.setattr(env_snapshot, "_workspace", workspace)
    first = await env_snapshot.for_turn("conv-1")
    (folder / "new.md").write_text("x")
    assert await env_snapshot.for_turn("conv-1") == first               # cached: turn 2 is turn 1's bytes
    assert await env_snapshot.for_turn("conv-2") != first               # another conversation counts afresh


async def test_a_failing_snapshot_never_fails_the_turn(monkeypatch):
    async def broken():
        raise OSError("no settings")
    monkeypatch.setattr(env_snapshot, "_workspace", broken)
    assert await env_snapshot.for_turn("conv-1") == ""


def test_the_snapshot_sits_before_the_language_and_the_time(monkeypatch):
    monkeypatch.setattr(arslan, "_now_line", lambda: "\n\nNOW")
    block = arslan._turn_context(facts="FACTS", summary="", kb_block="\n\nKB", mcp_line="\n\nMCP",
                                 environment="\n\nENV", language="\n\nLANG")
    order = [block.index(piece) for piece in ("FACTS", "KB", "MCP", "ENV", "LANG", "NOW")]
    assert order == sorted(order)


async def test_a_chat_turn_carries_it_in_the_turn_context_not_the_system(execution_db, monkeypatch):
    from server.orchestrator import tool_loop

    async def snapshot(conversation_id):
        return "\n\nThis Mac: macOS 99; ENV-MARK"
    monkeypatch.setattr(env_snapshot, "for_turn", snapshot)
    seen = {}

    async def fake_run_native(*, system, user_content, on_chunk, **kw):
        seen.update(system=str(system), user=user_content)
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    await arslan._handle_answer("c-env", "hello", lambda e: None)
    user = seen["user"] if isinstance(seen["user"], str) else seen["user"][0]["text"]
    assert "ENV-MARK" in user and user.startswith(turn_context.OPEN)
    assert "ENV-MARK" not in seen["system"]
