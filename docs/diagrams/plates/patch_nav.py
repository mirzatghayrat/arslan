"""Swaps the READMEs' nav and language rows over to the button images.

The links stay exactly what they were — same six destinations, same six
translations — they just stop being blue underlined text. Each button carries
its label as `alt`, so a reader with images off, or a screen reader, still gets
the words rather than a filename.

Run from the repository root, after buttons.py.
"""

import pathlib
import re
import sys

NAV_LINKS = [
    ("download", "https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"),
    ("website", "https://mirzatghayrat.github.io/arslan/"),
    ("quickstart", "docs/QUICKSTART.md"),
    ("architecture", "docs/ARCHITECTURE.md"),
    ("security", "SECURITY.md"),
    ("contributing", "CONTRIBUTING.md"),
]

# label text per language, in NAV_LINKS order — used for alt only
NAV_ALT = {
    "en": ["Download for macOS", "Website", "Quickstart", "Architecture", "Security", "Contributing"],
    "zh": ["下载 macOS 版", "官网", "快速上手", "架构", "安全", "参与贡献"],
    "de": ["Für macOS laden", "Website", "Quickstart", "Architektur", "Security", "Mitmachen"],
    "ja": ["macOS 版をダウンロード", "ウェブサイト", "クイックスタート", "アーキテクチャ", "セキュリティ", "コントリビューション"],
    "es": ["Descargar para macOS", "Sitio web", "Inicio rápido", "Arquitectura", "Seguridad", "Contribuir"],
    "tr": ["macOS için indir", "Web Sitesi", "Hızlı Başlangıç", "Mimari", "Güvenlik", "Katkıda Bulunma"],
}

LANGS = [("en", "English", "README.md"), ("zh", "简体中文", "README.zh-CN.md"),
         ("de", "Deutsch", "README.de.md"), ("ja", "日本語", "README.ja.md"),
         ("es", "Español", "README.es.md"), ("tr", "Türkçe", "README.tr.md")]

FILES = {code: path for code, _, path in LANGS}

NAV_LINE = re.compile(
    r'^<a href="https://github\.com/mirzatghayrat/arslan/releases/latest/download/'
    r'Arslan-macos-arm64\.dmg">.*$',
    re.M,
)
LANG_LINE = re.compile(r'^<sub><img src="docs/assets/icons/languages\.svg".*$', re.M)


def nav_row(code):
    parts = [
        f'<a href="{href}"><img src="docs/assets/btn/{code}-{slug}.png" '
        f'alt="{alt}" height="44"></a>'
        for (slug, href), alt in zip(NAV_LINKS, NAV_ALT[code])
    ]
    return "&nbsp;&nbsp;".join(parts)


def lang_row(current):
    parts = []
    for code, label, path in LANGS:
        if code == current:
            parts.append(f'<img src="docs/assets/btn/lang-{code}-on.png" alt="{label}" height="32">')
        else:
            parts.append(
                f'<a href="{path}"><img src="docs/assets/btn/lang-{code}.png" '
                f'alt="{label}" height="32"></a>'
            )
    return "&nbsp;".join(parts)


failed = False
for code, path in FILES.items():
    p = pathlib.Path(path)
    src = p.read_text(encoding="utf-8")

    out, n = NAV_LINE.subn(lambda _: nav_row(code), src, count=1)
    if n != 1:
        print(f"{path}: nav row not found", file=sys.stderr)
        failed = True
    out, n = LANG_LINE.subn(lambda _: lang_row(code), out, count=1)
    if n != 1:
        print(f"{path}: language row not found", file=sys.stderr)
        failed = True

    if out != src:
        p.write_text(out, encoding="utf-8")
        print(f"patched {path}")

sys.exit(1 if failed else 0)
