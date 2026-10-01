"""0.1.48 task panel: the working folder's recent files, and open / reveal confined to it."""
import os
from pathlib import Path

import pytest

from server.api import workspace as ws_api
from tests.server.test_proactive_api import client  # noqa: F401 — token-protected app client


@pytest.fixture
def folder():
    root = Path(os.environ["ARSLAN_DEFAULT_WORKSPACE"])
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def opened(monkeypatch):
    calls = []

    async def _open(args):
        calls.append(args)
    monkeypatch.setattr(ws_api, "_open", _open)
    return calls


async def test_lists_recent_files_newest_first_and_skips_hidden(client, folder):  # noqa: F811
    (folder / "old.md").write_text("a")
    os.utime(folder / "old.md", (1_000_000, 1_000_000))
    (folder / "out").mkdir()
    (folder / "out" / "report.md").write_text("b")
    (folder / ".secret").write_text("c")
    (folder / ".cache").mkdir()
    (folder / ".cache" / "x.txt").write_text("d")
    body = (await client.get("/api/v1/workspace")).json()
    assert body["is_default"] is True and Path(body["path"]) == folder.resolve()
    assert [f["path"] for f in body["recent"]] == ["out/report.md", "old.md"]


async def test_open_and_reveal_stay_inside_the_folder(client, folder, opened, tmp_path):  # noqa: F811
    (folder / "report.md").write_text("x")
    outside = tmp_path / "private.txt"
    outside.write_text("no")
    (folder / "link.txt").symlink_to(outside)
    assert (await client.post("/api/v1/workspace/open", json={"path": "report.md"})).status_code == 200
    for bad in ("../private.txt", str(outside), "link.txt", "missing.md", "."):
        r = await client.post("/api/v1/workspace/open", json={"path": bad})
        assert r.status_code == 404 and r.json()["detail"] == {"code": "not_in_workspace"}, bad
    assert (await client.post("/api/v1/workspace/reveal", json={"path": "report.md"})).status_code == 200
    assert (await client.post("/api/v1/workspace/reveal")).status_code == 200
    assert opened == [[str((folder / "report.md").resolve())], ["-R", str((folder / "report.md").resolve())],
                      [str(folder.resolve())]]


async def test_everything_needs_the_token(client):  # noqa: F811
    from httpx import AsyncClient
    async with AsyncClient(transport=client._transport, base_url="http://test") as anon:
        for method, path in (("get", "/api/v1/workspace"), ("post", "/api/v1/workspace/open"),
                             ("post", "/api/v1/workspace/reveal")):
            r = await getattr(anon, method)(path)
            assert r.status_code in (401, 403), path


def test_the_scan_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api, "SCAN_LIMIT", 5)
    for n in range(20):
        (tmp_path / f"f{n}.txt").write_text("x")
    assert len(ws_api.recent_files(tmp_path)) <= 5
