"""Writes the 24 HTML frames the demo GIF is assembled from.

Four real client screens, each held and then dissolved into the next in five
opacity steps. The dissolve lives here rather than in ffmpeg because the
vendored build has no xfade filter (see build.sh).
"""

SLIDES = [
    ("../../assets/site/adf2aaecbf0.jpg", "01", "You ask once"),
    ("../../assets/site/a8231dc73ee.jpg", "02", "It routes to the roster you raised"),
    ("../../assets/site/a01391bbd3d.jpg", "03", "Spawns read the second brain"),
    ("../../assets/site/ac17ffb11aa.jpg", "04", "Every run is on the record"),
]

HEAD = """<meta charset="utf-8">
<style>
@font-face{font-family:Plex;src:url(fonts/ibm-plex-mono-600.woff2) format('woff2');font-weight:600}
@font-face{font-family:Inter;src:url(fonts/inter-variable.woff2) format('woff2');font-weight:100 900}
*{box-sizing:border-box;margin:0}
body{width:1400px;height:960px;overflow:hidden;background:#F6EBD6;font-family:Inter,sans-serif;position:relative}
.stack{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:30px;background:#F6EBD6}
.mon{width:1240px;background:#E2DFD7;border-radius:26px;padding:14px;
  box-shadow:inset 6px 8px 18px rgba(255,255,255,.32),inset -8px -10px 20px rgba(0,0,0,.16),16px 22px 44px rgba(20,10,4,.28)}
.mon img{width:100%;display:block;border-radius:14px}
.cap{font-family:Plex;font-weight:600;font-size:26px;letter-spacing:.16em;text-transform:uppercase;color:#7A5C2E}
.cap i{font-style:normal;color:#C9992C;margin-right:14px}
</style>
"""


def stack(img, num, cap, opacity=None):
    style = "" if opacity is None else f' style="opacity:{opacity}"'
    return (
        f'<div class="stack"{style}><div class="mon"><img src="{img}"></div>'
        f'<div class="cap"><i>{num}</i>{cap}</div></div>'
    )


n = 0
for i, (img, num, cap) in enumerate(SLIDES):
    with open(f"f{n:03d}.html", "w") as fh:
        fh.write(HEAD + stack(img, num, cap))
    n += 1
    nxt = SLIDES[(i + 1) % len(SLIDES)]
    for opacity in (0.17, 0.34, 0.5, 0.66, 0.83):
        with open(f"f{n:03d}.html", "w") as fh:
            fh.write(HEAD + stack(img, num, cap) + stack(*nxt, opacity=opacity))
        n += 1
print(f"{n} html frames")
