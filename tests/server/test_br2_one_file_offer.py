"""BR2 / M3 #12 (docs/plans/0164/README.md §3.6): a turn offers each file once, its last version.

write_file / edit_file store a snapshot on every write, and attach_file stores the file again.
iPhone build 24 showed one reply offering the same file three times (same name and size,
different ids); the window showed a write and its attachment as two cards. The store keeps every
version; what the window and the phone are offered is one entry per file, the last one stored.
"""
import hashlib
import os
import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.registry import file_tools
from server.services import artifact_store, execution_context, file_reader, phone_reads

RUN = 88
sha = lambda data: hashlib.sha256(data).hexdigest()  # noqa: E731


@pytest_asyncio.fixture
async def ws(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'br2.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    (tmp_path / "home").mkdir()
    monkeypatch.setattr("server.registry.file_tools.Path.home", lambda: tmp_path / "home")
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path / "home")
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "store")
    root = tmp_path / "ws"
    root.mkdir()

    async def readable():
        return [root.resolve()]
    monkeypatch.setattr(file_reader, "roots", readable)
    async with m() as s:
        s.add(Setting(key="workspace_dir", value=str(root)))
        s.add(Setting(key="default_read_enabled", value="false"))
        await s.commit()
    yield root.resolve()
    await engine.dispose()


async def run(*calls):
    with execution_context.bind_run(RUN):
        for executor, args in calls:
            out = await executor().execute(args)
            assert out["ok"] is True, out


W, E, A = file_tools.WriteFileExecutor, file_tools.EditFileExecutor, file_tools.AttachFileExecutor


async def test_three_writes_and_an_attachment_reach_the_phone_and_the_window_once(ws):
    await run((W, {"path": "report.md", "content": "v1"}),
              (E, {"path": "report.md", "old": "v1", "new": "v2"}),
              (W, {"path": "report.md", "content": "v3"}),
              (A, {"path": "report.md", "title": "Weekly report"}))
    assert len(artifact_store.list_artifacts(RUN)) == 4, "every version is kept"
    offered = phone_reads.run_files(RUN)
    assert [(f["name"], f["sha256"]) for f in offered] == [("Weekly report.md", sha(b"v3"))]
    window = artifact_store.artifacts_by_run([RUN])[RUN]
    assert [(f["title"], f["sha256"]) for f in window] == [("Weekly report.md", sha(b"v3"))]


async def test_a_write_after_the_attachment_is_the_version_offered(ws):
    await run((W, {"path": "report.md", "content": "v1"}),
              (A, {"path": "report.md"}),
              (W, {"path": "report.md", "content": "v2"}))
    assert [(f["name"], f["sha256"]) for f in phone_reads.run_files(RUN)] == [("report.md", sha(b"v2"))]


async def test_two_files_stay_two_offers_in_the_order_they_were_finished(ws):
    await run((W, {"path": "a.md", "content": "a1"}),
              (W, {"path": "b.md", "content": "b1"}),
              (W, {"path": "a.md", "content": "a2"}))
    assert [(f["name"], f["sha256"]) for f in phone_reads.run_files(RUN)] == [("b.md", sha(b"b1")), ("a.md", sha(b"a2"))]


def _uuids(monkeypatch, hexes):
    """Filenames carry a random id; make the later versions sort FIRST by name."""
    seq = iter(hexes)
    monkeypatch.setattr(artifact_store.uuid, "uuid4", lambda: uuid.UUID(next(seq)))


def test_the_last_version_is_the_last_stored_not_the_last_by_name(ws, monkeypatch):
    _uuids(monkeypatch, ["f" * 32, "8" * 32, "0" * 32])
    for data in (b"one", b"two", b"three"):
        artifact_store.store_bytes(RUN, "notes.md", data, logical_key="a" * 64)
    stored = artifact_store.list_artifacts(RUN)
    assert [a["sha256"] for a in stored] == [sha(b"one"), sha(b"two"), sha(b"three")]
    assert [a["sha256"] for a in artifact_store.final_versions(stored)] == [sha(b"three")]


def test_a_manifest_from_before_v0164_is_ordered_by_its_file_time(ws, monkeypatch):
    _uuids(monkeypatch, ["f" * 32, "0" * 32])
    first = artifact_store.store_bytes(RUN, "notes.md", b"old", logical_key="b" * 64)
    second = artifact_store.store_bytes(RUN, "notes.md", b"new", logical_key="b" * 64)
    for item, when in ((first, 1_000_000), (second, 2_000_000)):
        manifest = artifact_store.root() / (item["filename"] + ".manifest.json")
        body = manifest.read_text(encoding="utf-8").replace(f', "stored_at_ns": {item["stored_at_ns"]}', "")
        assert "stored_at_ns" not in body
        manifest.write_text(body, encoding="utf-8")
        os.utime(manifest, ns=(when * 10**9, when * 10**9))
    assert [a["sha256"] for a in artifact_store.final_versions(artifact_store.list_artifacts(RUN))] == [sha(b"new")]


def test_an_entry_without_a_key_stands_alone():
    items = [{"filename": "x", "logical_key": None}, {"filename": "y"}, {"filename": "z", "logical_key": "c" * 64},
             {"filename": "w", "logical_key": "c" * 64}]
    assert [i["filename"] for i in artifact_store.final_versions(items)] == ["x", "y", "w"]


# ── ⑤CAP's review of #463 ────────────────────────────────────────────────────
def _three_versions(monkeypatch, clock):
    """Three versions of one file whose random ids sort newest-first by name, under `clock`."""
    _uuids(monkeypatch, ["f" * 32, "8" * 32, "0" * 32])
    monkeypatch.setattr(artifact_store.time, "time_ns", clock)
    stored = [artifact_store.store_bytes(RUN, "notes.md", data, logical_key="e" * 64) for data in (b"one", b"two", b"three")]
    stamps = [item["stored_at_ns"] for item in stored]
    assert stamps == sorted(stamps) and len(set(stamps)) == 3, "strictly increasing"
    return [a["sha256"] for a in artifact_store.final_versions(artifact_store.list_artifacts(RUN))]


def test_versions_stored_in_the_same_clock_tick_keep_their_order(ws, monkeypatch):
    """macOS gives time_ns() in microsecond steps: writes in one tick tied, and a tie fell back to
    the random filename (the earlier version offered in about half of ⑤CAP's probe runs)."""
    assert _three_versions(monkeypatch, lambda: 5 * 10**18) == [sha(b"three")]


def test_a_clock_that_steps_back_does_not_reorder_versions(ws, monkeypatch):
    ticks = iter([6 * 10**18, 6 * 10**18 - 10**12, 6 * 10**18 - 2 * 10**12])   # NTP or the user moves the clock back
    assert _three_versions(monkeypatch, lambda: next(ticks)) == [sha(b"three")]


def test_two_outputs_without_a_path_that_share_a_name_both_stay(ws):
    """A run's exported outputs (run_python files, browser downloads) have no path identity: two
    different files called out.csv are two offers, as before BR2."""
    first = artifact_store.store_bytes(RUN, "out.csv", b"a,b")
    second = artifact_store.store_bytes(RUN, "out.csv", b"c,d")
    assert first["logical_key"] == second["logical_key"]          # the default title key
    assert [f["sha256"] for f in phone_reads.run_files(RUN)] == [sha(b"a,b"), sha(b"c,d")]


def test_history_keeps_the_latest_files_when_a_run_has_more_than_it_shows(ws):
    for name in ("a.md", "b.md", "c.md"):
        artifact_store.store_bytes(RUN, name, name.encode(), logical_key=hashlib.sha256(name.encode()).hexdigest())
    assert [f["title"] for f in artifact_store.artifacts_by_run([RUN], per_run=2)[RUN]] == ["b.md", "c.md"]


def test_two_outputs_with_one_long_name_both_stay(ws):
    """⑤CAP recheck: the stored title is cut at 240 characters; the default key is computed from
    the cut title, so final_versions still recognises it."""
    long = "x" * 300 + ".csv"
    artifact_store.store_bytes(RUN, long, b"a,b")
    artifact_store.store_bytes(RUN, long, b"c,d")
    assert len(artifact_store.final_versions(artifact_store.list_artifacts(RUN))) == 2


def test_a_cap_of_zero_shows_no_files(ws):
    artifact_store.store_bytes(RUN, "a.md", b"a", logical_key="f" * 64)
    assert artifact_store.artifacts_by_run([RUN], per_run=0)[RUN] == []
    assert len(artifact_store.artifacts_by_run([RUN], per_run=None)[RUN]) == 1
