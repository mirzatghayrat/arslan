"""HX-2 (spec B1/B3): HTML artifact channel — sniffer units, disk store + download
endpoint, and the full route→dispatch regression (acceptance criteria 2, 3, 4-B)."""
from __future__ import annotations

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, Spawn
from server.services.html_artifact import sniff_html_doc, store_html_artifact


def _full_doc(body_chars: int = 3000, title: str | None = "季度汇报") -> str:
    title_tag = f"<title>{title}</title>" if title else ""
    return (
        "<!DOCTYPE html>\n<html>\n<head>" + title_tag + "<style>body{color:red}</style></head>\n"
        "<body>" + ("x" * body_chars) + "</body>\n</html>"
    )


# --- sniff_html_doc units ---------------------------------------------------

def test_sniff_full_doc_with_preamble_hits_complete():
    # (a) The incident shape: one English preamble line + full document.
    text = "Here is your presentation, ready to use:\n\n" + _full_doc()
    hit = sniff_html_doc(text)
    assert hit is not None
    assert hit["complete"] is True
    assert hit["html"].lower().startswith("<!doctype html")
    assert hit["html"].rstrip().lower().endswith("</html>")
    assert hit["pre"] == "Here is your presentation, ready to use:"
    assert hit["title"] == "季度汇报"


def test_sniff_truncated_doc_hits_incomplete():
    # (b) Regression for the live incident: max-tokens cut the doc — no </html>.
    doc = _full_doc()
    truncated = "A quick preamble line.\n\n" + doc[: len(doc) - 60]  # drop the tail incl. </html>
    assert len(truncated) - truncated.lower().find("<!doctype html") >= 2000
    hit = sniff_html_doc(truncated)
    assert hit is not None
    assert hit["complete"] is False
    assert "</html>" not in hit["html"].lower()
    assert hit["pre"] == "A quick preamble line."


def test_sniff_fenced_doc_returns_none():
    # (c) Acceptance #2: 用户要 HTML 示例代码 — fenced teaching code stays verbatim.
    # Fixture is a true SNIPPET (< the 2000-char fenced-deliverable floor): the same
    # doc unfenced WOULD package (complete ≥400), so this pins fence protection —
    # while a fenced ≥2000-char message-dominating doc is the PA-6 deliverable
    # exception, covered by test_fenced_complete_deliverable_is_packaged.
    text = "HTML 文档的基本骨架长这样:\n\n```html\n" + _full_doc(body_chars=900) + "\n```\n\n照着写就行。"
    assert sniff_html_doc(text) is None


def test_sniff_tilde_fenced_doc_returns_none():
    text = "示例:\n\n~~~\n" + _full_doc(body_chars=900) + "\n~~~\n"
    assert sniff_html_doc(text) is None


def test_sniff_fragment_without_doctype_returns_none():
    # (d) Bare fragment — B2 personas guarantee complete single-file docs.
    assert sniff_html_doc("<div>" + "x" * 5000 + "</div>") is None


def test_sniff_short_unclosed_doctype_returns_none():
    # (e) Under 2000 chars with no </html>: a small snippet, leave it alone.
    assert sniff_html_doc("look: <!DOCTYPE html><html><body>hi</body>") is None


def test_sniff_title_extraction_fallbacks():
    # (f) <title> wins; else first <h1>; else the default.
    with_h1 = ("<!doctype html><html><head></head><body><h1>年度总结</h1>"
               + "x" * 500 + "</body></html>")
    assert sniff_html_doc(with_h1)["title"] == "年度总结"
    bare = "<!doctype html><html><head></head><body>" + "x" * 500 + "</body></html>"
    assert sniff_html_doc(bare)["title"] == "HTML 文档"


def test_sniff_trims_dangling_opening_fence_from_pre():
    # A fence that OPENED in the preamble but closed before the doctype leaves fence
    # state closed; a stray closed pair stays. The frontend-parity trim targets a
    # dangling ```html line right above the doc — reproduce via a closed earlier pair.
    text = "先看说明:\n```txt\nnot html here\n```\n" + _full_doc()
    hit = sniff_html_doc(text)
    assert hit is not None
    assert hit["pre"].endswith("```")  # closed pair in pre is preserved verbatim


# --- store + download endpoint (acceptance #3) -------------------------------

def test_store_html_artifact_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    html = _full_doc()
    out = store_html_artifact(42, "季度汇报 Q2/Q3: 最终版", html)
    assert out["filename"].startswith("run_42_")
    assert out["filename"].endswith(".html")
    assert "/" not in out["filename"].replace(str(tmp_path), "")
    p = tmp_path / "artifacts" / out["filename"]
    assert p.read_text(encoding="utf-8") == html
    assert out["bytes"] == len(html.encode("utf-8"))


async def test_download_endpoint_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    html = _full_doc()
    out = store_html_artifact(7, "报告", html)
    resp = await client.get(f"/api/v1/runs/7/artifacts/{out['filename']}")
    assert resp.status_code == 200
    assert resp.content.decode("utf-8") == html  # byte-identical retrieval


async def test_download_endpoint_missing_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    resp = await client.get("/api/v1/runs/7/artifacts/run_7_nope.html")
    assert resp.status_code == 404


async def test_download_endpoint_rejects_traversal(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    resp = await client.get("/api/v1/runs/7/artifacts/run_7_..%2F..%2Fsecrets.html")
    assert resp.status_code in (400, 404)
    resp2 = await client.get("/api/v1/runs/7/artifacts/run_7_....html".replace("....", "..%2e"))
    assert resp2.status_code in (400, 404)


async def test_download_endpoint_rejects_wrong_run_prefix(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    out = store_html_artifact(8, "别人的", _full_doc())
    # run 9 must not be able to fetch run 8's artifact via its own endpoint.
    resp = await client.get(f"/api/v1/runs/9/artifacts/{out['filename']}")
    assert resp.status_code == 400


# --- route→dispatch regression (acceptance #4-B) ------------------------------

@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hx2.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(Spawn(id=6, name="deck-master", domain_category="content-creator",
                        capabilities=["deck"], system_prompt="You build decks."))
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_route_flow_packages_html_as_artifact(maker, monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    from server.orchestrator import arslan, dispatcher, router, tool_loop
    from tests.server.conftest import MockAdapter

    html = _full_doc(body_chars=4000, title="OKX 介绍")
    spawn_reply = "Here is your presentation:\n\n" + html
    adapter = MockAdapter(chat_content=spawn_reply, stream_chunks=[spawn_reply])
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _route(conv, msg):
        return router.RouterResult(action="route", spawn_id=6, task_brief="make the deck")

    monkeypatch.setattr(arslan.router, "route", _route)

    from server.services import roster_service
    await roster_service.join("main", 6, via="invited")

    events = []
    await arslan.handle_user_message("main", "have deck-master make the deck",
                                     lambda e: events.append(e))

    # display_content is the SUMMARY, not the raw HTML wall.
    async with db_session.AsyncSessionLocal() as s:
        ams = (await s.execute(select(ArslanMessage))).scalars().all()
    summary_row = next(a for a in ams if a.role == "spawn_summary")
    assert "已生成 HTML 文档" in summary_row.display_content
    assert "OKX 介绍" in summary_row.display_content
    assert "/artifacts/run_" in summary_row.display_content  # download link
    assert "<style>" not in summary_row.display_content
    assert "Here is your presentation:" in summary_row.display_content  # preamble kept
    # memory 1-liner mechanism unchanged
    assert summary_row.content.startswith("[deck-master]")

    # the full HTML is on disk, byte-identical (acceptance #3)
    run_id = next(e["run_id"] for e in events if e.get("type") == "spawn_meta")
    files = list((tmp_path / "artifacts").glob(f"run_{run_id}_*.html"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == html

    # the emitted stream_end frame carries the artifact for live rendering
    end = next(e for e in events if e.get("type") == "stream_end" and e.get("artifact"))
    art = end["artifact"]
    assert art["kind"] == "html"
    assert art["title"] == "OKX 介绍"
    assert art["complete"] is True
    assert art["content"] == html
    assert art["filename"] == files[0].name


@pytest.mark.asyncio
async def test_route_flow_leaves_plain_text_untouched(maker, monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    from server.orchestrator import arslan, dispatcher, router, tool_loop
    from tests.server.conftest import MockAdapter

    adapter = MockAdapter(chat_content="Post 1. Post 2.", stream_chunks=["Post 1. Post 2."])
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _route(conv, msg):
        return router.RouterResult(action="route", spawn_id=6, task_brief="posts")

    monkeypatch.setattr(arslan.router, "route", _route)
    from server.services import roster_service
    await roster_service.join("main", 6, via="invited")

    events = []
    await arslan.handle_user_message("main", "have deck-master make posts",
                                     lambda e: events.append(e))

    async with db_session.AsyncSessionLocal() as s:
        ams = (await s.execute(select(ArslanMessage))).scalars().all()
    summary_row = next(a for a in ams if a.role == "spawn_summary")
    assert summary_row.display_content == "Post 1. Post 2."  # unchanged behavior
    end = next(e for e in events if e.get("type") == "stream_end")
    assert "artifact" not in end


# ---------------------------------------------------------------------------
# Fenced DELIVERABLE vs fenced teaching snippet (PA-6 real-machine finding):
# run 70 shipped its complete 16K doc wrapped in a ```html fence (disobeying the
# persona) and the fence rule skipped packaging. A fenced doc is a deliverable —
# not a protected snippet — only when ALL THREE hold: complete (</html>), ≥2000
# chars, and ≥70% of the whole message. Snippets/teaching stay verbatim.
# ---------------------------------------------------------------------------

_BIG_DOC = ("<!DOCTYPE html>\n<html lang=\"zh\">\n<head><title>新能源简报</title></head>\n<body>"
            + ("<div class=\"card\">数据卡片内容,暗色磨砂玻璃,金色点缀。</div>\n" * 80)
            + "</body>\n</html>")


def test_fenced_complete_deliverable_is_packaged():
    text = "以下是您所需的简报HTML代码。\n\n```html\n" + _BIG_DOC + "\n```"
    hit = sniff_html_doc(text)
    assert hit is not None
    assert hit["complete"] is True
    assert hit["html"].startswith("<!DOCTYPE html>") and hit["html"].rstrip().endswith("</html>")
    assert "```" not in hit["pre"]          # opening fence trimmed from the preamble
    assert hit["title"] == "新能源简报"


def test_fenced_short_snippet_stays_verbatim():
    doc = "<!DOCTYPE html>\n<html><body><p>示例</p></body></html>"
    text = "这是一个 HTML 结构的教学示例:\n\n```html\n" + doc + "\n```\n\n如上,DOCTYPE 声明放最前面。"
    assert sniff_html_doc(text) is None   # < 2000 chars → snippet


def test_fenced_doc_buried_in_long_prose_stays_verbatim():
    prose = "下面我们逐段讲解这个页面的实现原理。" * 220   # long teaching context
    text = prose + "\n完整代码如下:\n```html\n" + _BIG_DOC + "\n```\n" + prose
    assert sniff_html_doc(text) is None   # ratio < 0.7 → teaching context
