"""Pure-Python SVG chart builder (no deps, no code execution).

Renders a restricted, pre-validated chart spec to an SVG string. Validation of the
spec (type whitelist, caps, numeric values) is the executor's job; this module assumes
the spec shape is sound and focuses on drawing. All user text is XML-escaped."""
from __future__ import annotations

from xml.sax.saxutils import escape

_W, _H = 640, 400
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 56, 24, 40, 48
_PALETTE = ["#4f8ef7", "#f7934f", "#54c08a", "#c0548a", "#8a7be0", "#e0c64f", "#54b6c0", "#c05454"]


def _esc(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def _text(x, y, s, *, size=12, anchor="middle", color="#333", weight="normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{color}" font-weight="{weight}" font-family="sans-serif">{_esc(s)}</text>')


def _frame(title: str, body: str) -> str:
    head = _text(_W / 2, 24, title, size=15, weight="bold") if title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}" width="100%">'
            f'<rect width="{_W}" height="{_H}" fill="#ffffff"/>{head}{body}</svg>')


def _plot_box():
    x0, y0 = _PAD_L, _PAD_T
    w, h = _W - _PAD_L - _PAD_R, _H - _PAD_T - _PAD_B
    return x0, y0, w, h


def _all_values(series) -> list[float]:
    return [float(v) for s in series for v in s["values"]] or [0.0]


def render_line(spec: dict) -> str:
    x0, y0, w, h = _plot_box()
    xs, series = spec["x"], spec["series"]
    vmax = max(_all_values(series) + [0.0]) or 1.0
    n = max(len(xs), 1)
    def px(i): return x0 + (w * (i / (n - 1))) if n > 1 else x0 + w / 2
    def py(v): return y0 + h - (h * (float(v) / vmax))
    body = [f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" stroke="#ccc"/>',
            f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0+h}" stroke="#ccc"/>']
    for i, lbl in enumerate(xs):
        body.append(_text(px(i), y0 + h + 16, lbl, size=10, color="#666"))
    for si, s in enumerate(series):
        color = _PALETTE[si % len(_PALETTE)]
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(s["values"]))
        body.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        body.append(_text(x0 + w, y0 + 12 + si * 14, s["name"], size=10, anchor="end", color=color))
    return _frame(spec.get("title", ""), "".join(body))


def render_bar(spec: dict) -> str:
    x0, y0, w, h = _plot_box()
    xs, series = spec["x"], spec["series"]
    vmax = max(_all_values(series) + [0.0]) or 1.0
    n = max(len(xs), 1)
    groups = len(series)
    slot = w / n
    bw = slot / (groups + 1)
    body = [f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" stroke="#ccc"/>']
    for i, lbl in enumerate(xs):
        cx = x0 + slot * i + slot / 2
        body.append(_text(cx, y0 + h + 16, lbl, size=10, color="#666"))
        for si, s in enumerate(series):
            v = float(s["values"][i]) if i < len(s["values"]) else 0.0
            bh = h * (v / vmax)
            bx = x0 + slot * i + bw * (si + 0.5)
            color = _PALETTE[si % len(_PALETTE)]
            body.append(f'<rect x="{bx:.1f}" y="{y0+h-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}"/>')
    for si, s in enumerate(series):
        body.append(_text(x0 + w, y0 + 12 + si * 14, s["name"], size=10, anchor="end",
                          color=_PALETTE[si % len(_PALETTE)]))
    return _frame(spec.get("title", ""), "".join(body))


def render_pie(spec: dict) -> str:
    import math
    xs = spec["x"]
    vals = [float(v) for v in spec["series"][0]["values"]]
    total = sum(vals) or 1.0
    cx, cy, r = _W / 2, _H / 2 + 10, 120
    legend_x = _W - 120
    body, angle = [], -math.pi / 2
    for i, v in enumerate(vals):
        frac = v / total
        a2 = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        color = _PALETTE[i % len(_PALETTE)]
        body.append(f'<path d="M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} '
                    f'A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>')
        lbl = xs[i] if i < len(xs) else ""
        body.append(_text(legend_x, 60 + i * 16, f"{lbl} ({v:g})", size=10, anchor="start", color=color))
        angle = a2
    return _frame(spec.get("title", ""), "".join(body))


_RENDERERS = {"line": render_line, "bar": render_bar, "pie": render_pie}


def render(spec: dict) -> str:
    fn = _RENDERERS.get(spec.get("type"))
    if fn is None:
        raise ValueError(f"unknown chart type: {spec.get('type')!r}")
    return fn(spec)
