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
