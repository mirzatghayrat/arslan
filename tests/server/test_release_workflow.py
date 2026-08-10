"""Guards on the release workflow itself (S4.3-a §4, §7).

Two properties here are not testable by running the workflow — by the time it
runs, the damage is done — so they are asserted against the file:

  * a tag that disagrees with tauri.conf.json's version would publish an
    update every installed copy fetches and can never apply, because the
    version it announces never matches what it installs;
  * a workflow triggered by `pull_request` that references `secrets.*` hands
    the signing certificate to anyone who opens a PR from a fork.

The drift check is not asserted by grepping for its text. The shell snippet is
EXTRACTED from the workflow and EXECUTED, once with a matching tag and once
with a mismatching one, so a snippet that has been broken into a no-op fails
here rather than passing a string match.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess

import pytest

_WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
_RELEASE = _WORKFLOWS / "release.yml"
_CONF = (
    pathlib.Path(__file__).resolve().parents[2]
    / "desktop" / "src-tauri" / "tauri.conf.json"
)


def test_the_release_workflow_and_config_exist():
    """Pre-assertion (class 0): every check below is vacuous if these moved."""
    assert _RELEASE.is_file()
    assert _CONF.is_file()


def _drift_snippet() -> str:
    """Pull the tag/version comparison out of the workflow, verbatim."""
    text = _RELEASE.read_text()
    m = re.search(
        r'(TAG="\$\{GITHUB_REF_NAME\}".*?\n\s*fi\n)', text, re.S
    )
    assert m, "the tag/version drift check is gone from release.yml"
    # De-indent so bash sees a normal script.
    lines = [ln[10:] if ln.startswith(" " * 10) else ln for ln in m.group(1).splitlines()]
    return "\n".join(lines)


@pytest.mark.parametrize("case", ["match", "patch_ahead", "way_off"])
def test_the_drift_check_accepts_only_a_matching_tag(tmp_path, case):
    """Both directions, derived from the REAL config version.

    An earlier revision hardcoded "v0.1.0" as the matching tag, with a
    self-check that demanded editing the test on every version bump — which
    promptly fired on the 0.1.1 bump and failed CI on a branch with zero
    backend changes. Deriving the tags from tauri.conf.json keeps the same
    discrimination (a matching tag passes, a mismatching one is rejected)
    with no per-release maintenance.

    NOT tested: a tag without the "v" prefix — `${TAG#v}` leaves it unchanged
    so it compares equal, but the workflow only triggers on tags: ["v*"] and
    the release job requires startsWith(github.ref, 'refs/tags/v'), so that
    input cannot reach this code.
    """
    version = json.loads(_CONF.read_text())["version"]
    parts = version.split(".")
    bumped = ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])
    tag, should_fail = {
        "match": (f"v{version}", False),
        # The realistic mistake: tag the release, forget to bump the config.
        "patch_ahead": (f"v{bumped}", True),
        "way_off": ("v9.9.9", True),
    }[case]
    assert (tag == f"v{version}") == (not should_fail)  # the cases really differ

    conf_dir = tmp_path / "desktop" / "src-tauri"
    conf_dir.mkdir(parents=True)
    (conf_dir / "tauri.conf.json").write_text(json.dumps({"version": version}))

    result = subprocess.run(
        ["bash", "-c", _drift_snippet()],
        cwd=tmp_path, env={"GITHUB_REF_NAME": tag, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    if should_fail:
        assert result.returncode != 0, f"tag {tag} should have been rejected"
        assert "::error::" in result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


def test_no_pull_request_triggered_workflow_can_read_secrets():
    """THE fork-PR guard.

    A workflow that both runs on `pull_request` and references `secrets.*` lets
    anyone who opens a PR from a fork exfiltrate the signing certificate — the
    PR can edit the very workflow that uses it. GitHub withholds secrets from
    fork PRs by default, but `pull_request_target` does not, and the default is
    a setting rather than a property of this repository.

    Checks every workflow, not just release.yml: the next one added is the one
    that gets this wrong.
    """
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        text = wf.read_text()
        # The trigger block ends at the first top-level key after `on:`.
        m = re.search(r"^on:\s*\n(.*?)^\w", text, re.S | re.M)
        triggers = m.group(1) if m else ""
        pr_triggered = "pull_request" in triggers
        # GITHUB_TOKEN is scoped to the PR and is not ours to leak.
        uses = [
            s for s in re.findall(r"secrets\.([A-Z_0-9]+)", text) if s != "GITHUB_TOKEN"
        ]
        if pr_triggered and uses:
            offenders.append(f"{wf.name} runs on pull_request AND reads {sorted(set(uses))}")

    assert not offenders, "; ".join(offenders)


def test_the_release_workflow_really_does_use_secrets():
    """Control for the test above.

    Without it, deleting every secret reference — which would produce unsigned
    releases — would make the fork-PR test pass for the wrong reason.
    """
    used = set(re.findall(r"secrets\.([A-Z_0-9]+)", _RELEASE.read_text()))
    assert {"APPLE_CERTIFICATE", "APPLE_SIGNING_IDENTITY", "TAURI_SIGNING_PRIVATE_KEY"} <= used


def test_releases_are_drafts_not_published_automatically():
    """Publishing IS pushing an update to every install. A human reviews first
    — the same fail-closed-on-the-executing-side rule as the rest of the repo.
    """
    assert re.search(r"^\s*draft:\s*true\s*$", _RELEASE.read_text(), re.M)


# The updater public key that every shipped binary is built with. Changing it
# is not a config edit — it is a decision to strand every existing install,
# because the updater verifies each artefact against the key COMPILED INTO the
# running app and nothing teaches an old binary a new key (we register the
# plugin without the runtime-pubkey override that exists for that purpose).
_PINNED_PUBKEY_SHA256 = "6ef633c5da1cce154e5f49c155e4b1cdf7549cc0af8b9c2a6d4d52efb470df62"


def test_the_updater_pubkey_has_not_changed():
    """A well-formed WRONG key is the failure this pins.

    build_dmg.sh already refuses a pubkey that is not the base64 content of a
    .pub file — but that checks SHAPE. Any other valid key passes it, builds,
    signs, notarizes, and ships; the damage only becomes visible when installs
    that will never update again fail to update, silently, by design.

    Rotating on purpose means editing this hash too, and docs/RELEASE_KEYS.md
    says what that costs. The point is that it cannot happen by accident.
    """
    pubkey = json.loads(_CONF.read_text())["plugins"]["updater"]["pubkey"].strip()
    actual = hashlib.sha256(pubkey.encode()).hexdigest()
    assert actual == _PINNED_PUBKEY_SHA256, (
        "the updater public key changed. If this was deliberate, every copy "
        "installed before the next release is stranded on its current version "
        "and must be reinstalled by hand — see docs/RELEASE_KEYS.md — and this "
        f"pin becomes {actual}. If it was not deliberate, do not ship."
    )
