"""THROWAWAY PROBE — never merge. Deliberately fails on macOS only.

Exists to answer one question with evidence instead of reasoning: does a red
`macos` check actually block a merge into main now that it is a required check?
That was left as an unverified assertion, which this project's first rule forbids.

It fails ONLY on macOS and is marked so `-m macos` selects it, so the macos job
goes red while backend/frontend/secrets stay green — isolating the required-check
behaviour from everything else.

The PR carrying this is opened, observed, and CLOSED. An unmerged PR leaves
nothing in main's history, so the probe costs one branch and zero repository
debt.
"""
import sys

import pytest


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="probe: fails on macOS by design")
def test_probe_fails_on_macos_only():
    assert False, "deliberate failure: proving a red required check blocks the merge"
