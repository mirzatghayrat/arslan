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


def test_the_mcp_tier_table_is_static_data_only():
    """The hand-graded tier table is data in the repository — versioned, reviewed, diffable.
    (0.1.63 C9b removed the preset connector list that used to live beside it.)

    Matched on IMPORT STATEMENTS, not on bare substrings. The first draft looked
    for the word "requests" anywhere in the file and went red the moment a
    connector exposed a tool called `browser_network_requests` — an assertion
    that fires on something other than what it claims to detect is worse than
    none, because the next person silences it rather than reading it.
    """
    source = pathlib.Path(inspect.getfile(catalog)).read_text()
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", source, re.M)
    roots = {name.split(".")[0] for name in imports}
    fetchers = roots & {"httpx", "requests", "urllib", "urllib3", "aiohttp", "socket"}
    assert not fetchers, (
        f"server/mcp/catalog.py imports {sorted(fetchers)} — the tier table must "
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
    # 0.1.55: per skill (its own license file, else the repo's), through
    # _skill_license_block → _license_gate; behaviour is pinned in test_skill_import.
    assert "_skill_license_block" in body, (
        "import_skill no longer consults the licence gate — a client could then "
        "import anything by calling the API directly")

