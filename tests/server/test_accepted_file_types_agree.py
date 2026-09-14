"""The file picker must not offer what the server will refuse.

The failure this prevents is small and infuriating: the picker lets you choose
a .bmp or a .doc, you drop it in, and the request comes back 400 "unsupported
file type". Nothing is wrong with either side on its own — they simply never
agreed, and nothing made them.

Both pickers now use a shared format declaration. Verify their wiring, compare
the backend's loaded declaration, and exercise its actual dispatch for every
declared extension. Parser fidelity has separate binary-fixture tests.
"""
from __future__ import annotations

import pathlib
import re
import json
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BRAIN_NAV = ROOT / "web" / "src" / "components" / "brain" / "BrainNav.tsx"
COMPOSER = ROOT / "web" / "src" / "components" / "ComposerAttach.tsx"
FORMAT_PATH = ROOT / "web/src/lib/input_formats.json"
FORMATS = json.loads(FORMAT_PATH.read_text())


def _accept_list(source: pathlib.Path, symbol: str) -> set[str]:
    text = source.read_text()
    assert re.search(r'import\s*\{[^}]*\bINPUT_ACCEPT\b[^}]*\}\s*from\s*[\"\'][^\"\']*/lib/inputFormats[\"\']', text)
    assert re.search(r'accept\s*=\s*\{\s*' + symbol + r'\s*\}', text)
    if symbol != "INPUT_ACCEPT":
        assert re.search(r'const\s+' + symbol + r'\s*=\s*INPUT_ACCEPT\s*;', text)
    # image/* in the common chooser covers the declared image family. A host
    # decoder may still reject an individual codec/file; that is not success.
    return {"." + ext for values in FORMATS.values() if isinstance(values, list) for ext in values}


def _backend_extensions() -> set[str]:
    from server.services import input_formats
    assert input_formats.REGISTRY == FORMATS, "packaged/backend declaration drifted"
    return {"." + ext for values in input_formats.REGISTRY.values() if isinstance(values, list) for ext in values}


def test_the_second_brain_picker_offers_nothing_the_server_refuses():
    offered = _accept_list(BRAIN_NAV, "INPUT_ACCEPT")
    handled = _backend_extensions()
    unsupported = offered - handled
    assert not unsupported, (
        f"the second-brain picker offers {sorted(unsupported)}, which "
        f"_extract_file refuses with 400. Handled: {sorted(handled)}")


def test_the_chat_composer_offers_nothing_the_server_refuses():
    offered = _accept_list(COMPOSER, "ATTACH_ACCEPT")
    handled = _backend_extensions()
    unsupported = offered - handled
    assert not unsupported, (
        f"the composer offers {sorted(unsupported)}, which _extract_file "
        f"refuses with 400. Handled: {sorted(handled)}")


def test_the_reader_actually_finds_something():
    """(0) pre-assertion. Both tests above pass trivially if either reader
    returns an empty set — an accept list that parsed to nothing is a subset of
    everything, and a backend set that swallowed everything hides all gaps."""
    assert len(_accept_list(BRAIN_NAV, "INPUT_ACCEPT")) >= 8
    assert len(_backend_extensions()) >= 8


@pytest.mark.parametrize("ext", ["." + ext for ext in FORMATS["image"]])
def test_every_image_type_the_pickers_offer_is_recognised_as_an_image(ext):
    """Not merely "not refused": an image must take the IMAGE branch, or it
    would fall through to the unsupported-type error despite being listed."""
    from server.services import ingest

    assert ingest._IMAGE_EXT_RE.search(f"photo{ext}"), (
        f"{ext} is offered by the pickers but is not an image to the backend")


@pytest.mark.parametrize("category,extension", [(category, ext) for category, values in FORMATS.items()
    if isinstance(values, list) for ext in values])
def test_every_declared_extension_reaches_its_real_dispatch_branch(monkeypatch, category, extension):
    import docx
    import lxml.html
    from server.services import ingest, input_formats

    expected = f"{category}-reader:" * 4
    called = []
    def structured(name, data):
        called.append(input_formats.kind(name))
        return expected, False
    def video(name, data):
        called.append("video")
        return {"reader": expected}
    def image(data, **kwargs):
        called.append("image")
        return expected, "ok"
    monkeypatch.setattr(input_formats, "read_structured", structured)
    monkeypatch.setattr(input_formats, "video_metadata", video)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: called.append("document") or expected)
    monkeypatch.setattr(docx, "Document", lambda data: called.append("document") or SimpleNamespace(paragraphs=[SimpleNamespace(text=expected)]))
    monkeypatch.setattr(lxml.html, "fromstring", lambda data: called.append("document") or SimpleNamespace(text_content=lambda: expected))
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    monkeypatch.setattr(ingest.ocr_fallback, "read_locally", image)
    result = ingest._extract_file(f"input.{extension.upper()}", expected.encode())
    assert expected in result
    assert called == ([] if extension in {"txt", "md"} else [category])


def test_undeclared_extensions_are_not_silently_accepted():
    from server.services import ingest
    for extension in ("exe", "xlsm", "doc", "unknown"):
        with pytest.raises(ValueError, match="unsupported file type"):
            ingest._extract_file(f"input.{extension}", b"not supported")
