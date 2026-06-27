import pytest
from server.services import chart_svg


def test_line_chart_produces_svg():
    spec = {"type": "line", "title": "Trend",
            "x": ["Jan", "Feb", "Mar"],
            "series": [{"name": "A", "values": [1, 3, 2]}]}
    svg = chart_svg.render(spec)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "Trend" in svg
    assert "Jan" in svg and "Mar" in svg
    assert "polyline" in svg or "<path" in svg


def test_bar_chart_produces_rects():
    spec = {"type": "bar", "title": "Counts",
            "x": ["a", "b"], "series": [{"name": "S", "values": [2, 5]}]}
    svg = chart_svg.render(spec)
    assert svg.startswith("<svg")
    assert svg.count("<rect") >= 2


def test_pie_chart_produces_paths():
    spec = {"type": "pie", "title": "Share",
            "x": ["x", "y", "z"], "series": [{"name": "S", "values": [1, 1, 2]}]}
    svg = chart_svg.render(spec)
    assert svg.startswith("<svg")
    assert svg.count("<path") >= 3


def test_xml_escaping_in_labels_and_title():
    spec = {"type": "bar", "title": "A & B <x>",
            "x": ["<i>", "p&q"], "series": [{"name": "n", "values": [1, 2]}]}
    svg = chart_svg.render(spec)
    assert "<i>" not in svg.replace("<svg", "")   # the label '<i>' must be escaped, not literal
    assert "&amp;" in svg
    assert "&lt;" in svg


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        chart_svg.render({"type": "donut", "x": ["a"], "series": [{"name": "s", "values": [1]}]})
