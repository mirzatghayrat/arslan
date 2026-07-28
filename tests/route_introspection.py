"""Enumerate an app's route paths across two different FastAPI shapes.

WHY: up to fastapi 0.136, include_router() FLATTENED a router's routes into
app.routes, so `r.path` worked for every entry. From 0.137 (the version our
pyproject caps below) it appends a single `_IncludedRouter` wrapper instead and
the individual paths are one level down. The routes still serve — a live request
returns 200 either way — but any code that walks app.routes looking for paths
sees an object with no `.path` and reads it as "the API is gone".

That distinction is the whole point of this helper: the cap exists because our
TESTS introspect routes, not because the application breaks. Written to work on
both so the cap can be lifted on evidence rather than on faith.
"""
from __future__ import annotations


def iter_route_paths(app) -> set[str]:
    """Every path the app serves, flattened through included-router wrappers."""
    found: set[str] = set()

    def walk(routes, prefix: str = "") -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                found.add(prefix + path)
            # fastapi >= 0.137: the router is kept whole rather than flattened.
            # The prefix is NOT on the wrapper — measured on 0.140.13, the
            # wrapper exposes only `original_router` and `include_context`, and
            # `original_router.prefix` is the empty string. The prefix given to
            # include_router() lives at include_context.prefix. Reading it off
            # the wrapper (the obvious guess) silently yields "/health" instead
            # of "/api/v1/health" — right-looking paths, wrong answers.
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx = getattr(route, "include_context", None)
                walk(getattr(inner, "routes", []),
                     prefix + (getattr(ctx, "prefix", "") or ""))
            # starlette Mount and friends
            elif hasattr(route, "routes") and not isinstance(path, str):
                walk(route.routes, prefix)

    walk(getattr(app, "routes", []))
    return found
