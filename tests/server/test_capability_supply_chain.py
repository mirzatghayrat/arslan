"""Where capabilities may come from. A red line, pinned before it is crossed.

The rule the user set: a capability's SOURCE is always a closed, reviewed
registry. Search may become a discovery layer one day — results a person reads,
from which a person chooses — but it must never become an install channel.

The distinction is not pedantic. "Install the top result for `browser mcp`"
turns a search ranking into a supply chain: whoever can influence the ranking
can influence what runs on the user's machine, and nobody reviewed the thing in
between. Naming a repository is a decision; accepting a result is not.

Today the boundary holds — import_skill takes a repo reference and there is no
query-driven path into it. These tests exist so that stays true by accident of
nobody noticing, rather than by accident of nobody trying.
"""
from __future__ import annotations

import inspect
import pathlib
import re

from server.mcp import catalog
from server.services import skill_import


def test_mcp_connectors_come_from_the_static_catalog_only():
    """CONNECTORS is data in the repository — versioned, reviewed, diffable."""
    source = pathlib.Path(inspect.getfile(catalog)).read_text()
    for forbidden in ("httpx", "requests", "urllib", "aiohttp"):
        assert forbidden not in source, (
            f"{forbidden} appears in the preset catalog — the connector list must "
            "be static data, not something fetched at runtime")


def test_installing_a_skill_requires_naming_a_repository():
    """Not a search result, not an index entry: an explicit owner/repo.

    The signature is the boundary. A function that accepted a query here would
    be the install channel the rule forbids, however carefully it ranked."""
    sig = inspect.signature(skill_import.import_skill)
    assert list(sig.parameters) == ["ref", "path"], (
        f"import_skill's parameters changed to {list(sig.parameters)} — if a "
        "query or a search result can now reach it, that is the supply-chain "
        "line being crossed")


def test_no_search_endpoint_feeds_the_importer():
    """The whole module, read for a query-shaped entry point.

    A discovery layer is allowed to exist. What is not allowed is a path from
    'here are some results' to 'and now it is installed' without a person
    naming the source in between."""
    source = pathlib.Path(inspect.getfile(skill_import)).read_text()
    # GitHub's code/repo search endpoints. Their absence is the claim.
    for endpoint in ("/search/repositories", "/search/code", "/search/topics"):
        assert endpoint not in source, (
            f"{endpoint} is reachable from the importer — search must stay a "
            "discovery layer that a person reads, never a source of installs")


def test_the_license_gate_is_server_side_and_not_advisory():
    """A gate the UI could skip is not a gate. Named here because the supply
    chain and the licence rule fail together: an unreviewed source with an
    unchecked licence is the whole hazard in one step."""
    source = pathlib.Path(inspect.getfile(skill_import)).read_text()
    body = source[source.index("async def import_skill"):]
    assert "_license_gate" in body, (
        "import_skill no longer consults the licence gate — a client could then "
        "import anything by calling the API directly")


def test_the_catalog_entries_are_complete_enough_to_review():
    """Every preset must carry what a reviewer needs, or 'reviewed registry' is
    a phrase rather than a property."""
    for c in catalog.CONNECTORS:
        assert c.get("key") and c.get("label"), c
        assert c.get("description"), f"{c['key']} has no description to review"
        assert "transport" in c and "command" in c, f"{c['key']} hides how it runs"
        # env is a list (possibly empty) — never absent, because "no credentials
        # required" and "nobody recorded the credentials" must not look alike.
        assert isinstance(c.get("env"), list), f"{c['key']} does not declare its credentials"


def test_no_connector_smuggles_a_shell_pipeline():
    """`command` is executed. A preset whose command is a shell one-liner would
    make the reviewed-registry property meaningless at the last step."""
    for c in catalog.CONNECTORS:
        assert not re.search(r"[;&|`$]", str(c["command"])), c
        for arg in c.get("args") or []:
            assert not re.search(r"[;&|`]", str(arg)), (c["key"], arg)
