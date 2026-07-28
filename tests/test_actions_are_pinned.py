"""Third-party GitHub Actions must be pinned to a commit, not a moving tag.

A tag is a pointer its owner can move. `uses: someone/action@v2` therefore says
"run whatever that account puts there at the moment our release builds" — and
this repository's release job holds the signing certificate, the notarisation
credentials and the updater's private key. A moved tag is the cheapest possible
supply-chain compromise, and it leaves no trace in our history.

GitHub's own actions/* are exempt, deliberately: they are published by the same
party that runs the workflow, so pinning them buys nothing against this threat
while adding churn.
"""
from __future__ import annotations

import pathlib
import re

import pytest

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parents[1]
                    / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.M)
SHA = re.compile(r"^[0-9a-f]{40}$")
FIRST_PARTY = ("actions/", "github/")


def _third_party_uses():
    for wf in WORKFLOWS:
        for ref in USES.findall(wf.read_text()):
            if ref.startswith(FIRST_PARTY) or ref.startswith("./"):
                continue
            yield wf.name, ref


def test_there_are_workflows_to_check():
    """(0) pre-assertion: a glob that matched nothing would make the test below
    vacuously true, which is the same shape as having no check at all."""
    assert WORKFLOWS, "no workflow files found"
    assert list(_third_party_uses()), "no third-party actions found to check"


@pytest.mark.parametrize("wf,ref", list(_third_party_uses()),
                         ids=lambda v: str(v).replace("/", "_"))
def test_every_third_party_action_is_pinned_to_a_commit(wf, ref):
    _, _, version = ref.partition("@")
    assert SHA.match(version), (
        f"{wf}: {ref} is pinned to a movable tag. Resolve it with\n"
        f"  gh api repos/{ref.partition('@')[0]}/commits/{version} -q .sha\n"
        f"and keep the tag as a trailing comment so the intent stays readable.")


def test_the_pins_keep_a_human_readable_tag_comment():
    """A bare 40-character hex string tells the next reader nothing about which
    release it is. The comment is not decoration — without it, deciding whether
    a pin is stale means resolving every SHA by hand."""
    for wf in WORKFLOWS:
        for line in wf.read_text().splitlines():
            m = re.match(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)\s*(#.*)?$", line)
            if not m:
                continue
            ref, comment = m.group(1), m.group(2)
            if ref.startswith(FIRST_PARTY) or ref.startswith("./"):
                continue
            if SHA.match(ref.partition("@")[2]):
                assert comment and comment.strip("# ").strip(), (
                    f"{wf.name}: {ref} is pinned but unlabelled — add '# <tag>'")
