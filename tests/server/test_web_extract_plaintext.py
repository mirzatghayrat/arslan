"""Raw README/code text must not be passed through an HTML article parser."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import httpx
import pytest

from server.registry import net_pin
from server.registry.executors import WebExtractExecutor


@pytest.mark.parametrize("media_type", ["text/plain; charset=utf-8", "text/markdown", "Text/Plain"])
async def test_raw_markdown_keeps_angle_brackets_and_install_commands(monkeypatch, media_type):
    text = '# Install\n```bash\ncd <this-repo>\nuv sync\nbash scripts/setup_verl.sh 0.8.0 cu130\n```\n\n## Architecture\nKeep <placeholder> and all following text.\n'
    async def get(url):
        return httpx.Response(200, text=text, headers={"Content-Type": media_type}, request=httpx.Request("GET", url))
    monkeypatch.setattr(net_pin, "pinned_get", get)
    parser = Mock(return_value="HTML parser must not run")
    monkeypatch.setattr(net_pin.trafilatura, "extract", parser)
    result = await WebExtractExecutor().execute({"url": "https://example.com/README.md", "max_chars": 40000})
    assert result["ok"] and result["text"] == text
    assert result["total_chars"] == len(text) and result["source"]["truncated"] is False
    parser.assert_not_called()


async def test_plaintext_still_obeys_requested_bound(monkeypatch):
    async def get(url):
        return httpx.Response(200, text="<item>\n" * 100, headers={"Content-Type": "text/plain"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(net_pin, "pinned_get", get)
    result = await WebExtractExecutor().execute({"url": "https://example.com/README.md", "max_chars": 15})
    assert result["text"] == ("<item>\n" * 100)[:15]
    assert result["total_chars"] == 700 and result["source"]["truncated"] is True


@pytest.mark.parametrize("media_type", ["text/html", "application/xhtml+xml", ""])
async def test_html_or_unspecified_content_keeps_article_extraction(monkeypatch, media_type):
    async def get(url):
        return httpx.Response(200, content=b"<html><body>Article</body></html>",
            headers={"Content-Type": media_type}, request=httpx.Request("GET", url))
    monkeypatch.setattr(net_pin, "pinned_get", get)
    parser = Mock(return_value="Extracted article")
    monkeypatch.setattr(net_pin.trafilatura, "extract", parser)
    assert await net_pin._fetch_text("https://example.com/README.md") == "Extracted article"
    parser.assert_called_once()


@pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_PLAINTEXT_EVIDENCE") != "1",
                    reason="explicit archived README evidence, no live model or network")
async def test_archived_lightning_readme_keeps_real_installation(monkeypatch):
    from evals.companion import stable_budget as budget
    from evals.companion.stable_live import persist
    from server.orchestrator.tool_loop import _record_tool_result
    folder = budget.EVIDENCE / "public-inputs"
    metadata = json.loads((folder / "lightning-current.json").read_bytes())
    body = (folder / metadata["file"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == metadata["sha256"]
    assert metadata["content_type"].split(";")[0] == "text/plain"

    async def get(url):
        assert url == metadata["url"]
        return httpx.Response(200, content=body, headers={"Content-Type": metadata["content_type"]},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(net_pin, "pinned_get", get)
    args = {"url": metadata["url"], "max_chars": 40000}
    result = await WebExtractExecutor().execute(args)
    assert result["text"] == body.decode() and not result["source"]["truncated"]
    assert "cd <this-repo>\nuv sync\nbash scripts/setup_verl.sh 0.8.0 cu130" in result["text"]
    trace, conversation = [], []
    delivered = _record_tool_result("web_extract", args, result, lambda _: None, trace, "Read source", conversation)
    assert delivered["text"] == body.decode()
    assert json.dumps(delivered["text"], ensure_ascii=False)[1:-1] in conversation[-1]["content"]
    persist(budget.EVIDENCE / "plaintext-readme-repair-v1.json", {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input": metadata, "result": delivered, "full_raw_text_in_tool_feedback": True,
        "transport": "Archived source bytes; no network or model", "live_R3_retest": "not_run",
        "semantic_quality": "not_run", "native_ui": "not_run"})
