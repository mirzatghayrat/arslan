"""The file picker must not offer what the server will refuse.

The failure this prevents is small and infuriating: the picker lets you choose
a .bmp or a .doc, you drop it in, and the request comes back 400 "unsupported
file type". Nothing is wrong with either side on its own — they simply never
agreed, and nothing made them.

So this reads the picker's `accept` list out of the frontend source and the
handled branches out of ingest.py, and asserts the first is a subset of the
second. Reading both rather than restating either is the point: a copy of the
list here would be a third thing to drift.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BRAIN_NAV = ROOT / "web" / "src" / "components" / "brain" / "BrainNav.tsx"
COMPOSER = ROOT / "web" / "src" / "components" / "ComposerAttach.tsx"
INGEST = ROOT / "server" / "services" / "ingest.py"


def _accept_list(source: pathlib.Path, pattern: str) -> set[str]:
    m = re.search(pattern, source.read_text())
    assert m, f"could not find the accept list in {source.name} — pattern {pattern!r}"
    return {
        part.strip().lower()
        for part in m.group(1).split(",")
        if part.strip().startswith(".")
    }


def _backend_extensions() -> set[str]:
    """Extensions _extract_file actually branches on, read from the source."""
    text = INGEST.read_text()
    body = text[text.index("def _extract_file("):]
    body = body[: body.index("raise ValueError")]

    exts = set(re.findall(r'endswith\(\s*"(\.[a-z0-9]+)"', body))
    exts |= set(re.findall(r'"(\.[a-z0-9]+)"', "".join(
        re.findall(r"endswith\(\((.*?)\)\)", body, re.S))))

    # The image branch delegates to a regex; read it from where it is defined.
    m = re.search(r'_IMAGE_EXT_RE = re\.compile\(r"\\\.\((.*?)\)\$"', text)
    assert m, "could not read _IMAGE_EXT_RE"
    for alt in m.group(1).split("|"):
        # jpe?g -> .jpg and .jpeg
        if "?" in alt:
            exts.add("." + alt.replace("e?", ""))
            exts.add("." + alt.replace("?", ""))
        else:
            exts.add("." + alt)
    return exts


def test_the_second_brain_picker_offers_nothing_the_server_refuses():
    offered = _accept_list(BRAIN_NAV, r'accept="([^"]+)"')
    handled = _backend_extensions()
    unsupported = offered - handled
    assert not unsupported, (
        f"the second-brain picker offers {sorted(unsupported)}, which "
        f"_extract_file refuses with 400. Handled: {sorted(handled)}")


def test_the_chat_composer_offers_nothing_the_server_refuses():
    offered = _accept_list(COMPOSER, r'ATTACH_ACCEPT = "([^"]+)"')
    handled = _backend_extensions()
    unsupported = offered - handled
    assert not unsupported, (
        f"the composer offers {sorted(unsupported)}, which _extract_file "
        f"refuses with 400. Handled: {sorted(handled)}")


def test_the_reader_actually_finds_something():
    """(0) pre-assertion. Both tests above pass trivially if either reader
    returns an empty set — an accept list that parsed to nothing is a subset of
    everything, and a backend set that swallowed everything hides all gaps."""
    assert len(_accept_list(BRAIN_NAV, r'accept="([^"]+)"')) >= 8
    assert len(_backend_extensions()) >= 8


@pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"])
def test_every_image_type_the_pickers_offer_is_recognised_as_an_image(ext):
    """Not merely "not refused": an image must take the IMAGE branch, or it
    would fall through to the unsupported-type error despite being listed."""
    from server.services import ingest

    assert ingest._IMAGE_EXT_RE.search(f"photo{ext}"), (
        f"{ext} is offered by the pickers but is not an image to the backend")
