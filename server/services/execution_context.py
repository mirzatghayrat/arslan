"""Trusted execution identity shared by tools; model arguments cannot choose a Run."""
from contextlib import contextmanager
from contextvars import ContextVar

_run_id: ContextVar[int | None] = ContextVar("execution_run_id", default=None)


def current_run_id() -> int | None:
    return _run_id.get()


@contextmanager
def bind_run(run_id: int):
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)
