"""REST API tests for POST /extract — ephemeral text extraction endpoint."""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.db.models import Base

import server.api.extract as eapi


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Async HTTP client backed by an in-memory SQLite DB."""
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "kb.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.db_maker = maker  # type: ignore[attr-defined]
        yield c
    await engine.dispose()


async def test_extract_url_endpoint(client, monkeypatch):
    async def fake_extract_text(*, filename=None, data=None, url=None, compress=False):
        return ("extracted web content", False)

    monkeypatch.setattr(eapi.extract, "extract_text", fake_extract_text)
    r = await client.post("/api/v1/extract", json={"url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "extracted web content"
    assert body["truncated"] is False
    assert body["chars"] == len("extracted web content")


async def test_extract_url_private_400(client):
    """End-to-end SSRF rejection: no stub — real executor path must return 400."""
    r = await client.post(
        "/api/v1/extract",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert r.status_code == 400


async def test_extract_file_upload(client, monkeypatch):
    async def fake_extract_text(*, filename=None, data=None, url=None, compress=False):
        return (data.decode("utf-8", errors="replace"), False)

    monkeypatch.setattr(eapi.extract, "extract_text", fake_extract_text)
    files = {"file": ("notes.txt", b"hello attachment", "text/plain")}
    r = await client.post("/api/v1/extract", files=files)
    assert r.status_code == 200
    assert r.json()["text"] == "hello attachment"


async def test_extract_image_upload_ocr(client, monkeypatch):
    """End-to-end image path: real extract_text/_extract_file, OCR stubbed."""
    import io

    import pytesseract
    from PIL import Image, ImageDraw

    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, **kw: "receipt total 42")
    img = Image.new("RGB", (120, 40), "white")
    ImageDraw.Draw(img).text((4, 12), "42", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    files = {"file": ("receipt.png", buf.getvalue(), "image/png")}
    r = await client.post("/api/v1/extract", files=files)
    assert r.status_code == 200
    assert r.json()["text"] == "receipt total 42"


async def test_extract_image_upload_no_text_200(client, monkeypatch):
    """OCR failure is best-effort: 200 with empty text, never a 500."""
    import pytesseract

    def _boom(img, **kw):
        raise RuntimeError("no tesseract")

    monkeypatch.setattr(pytesseract, "image_to_string", _boom)
    files = {"file": ("shot.png", b"\x89PNG not really", "image/png")}
    r = await client.post("/api/v1/extract", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == ""
    assert body["chars"] == 0


async def test_extract_missing_body_400(client):
    r = await client.post("/api/v1/extract", json={})
    assert r.status_code == 400


async def test_extract_file_missing_field_400(client):
    # multipart without 'file' field
    r = await client.post(
        "/api/v1/extract",
        content=b"--boundary\r\nContent-Disposition: form-data; name=\"other\"\r\n\r\nvalue\r\n--boundary--\r\n",
        headers={"content-type": "multipart/form-data; boundary=boundary"},
    )
    assert r.status_code == 400
