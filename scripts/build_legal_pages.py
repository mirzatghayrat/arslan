"""Build the plain reading pages served at aralem.dev/arslan/privacy/ and /support/.

The text lives in docs/legal/*.md (copied verbatim from the iPhone app's store
docs). This turns that small Markdown subset (headings, bold, bullet lists,
rules, paragraphs, bare links and emails) into static HTML under docs/, which
GitHub Pages serves as-is (docs/.nojekyll). Re-run after editing the Markdown:

    python3 scripts/build_legal_pages.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PAGES = {
    "privacy": (
        "legal/privacy-policy.md",
        "Arslan Privacy Policy",
        "How Arslan for iPhone and Arslan for Mac handle your data: no servers, no data collected.",
    ),
    "support": (
        "legal/support.md",
        "Arslan Support",
        "Help with Arslan for iPhone and Arslan for Mac: pairing, approvals, and how to reach us.",
    ),
}
# URLs are ASCII only, so a link stops at full-width punctuation such as "）" or "，".
LINK = re.compile(
    r"(https?://[!-~]*[A-Za-z0-9/#=_-])|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def inline(text: str) -> str:
    out, pos = [], 0
    for m in LINK.finditer(text):
        out.append(html.escape(text[pos : m.start()], quote=False))
        url, mail = m.group(1), m.group(2)
        href = url if url else f"mailto:{mail}"
        out.append(f'<a href="{html.escape(href)}">{html.escape(m.group(0), quote=False)}</a>')
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", "".join(out))


def note(text: str) -> str:
    """The Markdown opens with an editor's note ("To be published at …"). Keep
    only what a reader needs from it: the "Last updated" date, if any."""
    m = re.search(r"Last updated:\s*[0-9-]+", text)
    return f'<p class="updated">{m.group(0)}</p>' if m else ""


def body(md: str) -> tuple[str, str]:
    title, blocks, para, items = "", [], [], []
    lang_open = False

    def flush() -> None:
        if para:
            blocks.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("# "):
            title = s[2:]
        elif s.startswith("> "):
            flush()
            blocks.append(note(s[2:]))
        elif s.startswith("## "):
            flush()
            heading = s[3:]
            lang = "zh-Hans" if re.search(r"[一-鿿]", heading) else "en"
            sid = "zh" if lang == "zh-Hans" else "en"
            if lang_open:
                blocks.append("</section>")
            blocks.append(f'<section id="{sid}" lang="{lang}"><h2>{inline(heading)}</h2>')
            lang_open = True
        elif s.startswith("### "):
            flush()
            blocks.append(f"<h3>{inline(s[4:])}</h3>")
        elif s == "---":
            flush()
        elif s.startswith("- "):
            if para:
                flush()
            items.append(s[2:])
        else:
            para.append(s)
    flush()
    if lang_open:
        blocks.append("</section>")
    return title, "\n".join(b for b in blocks if b)


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="https://aralem.dev/arslan/{slug}/">
<link rel="icon" type="image/svg+xml" href="../assets/site/favicon.svg">
<meta name="color-scheme" content="light dark">
<style>
:root{{--bg:#F6EBD6;--fg:#2A1E10;--muted:#6B5A44;--rule:rgba(42,30,16,.16);--link:#9A4A12}}
@media (prefers-color-scheme:dark){{:root{{--bg:#231710;--fg:#F6EBD6;--muted:#C9B79B;--rule:rgba(246,235,214,.18);--link:#F3C34A}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-text-size-adjust:100%}}
main{{max-width:44rem;margin:0 auto;padding:28px 20px 72px}}
nav{{display:flex;gap:18px;flex-wrap:wrap;font-size:15px;margin-bottom:28px}}
a{{color:var(--link);text-underline-offset:2px;overflow-wrap:anywhere}}
a:focus-visible{{outline:3px solid var(--link);outline-offset:2px;border-radius:4px}}
h1{{font-size:clamp(26px,6vw,34px);line-height:1.2;margin:0 0 6px}}
h2{{font-size:22px;margin:44px 0 6px;padding-top:28px;border-top:1px solid var(--rule)}}
h3{{font-size:18px;margin:28px 0 4px}}
p,ul{{margin:10px 0}}
ul{{padding-left:1.3em}}
li{{margin:6px 0}}
.updated{{color:var(--muted);font-size:15px;margin:0}}
section[lang="zh-Hans"]{{line-height:1.8}}
footer{{margin-top:56px;padding-top:18px;border-top:1px solid var(--rule);font-size:15px;color:var(--muted);display:flex;gap:18px;flex-wrap:wrap}}
</style>
</head>
<body>
<main>
<nav aria-label="Page"><a href="../">← Arslan</a><a href="#en">English</a><a href="#zh" lang="zh-Hans">中文</a></nav>
<h1>{h1}</h1>
{content}
<footer><a href="../">aralem.dev/arslan</a><a href="../privacy/">Privacy</a><a href="../support/">Support</a></footer>
</main>
</body>
</html>
"""


def main() -> None:
    for slug, (src, title, desc) in PAGES.items():
        h1, content = body((DOCS / src).read_text(encoding="utf-8"))
        page = TEMPLATE.format(
            title=html.escape(title),
            desc=html.escape(desc),
            slug=slug,
            h1=inline(h1),
            content=content,
        )
        out = DOCS / slug / "index.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
