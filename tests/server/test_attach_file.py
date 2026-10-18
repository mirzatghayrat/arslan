"""D1 (docs/plans/0162/D1-deliver-files.md): a file the turn made reaches the user.

attach_file registers an existing file as the run's deliverable: the window shows a file card
and the paired iPhone receives the file. Only what the model attaches is registered, within the
read rules (readable folders, no hidden or credential-shaped names, no link leading out) and the
phone's limits (20 MB a file, 32 files a run). A turn from the iPhone tells the model a Mac path
is no use there.
"""
import os

import pytest

from server.registry import file_tools
from server.services import artifact_store, execution_context, file_reader, phone_reads

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
RUN = 41


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "store")

    async def workspace():
        return root

    async def readable():
        return [root.resolve()]
    monkeypatch.setattr(file_tools, "_workspace_root", workspace)
    monkeypatch.setattr(file_reader, "roots", readable)
    return root


async def attach(args, run=RUN):
    if run is None:
        return await file_tools.AttachFileExecutor().execute(args)
    with execution_context.bind_run(run):
        return await file_tools.AttachFileExecutor().execute(args)


async def test_a_png_a_command_made_becomes_the_runs_file_and_reaches_the_phone(ws):
    (ws / "shot.png").write_bytes(PNG)            # written the way screencapture would, not by write_file
    result = await attach({"path": "shot.png"})
    assert result["ok"] is True and result["artifact"]["media_type"] == "image/png"
    stored = artifact_store.list_artifacts(RUN)
    assert [a["sha256"] for a in stored] == [result["artifact"]["sha256"]]
    files = phone_reads.run_files(RUN)
    assert len(files) == 1 and files[0]["name"] == "shot.png" and files[0]["mime_type"] == "image/png"
    assert (artifact_store.root() / stored[0]["filename"]).read_bytes() == PNG


async def test_an_absolute_or_home_path_works_too(ws):
    (ws / "chart.png").write_bytes(PNG)
    result = await attach({"path": str(ws / "chart.png")})
    assert result["ok"] is True


async def test_a_title_without_an_extension_keeps_the_files(ws):
    (ws / "shot.png").write_bytes(PNG)
    result = await attach({"path": "shot.png", "title": "Mac screen"})
    assert result["ok"] is True
    assert result["artifact"]["title"] == "Mac screen.png" and result["artifact"]["media_type"] == "image/png"


# ── refusals: each one says which rule ──────────────────────────────────────────────

async def test_no_run_is_a_clear_error(ws):
    (ws / "shot.png").write_bytes(PNG)
    result = await attach({"path": "shot.png"}, run=None)
    assert result["ok"] is False and "no run" in result["error"]
    assert artifact_store.list_artifacts(RUN) == []


async def test_a_path_outside_the_readable_folders_is_refused(ws, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.png").write_bytes(PNG)
    result = await attach({"path": str(outside / "x.png")})
    assert result["ok"] is False and "outside" in result["error"]


async def test_a_credential_shaped_name_is_refused(ws):
    (ws / "id_rsa").write_bytes(b"-----BEGIN KEY-----")
    result = await attach({"path": "id_rsa"})
    assert result["ok"] is False and "hidden or credential" in result["error"]


async def test_a_link_leading_out_is_refused(ws, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "private.png").write_bytes(PNG)
    os.symlink(outside / "private.png", ws / "shot.png")
    result = await attach({"path": "shot.png"})
    assert result["ok"] is False and "outside" in result["error"]
    assert artifact_store.list_artifacts(RUN) == []


async def test_a_file_over_twenty_megabytes_is_refused(ws):
    with open(ws / "big.mov", "wb") as f:
        f.truncate(phone_reads.PHONE_FILE_MAX + 1)
    result = await attach({"path": "big.mov"})
    assert result["ok"] is False and "20 MB" in result["error"]
    assert artifact_store.list_artifacts(RUN) == []


async def test_a_run_holding_thirty_two_files_takes_no_more(ws):
    for n in range(artifact_store.MAX_FILES):
        artifact_store.store_bytes(RUN, f"f{n}.txt", b"x")
    (ws / "shot.png").write_bytes(PNG)
    result = await attach({"path": "shot.png"})
    assert result["ok"] is False and "32" in result["error"]
    assert len(artifact_store.list_artifacts(RUN)) == artifact_store.MAX_FILES


async def test_a_folder_is_not_a_file(ws):
    (ws / "pics").mkdir()
    result = await attach({"path": "pics"})
    assert result["ok"] is False and "not a file" in result["error"]


# ── a turn from the iPhone ───────────────────────────────────────────────────────────

from server.orchestrator import arslan, tool_loop  # noqa: E402
from server.services import turn_facts  # noqa: E402
from tests.server.test_arslan_loop import _LLMResp, _events, maker  # noqa: E402,F401


class _Seeing:
    """chat()-based stub that records what the model is shown."""

    def __init__(self):
        self.seen = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.seen.append({"system": system, "user": user, "tools": [t["function"]["name"] for t in tools or []]})
        return _LLMResp(content="ok")


async def _no_facts(conv, msg):
    return []


@pytest.mark.parametrize("source", ["phone", None])
async def test_only_a_phone_turn_tells_the_model_a_mac_path_is_no_use(maker, monkeypatch, source):  # noqa: F811
    model = _Seeing()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    await arslan.handle_user_message("c-d1", "send me a screenshot of my Mac", _events([]), source=source)
    first = model.seen[0]
    assert "attach_file" in first["tools"]
    told = "on their iPhone" in str(first["user"])
    assert told is (source == "phone")
    assert "on their iPhone" not in first["system"]          # never the cached system prompt
