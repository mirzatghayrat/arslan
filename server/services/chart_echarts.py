"""Backend ECharts option builder (no code execution, no LLM-authored config).

The LLM only ever supplies a *normalized intent* (type + labels + numeric series +
a few boolean flags). This module turns that validated intent into a plain-data
ECharts `option` dict that the frontend renders with the trusted echarts library.

🔒 SECURITY: the option is pure JSON data built HERE — never passed through from the
model. No `formatter`/JS functions, no arbitrary keys. Colors/fonts/background come
from the frontend Arslan theme, so options stay palette-agnostic. Validation (type
allowlist, caps, numeric/non-bool values, per-type shape) is the executor's job; this
module assumes a sound shape and focuses on structure.
"""
from __future__ import annotations

CHART_TYPES = {
    "line", "bar", "pie", "scatter", "area", "radar", "funnel", "gauge", "heatmap",
}


def _axis_chart(ctype: str, title: str, x: list[str], series: list[dict],
                *, stacked: bool, horizontal: bool, smooth: bool) -> dict:
    """line / area / bar — category axis + value axis (optionally swapped/stacked)."""
    names = [str(s.get("name") or f"S{i+1}") for i, s in enumerate(series)]
    cat = {"type": "category", "data": x, "boundaryGap": ctype == "bar"}
    val = {"type": "value"}
    base_type = "bar" if ctype == "bar" else "line"
    out_series = []
    for i, s in enumerate(series):
        item: dict = {"name": names[i], "type": base_type,
                      "data": [_num(v) for v in s.get("values", [])]}
        if stacked:
            item["stack"] = "total"
        if base_type == "line" and smooth:
            item["smooth"] = True
        if ctype == "area":
            item["areaStyle"] = {}
            if smooth:
                item["smooth"] = True
        out_series.append(item)
    opt: dict = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": names} if len(names) > 1 else {"show": False},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "series": out_series,
    }
    if horizontal and ctype == "bar":
        opt["xAxis"], opt["yAxis"] = val, cat
    else:
        opt["xAxis"], opt["yAxis"] = cat, val
    return _with_title(opt, title)


def _pie(title: str, x: list[str], series: list[dict]) -> dict:
    vals = series[0].get("values", [])
    data = [{"name": str(x[i]), "value": _num(v)} for i, v in enumerate(vals)]
    return _with_title({
        "tooltip": {"trigger": "item"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [{"name": str(series[0].get("name") or title or "Total"), "type": "pie",
                    "radius": ["35%", "65%"], "avoidLabelOverlap": True, "data": data}],
    }, title)


def _funnel(title: str, x: list[str], series: list[dict]) -> dict:
    vals = series[0].get("values", [])
    data = [{"name": str(x[i]), "value": _num(v)} for i, v in enumerate(vals)]
    return _with_title({
        "tooltip": {"trigger": "item"},
        "legend": {"data": [str(v) for v in x]},
        "series": [{"name": str(series[0].get("name") or title or "Funnel"), "type": "funnel",
                    "left": "10%", "width": "80%", "sort": "descending", "data": data}],
    }, title)


def _gauge(title: str, series: list[dict]) -> dict:
    value = _num(series[0].get("values", [0])[0])
    cap = max(100.0, float(value) * 1.25)
    return _with_title({
        "tooltip": {"formatter": "{b}: {c}"},
        "series": [{"type": "gauge", "min": 0, "max": cap,
                    "data": [{"value": value, "name": str(series[0].get("name") or title or "")}]}],
    }, title)


def _radar(title: str, x: list[str], series: list[dict]) -> dict:
    max_per = []
    for j in range(len(x)):
        col = [_num(s.get("values", [])[j]) for s in series if j < len(s.get("values", []))]
        max_per.append(max(col) * 1.2 if col else 1)
    indicator = [{"name": str(x[j]), "max": max_per[j]} for j in range(len(x))]
    data = [{"name": str(s.get("name") or f"S{i+1}"),
             "value": [_num(v) for v in s.get("values", [])]} for i, s in enumerate(series)]
    return _with_title({
        "tooltip": {"trigger": "item"},
        "legend": {"data": [d["name"] for d in data]} if len(data) > 1 else {"show": False},
        "radar": {"indicator": indicator},
        "series": [{"type": "radar", "data": data}],
    }, title)


def _scatter(title: str, x: list[str], series: list[dict]) -> dict:
    def xv(i: int):
        try:
            return float(x[i])
        except (TypeError, ValueError):
            return i
    out_series = []
    for k, s in enumerate(series):
        pts = [[xv(i), _num(v)] for i, v in enumerate(s.get("values", []))]
        out_series.append({"name": str(s.get("name") or f"S{k+1}"), "type": "scatter", "data": pts})
    names = [s["name"] for s in out_series]
    return _with_title({
        "tooltip": {"trigger": "item"},
        "legend": {"data": names} if len(names) > 1 else {"show": False},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "series": out_series,
    }, title)


def _heatmap(title: str, x: list[str], y: list[str], series: list[dict]) -> dict:
    data, vmin, vmax = [], None, None
    for i, s in enumerate(series):              # row i ↔ y[i]
        for j, v in enumerate(s.get("values", [])):
            n = _num(v)
            data.append([j, i, n])
            vmin = n if vmin is None else min(vmin, n)
            vmax = n if vmax is None else max(vmax, n)
    return _with_title({
        "tooltip": {"position": "top"},
        "xAxis": {"type": "category", "data": [str(v) for v in x], "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": [str(v) for v in y], "splitArea": {"show": True}},
        "visualMap": {"min": vmin if vmin is not None else 0, "max": vmax if vmax is not None else 1,
                      "calculable": True, "orient": "horizontal", "left": "center", "bottom": "2%"},
        "grid": {"height": "60%", "top": "12%", "containLabel": True},
        "series": [{"type": "heatmap", "data": data, "label": {"show": len(data) <= 60}}],
    }, title)


def _num(v):
    """Coerce a validated numeric to int/float (executor already excluded bool/non-numeric)."""
    f = float(v)
    return int(f) if f.is_integer() else f


def _with_title(opt: dict, title: str) -> dict:
    if title:
        opt = {"title": {"text": title, "left": "center"}, **opt}
    return opt


def build_option(spec: dict) -> dict:
    """Build an ECharts option from a *validated* normalized intent.

    spec = {type, title, x, series:[{name,values}], y?, stacked?, horizontal?, smooth?}
    """
    ctype = spec["type"]
    title = str(spec.get("title") or "").strip()
    x = [str(v) for v in spec.get("x") or []]
    series = spec["series"]
    stacked = bool(spec.get("stacked"))
    horizontal = bool(spec.get("horizontal"))
    smooth = bool(spec.get("smooth"))

    if ctype in ("line", "bar", "area"):
        return _axis_chart(ctype, title, x, series, stacked=stacked, horizontal=horizontal, smooth=smooth)
    if ctype == "pie":
        return _pie(title, x, series)
    if ctype == "funnel":
        return _funnel(title, x, series)
    if ctype == "gauge":
        return _gauge(title, series)
    if ctype == "radar":
        return _radar(title, x, series)
    if ctype == "scatter":
        return _scatter(title, x, series)
    if ctype == "heatmap":
        return _heatmap(title, x, [str(v) for v in spec.get("y") or []], series)
    raise ValueError(f"unhandled chart type {ctype!r}")
