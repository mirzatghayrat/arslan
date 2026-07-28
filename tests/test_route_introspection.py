"""The route flattener, exercised against BOTH FastAPI shapes.

The newer shape cannot be produced by the version this repo pins, so it is
built here from a fixture — and the fixture's shape was MEASURED on fastapi
0.140.13 rather than guessed:

    _IncludedRouter
      .original_router   -> APIRouter, whose .prefix is ""
      .include_context   -> object carrying .prefix ("/api/v1")

Guessing cost something already: the first draft read the prefix off the
wrapper, which has none, so every path came out as "/health" instead of
"/api/v1/health" — plausible-looking output, wrong answers, and no test could
have caught it because the pinned version never builds that object.
"""
from __future__ import annotations

from tests.route_introspection import iter_route_paths


class _Route:
    """A starlette Route: just a path."""

    def __init__(self, path: str) -> None:
        self.path = path


class _Ctx:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix


class _Router:
    def __init__(self, routes) -> None:
        self.routes = routes
        self.prefix = ""          # as measured: empty, even when a prefix was given


class _IncludedRouter:
    """fastapi >= 0.137's wrapper, in the shape measured on 0.140.13."""

    def __init__(self, routes, prefix: str) -> None:
        self.original_router = _Router(routes)
        self.include_context = _Ctx(prefix)


class _App:
    def __init__(self, routes) -> None:
        self.routes = routes


def test_the_old_flattened_shape():
    app = _App([_Route("/openapi.json"), _Route("/api/v1/health")])
    assert iter_route_paths(app) == {"/openapi.json", "/api/v1/health"}


def test_the_new_wrapped_shape_is_descended_into():
    app = _App([
        _Route("/openapi.json"),
        _IncludedRouter([_Route("/health"), _Route("/items/{i}")], "/api/v1"),
    ])
    assert iter_route_paths(app) == {
        "/openapi.json", "/api/v1/health", "/api/v1/items/{i}"}


def test_the_prefix_comes_from_the_include_context_not_the_router():
    """The specific mistake the measurement caught.

    original_router.prefix is "" even when include_router(prefix=...) was
    given one, so a flattener reading it produces unprefixed paths that look
    entirely reasonable in a failure message."""
    app = _App([_IncludedRouter([_Route("/health")], "/api/v1")])
    paths = iter_route_paths(app)
    assert paths == {"/api/v1/health"}
    assert "/health" not in paths, (
        "the prefix was dropped — this is what reading it off the wrapper does")


def test_nested_includes_accumulate_prefixes():
    inner = _IncludedRouter([_Route("/tree")], "/brain")
    app = _App([_IncludedRouter([inner], "/api/v1")])
    assert iter_route_paths(app) == {"/api/v1/brain/tree"}


def test_a_route_object_with_no_path_contributes_nothing():
    class _Odd:
        pass

    app = _App([_Odd(), _Route("/ok")])
    assert iter_route_paths(app) == {"/ok"}
