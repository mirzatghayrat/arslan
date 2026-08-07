"""Renders the README's navigation and language rows as button images.

GitHub strips CSS from a README, so a link is a blue underlined link and there
is no styling hook to change that. The way to get a button is to ship a picture
of one and wrap it in the link.

They are rendered here rather than fetched from a badge service because these
six rows are the first thing a visitor sees: an outage or a rename at a third
party would blank the top of the README in six languages. They also carry the
site's clay look, which no badge service offers.

Rendered at 3x and displayed with `height="44"`, so they stay sharp on a retina
screen. Every pill has a solid fill — nothing transparent — so the rows read the
same on GitHub's light and dark themes.

    python3 buttons.py            # writes ../../assets/btn/*.png

Needs a Chromium with --screenshot and --dump-dom; override with CHROMIUM=.
"""

import os
import pathlib
import re
import subprocess
import sys

SCALE = 3
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent.parent / "assets" / "btn"
ICONS = HERE.parent.parent / "assets" / "icons"
CHROMIUM = os.environ.get(
    "CHROMIUM", "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
)

# Latin from Inter; Turkish's ı/ğ/ş and the CJK labels fall through to what the
# render host has, so the stack is explicit rather than left to the default.
FONTS = '"Inter","DejaVu Sans","WenQuanYi Zen Hei","IPAPGothic",sans-serif'

NAV = {
    "en": ["Download for macOS", "Website", "Quickstart", "Architecture", "Security", "Contributing"],
    "zh": ["下载 macOS 版", "官网", "快速上手", "架构", "安全", "参与贡献"],
    "de": ["Für macOS laden", "Website", "Quickstart", "Architektur", "Security", "Mitmachen"],
    "ja": ["macOS 版をダウンロード", "ウェブサイト", "クイックスタート", "アーキテクチャ", "セキュリティ", "コントリビューション"],
    "es": ["Descargar para macOS", "Sitio web", "Inicio rápido", "Arquitectura", "Seguridad", "Contribuir"],
    "tr": ["macOS için indir", "Web Sitesi", "Hızlı Başlangıç", "Mimari", "Güvenlik", "Katkıda Bulunma"],
}
NAV_SLUGS = ["download", "website", "quickstart", "architecture", "security", "contributing"]
NAV_ICONS = [None, "globe", "zap", "layers", "shield", "heart-handshake"]

# The language row is the same six words in every README; only which one is the
# current page changes, so each is rendered twice rather than six times.
LANGS = [("en", "English"), ("zh", "简体中文"), ("de", "Deutsch"),
         ("ja", "日本語"), ("es", "Español"), ("tr", "Türkçe")]

CSS = """
@font-face{font-family:Inter;src:url(fonts/inter-variable.woff2) format('woff2');font-weight:100 900}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent}
body{width:max-content;font-family:%(fonts)s}
.pill{display:inline-flex;align-items:center;gap:%(gap)spx;width:max-content;
  height:%(h)spx;padding:0 %(pad)spx;border-radius:999px;
  font-size:%(fs)spx;font-weight:700;letter-spacing:-.01em;white-space:nowrap}
.pill svg{width:%(ico)spx;height:%(ico)spx;flex:none}
/* primary: the download call to action, the site's butter pill */
.primary{background:#F3C34A;color:#241407;
  box-shadow:inset 0 %(i1)spx %(i2)spx rgba(255,255,255,.45),inset 0 -%(i1)spx %(i2)spx rgba(0,0,0,.16)}
/* secondary: solid night so it reads on a white page and a dark one alike */
.secondary{background:#2B1C11;color:#F6EBD6;
  box-shadow:inset 0 0 0 %(b)spx rgba(246,235,214,.16),inset 0 %(i1)spx %(i2)spx rgba(255,255,255,.10)}
.secondary svg{stroke:#F3C34A}
.chip{height:%(ch)spx;padding:0 %(cpad)spx;font-size:%(cfs)spx;font-weight:600}
.arrow{font-size:%(fs)spx;line-height:1}
"""


def css():
    return CSS % dict(
        fonts=FONTS, gap=4 * SCALE, h=44 * SCALE, pad=21 * SCALE, fs=17 * SCALE,
        ico=17 * SCALE, i1=2 * SCALE, i2=5 * SCALE, b=1 * SCALE,
        ch=32 * SCALE, cpad=15 * SCALE, cfs=14 * SCALE,
    )


def icon(name):
    """Inline the lucide source so `stroke` can be themed by CSS."""
    if not name:
        return ""
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    return svg.replace('stroke="#e6863c"', "").strip()


def page(inner):
    return f"<meta charset=utf-8><style>{css()}</style>{inner}"


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def measure(html_path):
    """Chromium reports the laid-out width; nothing else knows how wide a
    proportional string is, and a guess would leave slivers of background."""
    out = run([CHROMIUM, "--no-sandbox", "--disable-gpu", "--headless",
               "--virtual-time-budget=3000", "--dump-dom", str(html_path)]).stdout
    m = re.search(r'id="w"[^>]*>(\d+)<', out)
    if not m:
        sys.exit(f"could not measure {html_path.name}")
    return int(m.group(1))


def render(name, inner):
    src = HERE / f"_btn_{name}.html"
    probe = ('<script>document.body.insertAdjacentHTML("beforeend",'
             '"<div id=w style=display:none>"+'
             'Math.ceil(document.querySelector(".pill").getBoundingClientRect().width)+"</div>")</script>')
    src.write_text(page(inner + probe), encoding="utf-8")
    width = measure(src)
    src.write_text(page(inner), encoding="utf-8")
    dst = OUT / f"{name}.png"
    run([CHROMIUM, "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--default-background-color=00000000",
         f"--screenshot={dst}", f"--window-size={width},{44 * SCALE}",
         "--virtual-time-budget=4000", str(src)])
    src.unlink()
    if not dst.exists():
        sys.exit(f"render failed: {name}")
    return dst


OUT.mkdir(parents=True, exist_ok=True)
made = []

for lang, labels in NAV.items():
    for slug, label, ico in zip(NAV_SLUGS, labels, NAV_ICONS):
        if slug == "download":
            inner = f'<span class="pill primary"><span class="arrow">↓</span>{label}</span>'
        else:
            inner = f'<span class="pill secondary">{icon(ico)}{label}</span>'
        made.append(render(f"{lang}-{slug}", inner))

for code, label in LANGS:
    made.append(render(f"lang-{code}", f'<span class="pill secondary chip">{label}</span>'))
    made.append(render(f"lang-{code}-on", f'<span class="pill primary chip">{label}</span>'))

total = sum(p.stat().st_size for p in made)
print(f"{len(made)} buttons, {total // 1024} KB total → {OUT}")
