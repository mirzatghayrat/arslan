"""0.1.58 §2–§3: files in Arslan's window — browse, read, stat, open/reveal, tables, a
conversation's files — inside the readable roots only, never hidden or credential files,
never served as a page of Arslan's own origin."""
from __future__ import annotations

import io
import zipfile

import pytest

from server.api import files as files_api
from server.services import file_reader


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = (tmp_path / "ws").resolve()
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "week.md").write_text("# Week\n")
    (root / "b.csv").write_text("name,amount\nA,1\nB,2\n")
    (root / ".hidden").write_text("x")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x")
    (root / ".env").write_text("SECRET=1")
    (root / "id_rsa").write_text("key")
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours")
    (root / "link-out.txt").symlink_to(outside)

    async def roots():
        return [root]
    monkeypatch.setattr(file_reader, "roots", roots)
    opened: list[list[str]] = []

    async def fake_open(args):
        opened.append(args)
    monkeypatch.setattr(files_api, "_open", fake_open)
    return root, outside, opened


async def test_a_folder_lists_folders_first_without_hidden_or_credential_files(client, ws):
    root, _, _ = ws
    body = (await client.get("/api/v1/files/list", params={"path": str(root)})).json()
    names = [e["name"] for e in body["entries"]]
    assert names == ["reports", "b.csv", "link-out.txt"]
    assert body["entries"][0]["is_dir"] is True and body["entries"][1]["bytes"] == 20
    sub = (await client.get("/api/v1/files/list", params={"path": str(root / "reports")})).json()
    assert [c["name"] for c in sub["crumbs"]] == ["ws", "reports"]


async def test_reading_returns_bytes_as_an_attachment_never_a_page(client, ws):
    root, _, _ = ws
    r = await client.get("/api/v1/files/read", params={"path": str(root / "reports" / "week.md")})
    assert r.status_code == 200 and r.content == b"# Week\n"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize("rel,code", [
    ("../outside.txt", 403), ("link-out.txt", 403), (".hidden", 403), (".git/config", 403),
    (".env", 403), ("id_rsa", 403), ("nope.md", 404),
])
async def test_the_boundary(client, ws, rel, code):
    root, _, _ = ws
    r = await client.get("/api/v1/files/read", params={"path": str(root / rel)})
    assert r.status_code == code, (rel, r.text)


async def test_relative_paths_are_refused(client, ws):
    r = await client.get("/api/v1/files/read", params={"path": "reports/week.md"})
    assert r.status_code == 422


async def test_stat_tells_readable_from_merely_existing(client, ws):
    root, outside, _ = ws
    items = (await client.post("/api/v1/files/stat", json={"paths": [
        str(root / "b.csv"), str(outside), str(root / "missing.md"), str(root / ".env")]})).json()["items"]
    assert [(i["exists"], i["readable"]) for i in items] == [(True, True), (True, False), (False, False), (True, False)]


async def test_open_only_inside_the_roots_reveal_anywhere(client, ws):
    root, outside, opened = ws
    assert (await client.post("/api/v1/files/open", json={"path": str(outside)})).status_code == 403
    assert (await client.post("/api/v1/files/open", json={"path": str(root / "b.csv")})).status_code == 200
    assert (await client.post("/api/v1/files/reveal", json={"path": str(outside)})).status_code == 200
    assert opened == [[str(root / "b.csv")], ["-R", str(outside)]]


def _xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<sheets><sheet name="Totals" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<si><t>Supplier</t></si><si><t>Spruce</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>7</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>1</v></c></row></sheetData></worksheet>')
    return buf.getvalue()


async def test_tables_from_csv_and_xlsx(client, ws):
    root, _, _ = ws
    csv_body = (await client.get("/api/v1/files/table", params={"path": str(root / "b.csv")})).json()
    assert csv_body["sheets"][0]["rows"] == [["name", "amount"], ["A", "1"], ["B", "2"]]
    (root / "t.xlsx").write_bytes(_xlsx())
    x = (await client.get("/api/v1/files/table", params={"path": str(root / "t.xlsx")})).json()["sheets"][0]
    assert x["name"] == "Totals" and x["rows"] == [["Supplier", "", "7"], ["Spruce", "", ""]]


def test_a_pdf_page_renders_as_an_image():
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    png, count = file_reader.pdf_page(buf.getvalue(), 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and count == 1
    with pytest.raises(file_reader.NotReadable):
        file_reader.pdf_page(buf.getvalue(), 3)


async def test_the_roots_are_the_read_tools_plus_project_folders_and_artifacts(client, tmp_path, monkeypatch):
    from server.db import session as db_session
    from server.db.companion_models import Project
    from server.services import artifact_store, settings_service
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    ws_dir, proj, arts = tmp_path / "w", tmp_path / "proj", tmp_path / "arts"
    for d in (ws_dir, proj, arts):
        d.mkdir()
    monkeypatch.setattr(artifact_store, "root", lambda: arts)
    async with client.db_maker() as db:
        await settings_service._set_raw(db, "workspace_dir", str(ws_dir))
        await settings_service._set_raw(db, "default_read_enabled", "false")
        db.add(Project(id="p1", name="P", kind="general", workspace_ref=str(proj)))
        db.add(Project(id="p2", name="Old", kind="general", workspace_ref=str(tmp_path), status="archived"))
        await db.commit()
    got = await file_reader.roots()
    assert set(got) == {ws_dir.resolve(), proj.resolve(), arts.resolve()}


async def test_a_conversations_files_one_per_path_newest_first(client, tmp_path, monkeypatch):
    from server.db.models import Run
    from server.services import artifact_store
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "arts")
    async with client.db_maker() as db:
        r1 = Run(conversation_id="c", spawn_name="Arslan", user_message="x", status="recorded", kind="host", task_tokens=0)
        r2 = Run(conversation_id="c", spawn_name="Arslan", user_message="y", status="recorded", kind="host", task_tokens=0)
        other = Run(conversation_id="d", spawn_name="Arslan", user_message="z", status="recorded", kind="host", task_tokens=0)
        db.add_all([r1, r2, other])
        await db.commit()
        ids = (r1.id, r2.id, other.id)
    key = "a" * 64
    artifact_store.store_bytes(ids[0], "report.md", b"v1", logical_key=key)
    artifact_store.store_bytes(ids[1], "report.md", b"v2", logical_key=key)
    artifact_store.store_bytes(ids[1], "table.csv", b"x,y")
    artifact_store.store_bytes(ids[2], "elsewhere.md", b"no")
    files = (await client.get("/api/v1/conversations/c/files")).json()["files"]
    assert sorted(f["title"] for f in files) == ["report.md", "table.csv"]
    assert next(f for f in files if f["title"] == "report.md")["run_id"] == ids[1]   # the last version


async def test_history_rows_carry_each_replys_files(client, tmp_path, monkeypatch):
    """0.1.58 §2: a reloaded reply still shows its file cards."""
    from server.db import session as db_session
    from server.db.models import ArslanMessage, Run
    from server.services import artifact_store
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "arts")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as db:
        run = Run(conversation_id="c", spawn_name="Arslan", user_message="x", status="recorded", kind="host", task_tokens=0)
        db.add(run)
        await db.flush()
        db.add_all([ArslanMessage(conversation_id="c", role="user", content="x"),
                    ArslanMessage(conversation_id="c", role="arslan", content="done", run_id=run.id)])
        await db.commit()
        run_id = run.id
    artifact_store.store_bytes(run_id, "报告/a.md", b"# a")
    from server.ws.arslan import _history
    rows = await _history("c")
    assert "files" not in rows[0]
    assert [f["title"] for f in rows[1]["files"]] == ["报告/a.md"]
