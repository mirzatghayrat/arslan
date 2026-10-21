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

    def __init__(self, replies=None):
        self.seen = []
        self.replies = list(replies or [])

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.seen.append({"system": system, "user": user, "tools": [t["function"]["name"] for t in tools or []],
                          "params": {t["function"]["name"]: t["function"]["parameters"] for t in tools or []}})
        return self.replies.pop(0) if self.replies else _LLMResp(content="ok")


async def _no_facts(conv, msg):
    return []


@pytest.mark.parametrize("source", ["phone", None])
async def test_only_a_phone_turn_tells_the_model_a_mac_path_is_no_use(maker, monkeypatch, source):  # noqa: F811
    model = _Seeing()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    await arslan.handle_user_message("c-d1", "send me a screenshot of my Mac", _events([]), source=source)
    first = model.seen[0]
    assert first["tools"] == sorted(first["tools"])                                        # K3: sorted by name
    # K7: attach_file is reached on demand; the request carries find_tools, and the phone note says so
    assert "find_tools" in first["tools"] and "attach_file" not in first["tools"]
    assert "attach_file" in {t["key"] for t in await arslan._callable_tools()}
    told = "on their iPhone" in str(first["user"])
    assert told is (source == "phone")
    assert ("attach_file (find it with find_tools)" in str(first["user"])) is (source == "phone")
    assert "on their iPhone" not in first["system"]          # never the cached system prompt


# ── review fixes (#217) ──────────────────────────────────────────────────────────────

import asyncio  # noqa: E402
import threading  # noqa: E402

from arslan import execution_budget  # noqa: E402
from server.orchestrator import tool_loop as _tool_loop  # noqa: E402
from server.services import task_service  # noqa: E402


def test_a_fifo_is_refused_without_waiting_for_a_writer(ws):
    # Opening a FIFO for reading blocks until someone writes: the whole event loop would freeze.
    os.mkfifo(ws / "shot.png")
    done: dict = {}
    worker = threading.Thread(target=lambda: done.update(result=asyncio.run(attach({"path": "shot.png"}))),
                              daemon=True)
    worker.start()
    worker.join(timeout=5)
    if worker.is_alive():                                   # release the blocked open, then fail
        os.close(os.open(ws / "shot.png", os.O_WRONLY | os.O_NONBLOCK))
        worker.join(timeout=5)
        pytest.fail("attach_file blocked on a FIFO")
    assert done["result"]["ok"] is False and "not a file" in done["result"]["error"]


@pytest.mark.parametrize("setup,args", [
    (None, {"path": "missing.png"}),
    ("secret", {"path": "id_rsa"}),
    ("big", {"path": "big.mov"}),
])
async def test_every_refusal_says_it_never_ran(ws, setup, args):
    # A refused attach is a known outcome that stayed on this Mac, not "needs your review".
    if setup == "secret":
        (ws / "id_rsa").write_bytes(b"k")
    if setup == "big":
        with open(ws / "big.mov", "wb") as f:
            f.truncate(phone_reads.PHONE_FILE_MAX + 1)
    result = await attach(args)
    assert result["ok"] is False and result["executed"] is False
    assert task_service.known_local_failure("attach_file", args, result)


async def test_no_run_says_it_never_ran(ws):
    result = await attach({"path": "x.png"}, run=None)
    assert result["executed"] is False


async def test_a_file_past_the_turns_artifact_budget_is_refused_and_the_turn_goes_on(ws):
    (ws / "shot.png").write_bytes(PNG)
    budget = execution_budget.Budget(execution_budget.Limits(artifact_bytes=len(PNG) - 1))
    with execution_budget.scope(budget):
        result = await attach({"path": "shot.png"})
    assert result["ok"] is False and result["executed"] is False and "budget" in result["error"]
    assert budget.stop_reason is None and budget.artifact_bytes == 0
    assert artifact_store.list_artifacts(RUN) == []


async def test_arslans_own_data_is_never_attached(ws, monkeypatch):
    from server import config
    data = ws / "arslan-data"
    data.mkdir()
    (data / "arslan.db").write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(config, "data_dir", lambda: data)
    result = await attach({"path": "arslan-data/arslan.db"})
    assert result["ok"] is False and "protected" in result["error"]
    assert artifact_store.list_artifacts(RUN) == []


async def test_a_link_swapped_in_after_the_check_is_not_followed(ws, tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "private.png").write_bytes(PNG)
    os.symlink(outside / "private.png", ws / "shot.png")

    def checked_then_swapped(raw, roots):        # the check saw a file; a link is there now
        return ws / "shot.png", ws.resolve()
    monkeypatch.setattr(file_reader, "resolve", checked_then_swapped)
    result = await attach({"path": "shot.png"})
    assert result["ok"] is False
    assert artifact_store.list_artifacts(RUN) == []


async def test_a_file_that_grew_after_it_was_measured_is_refused(ws, monkeypatch):
    with open(ws / "grows.png", "wb") as f:
        f.truncate(phone_reads.PHONE_FILE_MAX + 1)
    real = os.fstat

    def small(fd):                                # measured while it was still small
        st = real(fd)
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                               10, st.st_atime, st.st_mtime, st.st_ctime))
    monkeypatch.setattr(file_tools.os, "fstat", small)
    result = await attach({"path": "grows.png"})
    monkeypatch.setattr(file_tools.os, "fstat", real)
    assert result["ok"] is False and "20 MB" in result["error"]
    assert artifact_store.list_artifacts(RUN) == []


async def test_attach_file_is_a_local_write():
    assert await task_service.effect_of("attach_file", {"path": "shot.png"}) == "local_write"


def test_attach_file_has_its_own_parameter_schema():
    params = _tool_loop._tool_params({"key": "attach_file"})
    assert params["required"] == ["path"] and set(params["properties"]) == {"path", "title"}


async def test_a_multi_part_extension_is_kept(ws):
    (ws / "backup.tar.gz").write_bytes(b"x")
    result = await attach({"path": "backup.tar.gz", "title": "backup"})
    assert result["artifact"]["title"] == "backup.tar.gz"


async def test_the_phone_line_stays_on_every_step(maker, monkeypatch):  # noqa: F811
    plan = _LLMResp(tool_calls=[{"id": "c1", "type": "function", "function": {
        "name": "update_plan", "arguments": {"items": [{"text": "find the file", "status": "in_progress"}]}}}])
    model = _Seeing([plan, _LLMResp(content="ok")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    await arslan.handle_user_message("c-d1b", "send me the report", _events([]), source="phone")
    assert len(model.seen) >= 2 and all("on their iPhone" in str(step["user"]) for step in model.seen)
