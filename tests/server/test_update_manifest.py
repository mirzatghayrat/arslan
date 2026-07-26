"""packaging/make_update_manifest.py — the auto-update feed (S4.3-a).

Publishing a release IS pushing an update to every installed copy, so a wrong
manifest is not a build failure — it is a bad update shipped to users. The two
mistakes worth spending tests on both LOOK fine:

  * a `latest/` asset URL, which serves whatever the newest release happens to
    hold rather than the artefact this manifest was signed against;
  * an empty manifest, which tells every install "no update exists" and is
    indistinguishable from a successful no-op.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "packaging" / "make_update_manifest.py"
_ASSET = "Arslan-macos-arm64.app.tar.gz"


def _run(dist: pathlib.Path, out: pathlib.Path, *, tag="v1.2.3", version="1.2.3"):
    return subprocess.run(
        [
            sys.executable, str(_SCRIPT),
            "--version", version, "--tag", tag,
            "--repo", "owner/repo",
            "--dist", str(dist), "--out", str(out),
            "--pub-date", "2026-01-01T00:00:00Z",
        ],
        capture_output=True, text=True,
    )


def _stage(dist: pathlib.Path, *, artifact=True, sig=True) -> None:
    dist.mkdir(parents=True, exist_ok=True)
    if artifact:
        (dist / _ASSET).write_bytes(b"tarball")
    if sig:
        (dist / (_ASSET + ".sig")).write_text("SIGNATURE-CONTENT\n")


def test_the_script_exists_where_the_release_workflow_calls_it():
    """Pre-assertion (class 0): the workflow invokes it by path."""
    assert _SCRIPT.is_file()


def test_asset_urls_are_tag_pinned_never_latest(tmp_path):
    """THE assertion. `latest/` would hand installs a binary the signature in
    this very manifest does not cover — during a half-published release, or
    any time a newer release lands before a client polls."""
    dist, out = tmp_path / "dist", tmp_path / "latest.json"
    _stage(dist)

    assert _run(dist, out).returncode == 0
    url = json.loads(out.read_text())["platforms"]["darwin-aarch64"]["url"]

    assert url == f"https://github.com/owner/repo/releases/download/v1.2.3/{_ASSET}"
    assert "/releases/download/v1.2.3/" in url
    assert "/latest/" not in url, "asset URLs must be tag-pinned, not latest"


def test_the_signature_is_carried_from_the_sig_file(tmp_path):
    """A manifest with a missing or wrong signature is refused by the client,
    producing an update prompt that can never succeed."""
    dist, out = tmp_path / "dist", tmp_path / "latest.json"
    _stage(dist)
    _run(dist, out)
    assert json.loads(out.read_text())["platforms"]["darwin-aarch64"]["signature"] == (
        "SIGNATURE-CONTENT"
    )


@pytest.mark.parametrize(
    ("artifact", "sig", "why"),
    [
        (False, True, "artefact missing"),
        (True, False, "signature missing"),
        (False, False, "nothing staged"),
    ],
)
def test_an_empty_manifest_is_refused_rather_than_written(tmp_path, artifact, sig, why):
    """Non-zero exit AND no file. Writing `{"platforms": {}}` would read to
    every installed app as "you are up to date" — a silent failure that looks
    exactly like success."""
    dist, out = tmp_path / "dist", tmp_path / "latest.json"
    _stage(dist, artifact=artifact, sig=sig)

    result = _run(dist, out)

    assert result.returncode != 0, f"should have failed: {why}"
    assert not out.exists(), "no manifest may be written when there is nothing to offer"
    assert "empty manifest" in result.stderr


def test_a_complete_pair_really_does_succeed(tmp_path):
    """Control for the parametrized failures above.

    Without it, an implementation that failed unconditionally would satisfy
    every one of them.
    """
    dist, out = tmp_path / "dist", tmp_path / "latest.json"
    _stage(dist)
    result = _run(dist, out)
    assert result.returncode == 0
    assert out.exists()
    assert json.loads(out.read_text())["platforms"]


def test_the_version_field_is_the_bare_version_not_the_tag(tmp_path):
    """Tauri compares this against the installed app's version string. A
    leading "v" makes every comparison fail, so the app either never updates
    or offers the same update forever."""
    dist, out = tmp_path / "dist", tmp_path / "latest.json"
    _stage(dist)
    _run(dist, out, tag="v1.2.3", version="1.2.3")

    manifest = json.loads(out.read_text())
    assert manifest["version"] == "1.2.3"
    assert not manifest["version"].startswith("v")
    # …while the URL still uses the tag, which DOES carry the v.
    assert "/v1.2.3/" in manifest["platforms"]["darwin-aarch64"]["url"]
