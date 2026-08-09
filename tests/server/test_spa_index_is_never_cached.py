"""The SPA entry point must not be cached; its hashed assets must be.

🔴 FOUND ON A REAL UPGRADE, not in a test. After installing v0.1.20 over an existing
copy, the Settings screen still showed v0.1.19's text — while the provider dropdown
showed the NEW options. That split is the signature: the dropdown comes from a live
API call, the labels are baked into the JS bundle. WebKit had 48 copies of old
bundles in ~/Library/Caches/com.arslan.desktop/WebKit/NetworkCache, and the shipped
bundle contained the new strings zero times in the cache.

WHY CONTENT HASHING DID NOT SAVE US. Assets are named index-<hash>.js precisely so
they can be cached forever. That is correct and stays. But `index.html` — the file
that says WHICH hash to load — was served by FastAPI's FileResponse with etag and
last-modified and no Cache-Control, so WebKit cached it heuristically. A cached
index.html points at the old hash, the old hash is also in the cache, and the entire
previous frontend keeps running. Quitting the app does not help: the cache is on disk.

WHY IT MATTERED MORE THAN STALE COPY. The old frontend has no CryptoHealthNotice
component at all. An upgrading user whose stored keys had actually broken would see
NOTHING — the same silence spec ⓪ was written to end, for exactly the population it
was written for.

So: entry point no-store, hashed assets left cacheable. Both halves are asserted,
because making everything no-store would throw away the caching that hashed filenames
exist to enable.
"""
from __future__ import annotations

import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """The real app, serving a static dir shaped like a built frontend."""
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><script src="/assets/index-DEADBEEF.js"></script>')
    (static / "assets" / "index-DEADBEEF.js").write_text("console.log('bundle')")
    # A root-level static file. This one matters: /assets/* is served by a StaticFiles
    # MOUNT that the SPA fallback never sees, so asserting on it proves nothing about
    # the code under test — a blanket-no-store mutation sailed past the first version
    # of this file for exactly that reason. favicon.svg goes through the fallback,
    # like every real root asset in the built tree.
    (static / "favicon.svg").write_text("<svg/>")

    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(static))
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "t.db"))
    import server.config as config

    importlib.reload(config)
    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _no_store(resp) -> bool:
    return "no-store" in resp.headers.get("cache-control", "").lower()


class TestTheEntryPointIsNeverCached:
    async def test_the_root_says_no_store(self, client):
        resp = await client.get("/")

        assert resp.status_code == 200
        assert _no_store(resp), resp.headers.get("cache-control")

    async def test_a_deep_link_says_no_store_too(self, client):
        # Every SPA route falls back to index.html, so every one of them is an entry
        # point. Caching /settings would strand a user on the old bundle just as
        # surely as caching /.
        resp = await client.get("/settings")

        assert resp.status_code == 200
        assert _no_store(resp), resp.headers.get("cache-control")

    async def test_index_html_by_name_says_no_store(self, client):
        resp = await client.get("/index.html")

        assert _no_store(resp), resp.headers.get("cache-control")


class TestHashedAssetsStayCacheable:
    async def test_a_root_static_file_through_the_fallback_is_not_no_store(self, client):
        # THE other half, and it has to go through the fallback to mean anything.
        # Blanket no-store would re-fetch every icon on every launch and call that a
        # fix; this is the assertion that fails when someone reaches for that.
        resp = await client.get("/favicon.svg")

        assert resp.status_code == 200
        assert not _no_store(resp), resp.headers.get("cache-control")

    async def test_the_assets_mount_is_untouched(self, client):
        # Recorded rather than assumed: /assets/* is served by a StaticFiles MOUNT,
        # not by the fallback, so this passes no matter what the fallback does. Kept
        # as documentation of the boundary, not as a guard.
        resp = await client.get("/assets/index-DEADBEEF.js")

        assert resp.status_code == 200


class TestTheRealBuiltIndexWouldBeCoveredToo:
    @pytest.mark.parametrize("path", ["/", "/settings", "/chat/123", "/index.html"])
    async def test_every_html_entry_path_is_no_store(self, client, path):
        # Parametrized over the shapes a user can actually land on, rather than one
        # example: the defect was that ONE uncached-by-nobody path pinned an entire
        # frontend generation in place.
        resp = await client.get(path)

        assert _no_store(resp), f"{path}: {resp.headers.get('cache-control')}"
