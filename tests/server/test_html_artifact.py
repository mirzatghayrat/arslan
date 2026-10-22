"""HX-2 (spec B1/B3): HTML artifact channel — sniffer units, disk store + download
endpoint, and the full route→dispatch regression (acceptance criteria 2, 3, 4-B)."""
from __future__ import annotations




# --- sniff_html_doc units ---------------------------------------------------

# --- store + download endpoint (acceptance #3) -------------------------------

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


# --- route→dispatch regression (acceptance #4-B) ------------------------------

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
