"""The acceptance probe must be able to FAIL. Spec §4, acceptance clause ②.

A probe is a claim about the shipped product, and an unfalsifiable claim is
worth nothing. The clause the user wrote is explicit about the mutation shape:
"if the probe stays green after Vision is taken away, the probe has no
discriminating power". Rebuilding a bundle to test that would cost five minutes
per assertion, so the probe's decision logic is exercised here directly.

Two failure modes are pinned, and they are different:
  - the recogniser produced nothing  -> the probe must go RED
  - the host has third-party OCR     -> the probe must go RED *by name*, and
                                        must NOT proceed to make the claim
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

SPEC = pathlib.Path(__file__).resolve().parents[1] / "packaging" / "fresh_install_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("fresh_install_check", SPEC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fresh_install_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fic():
    return _load()


class _Resp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _clean_host(fic, monkeypatch):
    monkeypatch.setattr(fic.sys, "platform", "darwin")
    monkeypatch.setattr(fic.shutil, "which", lambda name: None)


def test_the_probe_goes_red_when_nothing_is_recognised(fic, monkeypatch):
    """The Vision-is-missing case, which is what a broken bundle looks like
    from the outside: /extract answers 200 with no text."""
    _clean_host(fic, monkeypatch)
    monkeypatch.setattr(fic.urllib.request, "urlopen",
                        lambda *a, **k: _Resp({"text": "", "chars": 0}))

    c = fic.Checks()
    fic._check_ocr(1234, "tok", c)

    assert c.failures, "a bundle that recognised nothing was reported as fine"
    assert any("reads English" in f for f in c.failures), c.failures


def test_the_probe_goes_green_only_on_the_actual_words(fic, monkeypatch):
    """Discriminating twin: non-empty text is NOT enough.

    An echoed filename or a truncated read would satisfy len(text) > 0, so the
    assertion is on the words that were drawn onto the pixels."""
    _clean_host(fic, monkeypatch)

    monkeypatch.setattr(fic.urllib.request, "urlopen",
                        lambda *a, **k: _Resp({"text": "probe.png", "chars": 9}))
    c = fic.Checks()
    fic._check_ocr(1234, "tok", c)
    assert c.failures, "a filename echo passed for recognised text"

    monkeypatch.setattr(fic.urllib.request, "urlopen",
                        lambda *a, **k: _Resp({"text": fic.OCR_PROBE_EN, "chars": 25}))
    c = fic.Checks()
    fic._check_ocr(1234, "tok", c)
    assert not c.failures, c.failures


def test_a_host_with_homebrew_ocr_is_refused_by_name_not_skipped(fic, monkeypatch):
    """The (0) precondition, and the reason it is a FAILURE rather than a skip.

    A skip reads as "checked, fine" in a green run. The developer machine this
    was written on has Homebrew tesseract, so a probe that skipped there would
    have been silently unexercised for as long as nobody looked."""
    monkeypatch.setattr(fic.sys, "platform", "darwin")
    monkeypatch.setattr(fic.shutil, "which",
                        lambda name: "/opt/homebrew/bin/tesseract"
                        if name == "tesseract" else None)
    called = []
    monkeypatch.setattr(fic.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1) or _Resp({"text": fic.OCR_PROBE_EN}))

    c = fic.Checks()
    fic._check_ocr(1234, "tok", c)

    assert any("third-party OCR" in f for f in c.failures), c.failures
    assert "tesseract" in " ".join(c.failures), "the reason was not named"
    # And it stops: making the claim on a host that could have borrowed the
    # capability is the failure this precondition exists to prevent.
    assert called == [], "the probe made its claim on a dirty host"
