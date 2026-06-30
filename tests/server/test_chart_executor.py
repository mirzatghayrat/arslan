import pytest
from server.registry.executors import ChartExecutor


async def test_valid_line_spec_returns_echarts_artifact():
    out = await ChartExecutor().execute({
        "type": "line", "title": "T", "x": ["a", "b", "c"],
        "series": [{"name": "S", "values": [1, 2, 3]}]})
    assert out["ok"] is True
    assert out["external"] is False
    # new contract: a backend-built ECharts option spec, not a raw SVG string
    assert out["artifact"]["kind"] == "echarts"
    spec = out["artifact"]["spec"]
    assert isinstance(spec, dict)
    assert spec["series"][0]["type"] == "line"
    assert spec["series"][0]["data"] == [1, 2, 3]
    assert spec["xAxis"]["data"] == ["a", "b", "c"]
    assert spec["title"]["text"] == "T"
    assert "summary" in out and out["summary"]


async def test_spec_is_pure_json_data():
    # 🔒 the option must be plain JSON-serializable data (no functions / callables)
    import json
    out = await ChartExecutor().execute({
        "type": "bar", "x": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]})
    json.dumps(out["artifact"]["spec"])  # raises if any value is non-serializable


async def test_each_new_type_builds():
    base = {"x": ["a", "b", "c"], "series": [{"name": "s", "values": [1, 2, 3]}]}
    for ctype in ("bar", "area", "scatter", "pie", "funnel", "radar"):
        out = await ChartExecutor().execute({**base, "type": ctype})
        assert out["ok"] is True, ctype
        assert out["artifact"]["kind"] == "echarts"
        assert "series" in out["artifact"]["spec"]


async def test_gauge_needs_no_x():
    out = await ChartExecutor().execute({"type": "gauge", "series": [{"name": "load", "values": [72]}]})
    assert out["ok"] is True
    assert out["artifact"]["spec"]["series"][0]["type"] == "gauge"


async def test_heatmap_requires_aligned_y():
    ok = await ChartExecutor().execute({
        "type": "heatmap", "x": ["m", "t"], "y": ["r1", "r2"],
        "series": [{"name": "r1", "values": [1, 2]}, {"name": "r2", "values": [3, 4]}]})
    assert ok["ok"] is True and ok["artifact"]["spec"]["series"][0]["type"] == "heatmap"
    missing_y = await ChartExecutor().execute({
        "type": "heatmap", "x": ["m", "t"], "series": [{"name": "r1", "values": [1, 2]}]})
    assert missing_y["ok"] is False and "y" in missing_y["error"].lower()


async def test_pie_requires_x_value_alignment():
    out = await ChartExecutor().execute({
        "type": "pie", "x": ["a", "b", "c"], "series": [{"name": "s", "values": [1, 2]}]})
    assert out["ok"] is False and "align" in out["error"].lower()


async def test_unknown_type_rejected():
    out = await ChartExecutor().execute({"type": "donut", "x": ["a"], "series": [{"name": "s", "values": [1]}]})
    assert out["ok"] is False and "type" in out["error"].lower()


async def test_too_many_points_rejected():
    out = await ChartExecutor().execute({
        "type": "bar", "x": [str(i) for i in range(999)],
        "series": [{"name": "s", "values": [1] * 999}]})
    assert out["ok"] is False


async def test_non_numeric_values_rejected():
    out = await ChartExecutor().execute({
        "type": "bar", "x": ["a", "b"], "series": [{"name": "s", "values": [1, "oops"]}]})
    assert out["ok"] is False


async def test_empty_series_rejected():
    out = await ChartExecutor().execute({"type": "line", "x": ["a"], "series": []})
    assert out["ok"] is False


async def test_bool_values_rejected():
    # bool ⊂ int — the numeric check must exclude booleans (named spec invariant)
    out = await ChartExecutor().execute({
        "type": "bar", "x": ["a", "b"], "series": [{"name": "s", "values": [True, False]}]})
    assert out["ok"] is False


async def test_series_values_cap_independent():
    # valid-length x but an over-cap series exercises the per-series cap branch on its own
    out = await ChartExecutor().execute({
        "type": "line", "x": ["a", "b", "c"], "series": [{"name": "s", "values": [1] * 51}]})
    assert out["ok"] is False
