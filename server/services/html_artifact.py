"""HTML deliverable channel (HX-2, spec B1/B3).

Deterministic sniffer that runs at the spawn final-output exit (dispatcher.dispatch,
which every spawn path goes through — B3) and detects a full single-file HTML document
in the reply — complete OR truncated by max-tokens (the live incident: a 21K-char
`<!DOCTYPE html>` reply with no `</html>` landed as a raw code wall in chat). On a hit
the document is stored on disk (acceptance #3: retrievable), served via
`GET /api/v1/runs/{run_id}/artifacts/{filename}`, and the chat shows a one-line summary
instead of the raw HTML.

Boundary (acceptance #2): a doctype inside a markdown code fence (``` or ~~~) is
teaching/example code and stays verbatim — never packaged.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# A doc cut by max-tokens has no </html>; only treat it as a deliverable when there is
# substantial content after the doctype. Below this it's a small snippet — leave alone.
MIN_TRUNCATED_CHARS = 2000
# Frontend parity (MessageBody.extractEmbeddedHtmlDoc): a complete doc under 400 chars
# is "not a real document".
_MIN_COMPLETE_CHARS = 400
_SLUG_MAX = 40

_DOCTYPE_RE = re.compile(r"<!doctype html", re.IGNORECASE)
_HTML_CLOSE_RE = re.compile(r"</html>", re.IGNORECASE)
_FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# Same shape as the frontend's dangling-opening-fence trim in extractEmbeddedHtmlDoc.
_DANGLING_FENCE_RE = re.compile(r"(^|\n)\s*(`{3,}|~{3,})[a-z]*\s*$", re.IGNORECASE)


def _first_unfenced_doctype(text: str) -> int | None:
    """Offset of the first `<!doctype html` that is NOT inside an open markdown fence.

    Fence state is tracked line-by-line (``` / ~~~ toggle, leading spaces allowed —
    mirrors the frontend's exportMarkdown fence walk). A doctype on a line inside an
    open fence is example code (acceptance #2) and is skipped.
    """
    hits = [m.start() for m in _DOCTYPE_RE.finditer(text)]
    if not hits:
        return None
    in_fence = False
    line_start = 0
    hit_iter = iter(hits)
    hit = next(hit_iter)
    for line in text.splitlines(keepends=True):
        line_end = line_start + len(line)
        if _FENCE_LINE_RE.match(line):
            in_fence = not in_fence
        else:
            while hit is not None and line_start <= hit < line_end:
                if not in_fence:
                    return hit
                hit = next(hit_iter, None)
        if hit is None:
            return None
        line_start = line_end
    return None


def _extract_title(html: str) -> str:
    for pattern in (_TITLE_RE, _H1_RE):
        m = pattern.search(html)
        if m:
            title = _TAG_RE.sub("", m.group(1)).strip()
            if title:
                return title
    return "HTML 文档"


def sniff_html_doc(text: str) -> dict | None:
    """Detect a full/truncated HTML document deliverable in a spawn's final text.

    Returns None (leave the message verbatim) or
    {"pre": preamble text, "html": the document, "complete": bool, "title": str}.
    """
    if not text or "<!doctype" not in text.lower():
        return None
    start = _first_unfenced_doctype(text)
    if start is None:
        return None
    close = _HTML_CLOSE_RE.search(text, start)
    if close is not None:
        html = text[start:close.end()]
        if len(html) < _MIN_COMPLETE_CHARS:
            return None  # trivial inline example, not a deliverable
        complete = True
    else:
        # TRUNCATED case (the incident): max-tokens cut the doc before </html>.
        if len(text) - start < MIN_TRUNCATED_CHARS:
            return None
        html = text[start:]
        complete = False
    pre = text[:start]
    # Frontend parity (extractEmbeddedHtmlDoc): trim a DANGLING opening fence line
    # right above the doc — but only when it is actually dangling (odd fence count),
    # so a legitimately closed ``` pair in the preamble stays verbatim.
    if sum(1 for ln in pre.splitlines() if _FENCE_LINE_RE.match(ln)) % 2 == 1:
        pre = _DANGLING_FENCE_RE.sub("", pre)
    pre = pre.rstrip()
    return {"pre": pre, "html": html, "complete": complete, "title": _extract_title(html)}


def artifacts_dir() -> Path:
    """`{data_dir}/artifacts` — env read at call time (test/deploy friendly, same
    pattern as skill_import/code_sandbox `_data_dir()`)."""
    return Path(os.environ.get("ARSLAN_DATA_DIR", "data")).resolve() / "artifacts"


def _slug(title: str) -> str:
    safe = "".join(c for c in title if c.isalnum() or c in " -_（）()").strip()
    safe = re.sub(r"\s+", "-", safe)[:_SLUG_MAX].strip("-")
    return safe or "html"


def store_html_artifact(run_id: int, title: str, html: str) -> dict:
    """Persist the document to disk; returns {"filename", "path", "bytes"}.

    Acceptance #3: after the chat message is summarized, the full HTML must remain
    retrievable — this file is what the /runs/{run_id}/artifacts/{filename} endpoint
    serves.
    """
    directory = artifacts_dir()
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"run_{run_id}_{_slug(title)}.html"
    path = directory / filename
    data = html.encode("utf-8")
    path.write_bytes(data)
    return {"filename": filename, "path": str(path), "bytes": len(data)}


def package_spawn_output(run_id: int | None, text: str) -> tuple[str, dict | None]:
    """The spawn-output exit hook (B3 — called for EVERY dispatched spawn).

    Returns (display_text, artifact | None). On a sniff hit the display text becomes
    `{preamble}\\n\\n已生成 HTML 文档《title》(N KB)[ ⚠ 输出被截断] — [⬇ 下载](url)` and
    the artifact dict {kind, filename, title, bytes, complete, content} is returned for
    the WS frame. Fail-open: any error → (text, None), the turn is never broken.
    """
    if run_id is None:
        return text, None
    try:
        hit = sniff_html_doc(text)
        if hit is None:
            return text, None
        stored = store_html_artifact(run_id, hit["title"], hit["html"])
        kb = max(1, round(stored["bytes"] / 1024))
        note = f"已生成 HTML 文档《{hit['title']}》({kb} KB)"
        if not hit["complete"]:
            note += " ⚠ 输出被截断"
        link = f"[⬇ 下载](/api/v1/runs/{run_id}/artifacts/{stored['filename']})"
        display = (f"{hit['pre']}\n\n" if hit["pre"] else "") + f"{note} — {link}"
        artifact = {
            "kind": "html",
            "filename": stored["filename"],
            "title": hit["title"],
            "bytes": stored["bytes"],
            "complete": hit["complete"],
            "content": hit["html"],
        }
        return display, artifact
    except Exception as exc:  # noqa: BLE001 — fail-open: raw text beats a broken turn
        logger.warning("html artifact packaging failed (fail-open): %s", exc)
        return text, None
