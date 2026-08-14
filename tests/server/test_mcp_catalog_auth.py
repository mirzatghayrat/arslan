"""Every connector declares HOW it authenticates, explicitly.

THE SHAPE THIS REPLACES. `_one_click` derived "no env vars" into "connect in one
click", a two-way split that has no way to say "needs OAuth, not supported yet".
The first OAuth-shaped entry added to this catalog would have rendered as a
NEEDS-KEY card with a prefill form — a form that collects a key no service will
ever issue, actively lying about what would happen next (spec ③ §0.5).

The explicit field exists BEFORE any oauth entry does, on the user's ruling: the
first deliverable is the honesty mechanism, and the catalog must NOT gain a fake
oauth entry just to demonstrate the section.
"""
from __future__ import annotations

import pytest

from server.mcp.catalog import CONNECTORS, _one_click, list_connectors

VOCAB = ("none", "static_key", "oauth")


def test_every_connector_declares_auth():
    missing = [c["key"] for c in CONNECTORS if "auth" not in c]
    assert not missing, (
        f"connectors without an explicit auth field: {missing} — the derived "
        "two-way split is exactly what this field replaces"
    )


@pytest.mark.parametrize("c", CONNECTORS, ids=lambda c: c["key"])
def test_auth_uses_the_fixed_vocabulary(c):
    assert c["auth"] in VOCAB


@pytest.mark.parametrize("c", CONNECTORS, ids=lambda c: c["key"])
def test_auth_agrees_with_the_env_shape_it_replaces(c):
    """For today's entries the field must MATCH the derivation, or the badge and
    the form would disagree about the same card. An oauth entry is exempt by
    construction — it has no env to derive from — but none may exist yet."""
    if c["auth"] == "none":
        assert not c["env"], f"{c['key']}: auth=none but carries env vars"
    elif c["auth"] == "static_key":
        assert c["env"], f"{c['key']}: auth=static_key but has no env vars"


def test_no_oauth_entries_until_the_flow_exists():
    """User ruling ② (2026-08-08): the section ships before any entry that needs
    it. A catalog entry whose Connect can only fail is not a demo, it is a trap."""
    fakes = [c["key"] for c in CONNECTORS if c["auth"] == "oauth"]
    assert not fakes, f"oauth entries added before the flow exists: {fakes}"


def test_list_connectors_carries_auth_and_keeps_one_click():
    """one_click stays for compatibility, but auth travels with every row."""
    for row in list_connectors():
        assert row["auth"] in VOCAB
        assert row["one_click"] == _one_click(row)
