import pytest
from server.registry.executors import ChartExecutor


async def test_valid_line_spec_returns_artifact():
    out = await ChartExecutor().execute({
        "type": "line", "title": "T", "x": ["a", "b", "c"],
        "series": [{"name": "S", "values": [1, 2, 3]}]})
    assert out["ok"] is True
    assert out["external"] is False
    assert out["artifact"]["kind"] == "svg"
    assert out["artifact"]["content"].startswith("<svg")
    assert "summary" in out and out["summary"]


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
