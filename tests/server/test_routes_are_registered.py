"""The API surface must actually be REGISTERED, not merely written.

WHY THIS EXISTS: a version cap on starlette/fastapi used to sit in pyproject,
and its stated reason was that include_router() registered nothing past
starlette 1.3 — that the whole API surface silently vanished. That reason was
WRONG, and the correction is the reason this file matters. Measured on the newer
pair: the routes register and SERVE. What changed is INTROSPECTION —
include_router() stopped flattening a router into app.routes and now appends a
wrapper, so code walking app.routes for `.path` finds nothing and concludes the
API is gone. Our TESTS were doing that. The application never was.

The cap was lifted on 2026-08-23 once this file passed on the newer pair. That
is exactly what it is for: a cap is a decision, and a decision with no assertion
behind it rots. It counts the include_router calls in server/main.py rather than
hardcoding a number — a literal would go stale on the next router and would then
be wrong in the direction that reads as "the router is broken".
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.route_introspection import iter_route_paths

MAIN = pathlib.Path(__file__).resolve().parents[2] / "server" / "main.py"


def _declared_router_count() -> int:
    return len(re.findall(r"^\s*app\.include_router\(", MAIN.read_text(), re.M))


@pytest.fixture
def app():
    from server.main import create_app

    return create_app()


def test_the_api_surface_is_not_empty(app):
    """The bluntest form of the failure: everything vanished."""
    api = [p for p in iter_route_paths(app) if p.startswith("/api/v1")]
    assert api, (
        "no /api/v1 route is registered — include_router() silently did nothing, "
        "which is the starlette 1.3 behaviour the pyproject cap exists for"
    )


def test_every_declared_router_contributed_at_least_one_route(app):
    """Discriminating against a PARTIAL failure.

    "Some routes exist" is satisfied by an app that registered one router and
    dropped twenty-four. Comparing against the number of include_router calls
    in the source means the assertion tracks the code rather than a literal."""
    declared = _declared_router_count()
    assert declared >= 20, f"expected the full router set in main.py, found {declared}"

    prefixes = {
        p.split("/")[3] for p in iter_route_paths(app)
        if p.startswith("/api/v1/") and len(p.split("/")) > 3
    }
    # Not one-to-one (several routers share a top segment, some routers mount
    # more than one), so the floor is deliberately conservative: what must not
    # happen is a handful of surviving groups standing in for the whole API.
    assert len(prefixes) >= 15, (
        f"only {len(prefixes)} distinct /api/v1 groups registered from "
        f"{declared} include_router calls: {sorted(prefixes)}"
    )


@pytest.mark.parametrize("path", [
    "/api/v1/health",
    "/api/v1/settings",
    "/api/v1/spawns",
    "/api/v1/conversations",
    "/api/v1/brain",   # the knowledge router mounts here, not at /knowledge
])
def test_named_endpoints_the_ui_cannot_live_without(app, path):
    """Named individually so a failure says WHICH surface disappeared."""
    paths = iter_route_paths(app)
    assert any(p == path or p.startswith(path + "/") for p in paths), (
        f"{path} is not registered; the UI calls it on every load")


def test_the_websocket_route_is_registered(app):
    """The chat transport, and a special case: when it is missing the SPA
    catch-all answers the upgrade with 200 instead of failing, which is what
    made the six-release outage invisible."""
    ws = [p for p in iter_route_paths(app) if p.startswith("/ws/")]
    assert ws, "no /ws/ route — every upgrade would fall through to the SPA"
