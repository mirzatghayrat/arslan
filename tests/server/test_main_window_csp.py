"""IMG1-B (v0.1.64): the main window's Content-Security-Policy, and the island's.

The main window loads the SPA from the sidecar over http://127.0.0.1:<port> (desktop/src-tauri/src/lib.rs,
`WebviewUrl::External`), so Tauri's `security.csp` never reaches it: the header on the entry-page response is the
only policy the page gets. These pin it exactly, as a parsed directive set, on every way the window can land on
index.html: by name, and through the SPA fallback. The notch island's page (island.html, desktop/src-tauri/src/
island.rs) comes from the same sidecar the same way and gets its own, narrower policy. The splash is on Tauri's own
protocol; its policy is a <meta> in the file (web/src/__tests__/splash-csp.test.ts). Card:
docs/plans/0164/IMG1-remote-images.md (option B).
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parents[2]
PORT = 47317  # packaging/server_entry.py DEFAULT_PORT; the fallback port is ephemeral, see the port test

# Every way the window reaches index.html. "/" is what the shell loads; the rest are deep links, a missing file and a
# traversal attempt, which all fall back to it, and the file by name.
ENTRY_PATHS = ["/", "/index.html", "/settings", "/chat/thread-1", "/no-such-file.js", "/%2e%2e/secret.txt"]


def expected(port: int) -> dict[str, frozenset[str]]:
    return {
        "default-src": frozenset({"'self'"}),
        "script-src": frozenset({"'self'"}),
        "style-src": frozenset({"'self'", "'unsafe-inline'"}),
        "img-src": frozenset({"'self'", "data:", "blob:"}),
        "font-src": frozenset({"'self'"}),
        "connect-src": frozenset({"'self'", f"ws://127.0.0.1:{port}", f"ws://localhost:{port}",
                                  "ipc:", "http://ipc.localhost"}),
        "media-src": frozenset({"blob:"}),
        "frame-src": frozenset({"blob:"}),
        "worker-src": frozenset({"'self'"}),
        "object-src": frozenset({"'none'"}),
        "base-uri": frozenset({"'none'"}),
        "form-action": frozenset({"'none'"}),
        # Not 'none': WebKit gives the reader's blob: PDF document this policy, and 'none' blanked it.
        "frame-ancestors": frozenset({"'self'"}),
    }


def parse(policy: str) -> dict[str, frozenset[str]]:
    """A policy as a browser reads it: `;`-separated directives, names case-insensitive, sources split on whitespace.
    A repeated directive fails here: a browser ignores every copy after the first, so a second one only hides which
    sources apply."""
    directives: dict[str, frozenset[str]] = {}
    for part in policy.split(";"):
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].lower()
        assert name not in directives, f"{name} appears twice in {policy!r}"
        directives[name] = frozenset(tokens[1:])
    return directives


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    """The real app, serving a static dir shaped like the built frontend."""
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><title>Arslan</title><div id="boot-veil"></div><script src="/boot-veil.js?v=1"></script>'
        '<div id="root"></div><script type="module" src="/assets/index-DEADBEEF.js"></script>')
    (static / "assets" / "index-DEADBEEF.js").write_text("console.log('bundle')")
    (static / "island.html").write_text('<!doctype html><title>Arslan Island</title>')
    (tmp_path / "secret.txt").write_text("TOPSECRET")  # one level above the static dir, for the traversal path

    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(static))
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "t.db"))
    import server.config as config

    importlib.reload(config)
    from server.main import create_app

    return create_app()


def client(app, port: int = PORT) -> AsyncClient:
    # httpx's ASGI transport fills scope["server"] from the URL, the way uvicorn fills it from the listening socket.
    return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://127.0.0.1:{port}")


@pytest.mark.parametrize("path", ENTRY_PATHS)
async def test_every_entry_path_carries_exactly_the_main_window_policy(app, path):
    async with client(app) as c:
        resp = await c.get(path)

    assert resp.status_code == 200 and "<title>Arslan</title>" in resp.text, path
    assert parse(resp.headers["content-security-policy"]) == expected(PORT), path


@pytest.mark.parametrize("path", ENTRY_PATHS)
async def test_no_entry_path_serves_an_empty_or_missing_policy(app, path):
    async with client(app) as c:
        resp = await c.get(path)

    policies = resp.headers.get_list("content-security-policy")
    assert len(policies) == 1 and policies[0].strip(), f"{path}: {policies}"
    # Report-only would log a violation and load the image anyway.
    assert "content-security-policy-report-only" not in resp.headers, path


async def test_index_html_gets_the_policy_under_any_name_that_reaches_it(app, tmp_path):
    # A Mac's disk ignores case, so /INDEX.HTML is index.html itself; matched by spelling, it went out with no policy
    # and no no-store. A hard link is the same file under another name on any disk, so it pins the check on CI's
    # case-sensitive Linux too, where /INDEX.HTML is simply the fallback.
    os.link(tmp_path / "web" / "index.html", tmp_path / "web" / "alias.html")
    async with client(app) as c:
        for path in ("/INDEX.HTML", "/Index.html", "/alias.html"):
            resp = await c.get(path)

            assert "<title>Arslan</title>" in resp.text, path
            assert parse(resp.headers.get("content-security-policy", "")) == expected(PORT), path


async def test_the_websocket_port_is_the_listening_sockets_not_the_host_headers(app):
    # 51234 stands for the ephemeral port choose_port() falls back to when 47317 is taken. The Host header is the
    # client's to write; the policy must name the port the page was really served from.
    async with client(app, port=51234) as c:
        resp = await c.get("/", headers={"Host": "127.0.0.1:9999"})

    connect = parse(resp.headers["content-security-policy"])["connect-src"]
    assert {"ws://127.0.0.1:51234", "ws://localhost:51234"} <= connect
    assert not any("9999" in source for source in connect), connect


# Every header a proxy-aware reading of the port could take it from, each naming a different hostile port, so a leak
# says which header it came through.
FORWARDED_SPOOF = {
    "Host": "127.0.0.1:9991",
    "X-Forwarded-Port": "9992",
    "X-Forwarded-Host": "127.0.0.1:9993",
    "X-Forwarded-Proto": "wss",
    "Forwarded": 'for=127.0.0.1;host="127.0.0.1:9994";proto=https',
}


@pytest.mark.parametrize("path", ["/", "/index.html", "/settings"])
async def test_no_forwarded_header_can_set_the_websocket_port(app, path):
    # The sidecar has no proxy in front of it, so nothing a client writes may move the port: not Host, and not the
    # X-Forwarded-* or Forwarded headers a proxy-aware reading would take first. The whole policy must equal the one
    # for the socket's port, so a spoofed port, host or scheme can't appear anywhere in it.
    async with client(app, port=51234) as c:
        resp = await c.get(path, headers=FORWARDED_SPOOF)

    assert parse(resp.headers["content-security-policy"]) == expected(51234), path
    policy = resp.headers["content-security-policy"]
    for leaked in ("9991", "9992", "9993", "9994", "wss:", "https:"):
        assert leaked not in policy, (leaked, policy)


# The island (0.1.51): the notch window's own entry page, served by the same sidecar. It renders model text only as
# React text nodes and one data: thumbnail, so this is defence in depth. Narrowed to what it loads (measured on the
# built page): its bundle, its chunks and its stylesheet from the sidecar; fetch to /api/v1 on the same origin; a
# data: JPEG thumbnail; and Tauri's IPC (island_shape, island_open_conversation, event listen). No WebSocket, so no
# port; no inline script or style; no font, media, worker or frame.
ISLAND_EXPECTED = {
    "default-src": frozenset({"'none'"}),
    "script-src": frozenset({"'self'"}),
    "style-src": frozenset({"'self'"}),
    "img-src": frozenset({"data:"}),
    "connect-src": frozenset({"'self'", "ipc:", "http://ipc.localhost"}),
    "base-uri": frozenset({"'none'"}),
    "form-action": frozenset({"'none'"}),
    "frame-ancestors": frozenset({"'none'"}),
}


async def test_the_island_page_carries_exactly_its_own_policy(app):
    async with client(app) as c:
        resp = await c.get("/island.html")

    assert resp.status_code == 200 and "<title>Arslan Island</title>" in resp.text
    policies = resp.headers.get_list("content-security-policy")
    assert len(policies) == 1, policies
    assert parse(policies[0]) == ISLAND_EXPECTED
    assert "content-security-policy-report-only" not in resp.headers
    assert "no-store" in resp.headers["cache-control"]


async def test_the_island_gets_its_policy_under_any_name_that_reaches_it(app, tmp_path):
    # Whatever file a name reaches gets that file's policy. On a Mac's disk, which ignores case, /ISLAND.HTML is the
    # island itself, and a spelling match sent it out with neither the policy nor no-store. On CI's case-sensitive
    # Linux the same name reaches no file and is the main page under the main policy, which is right there. A hard link
    # is the island under another name on either disk, so it pins the island's case everywhere.
    web = tmp_path / "web"
    os.link(web / "island.html", web / "notch.html")
    reached_island = 0
    async with client(app) as c:
        for path in ("/ISLAND.HTML", "/Island.html", "/notch.html"):
            resp = await c.get(path)
            target = web / path.lstrip("/")
            if target.exists() and os.path.samefile(target, web / "island.html"):
                reached_island += 1
                assert "<title>Arslan Island</title>" in resp.text, path
                assert parse(resp.headers.get("content-security-policy", "")) == ISLAND_EXPECTED, path
            else:
                assert "<title>Arslan</title>" in resp.text, path
                assert parse(resp.headers.get("content-security-policy", "")) == expected(PORT), path
            assert "no-store" in resp.headers.get("cache-control", ""), path
    assert reached_island >= 1      # the hard link reaches the island on any disk


async def test_the_island_policy_ignores_forwarded_headers_too(app):
    async with client(app, port=51234) as c:
        resp = await c.get("/island.html", headers=FORWARDED_SPOOF)

    assert parse(resp.headers["content-security-policy"]) == ISLAND_EXPECTED


def test_the_island_page_has_no_inline_script_or_style():
    # Its policy allows neither: an inline <style> or <script> in web/island.html would be refused, and the window
    # would lose that rule or code with only a console error to say so. Its page-level rules live in island.css.
    html = (REPO / "web" / "island.html").read_text().lower()
    assert "<style" not in html and " style=" not in html, "inline style in island.html; it belongs in island.css"
    scripts = re.findall(r"<script\b([^>]*)>", html)
    assert scripts and all("src=" in attrs for attrs in scripts), scripts


async def test_the_boot_script_is_served_from_the_static_root_as_javascript(app, tmp_path):
    # script-src 'self' with no hash: the boot veil's script is a file the same server serves, not inline text. The
    # build copies web/public to the static root, so that is where it lands.
    (tmp_path / "web" / "boot-veil.js").write_bytes((REPO / "web" / "public" / "boot-veil.js").read_bytes())
    async with client(app) as c:
        resp = await c.get("/boot-veil.js?v=1")

    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"], resp.headers["content-type"]
    assert resp.content == (REPO / "web" / "public" / "boot-veil.js").read_bytes()
