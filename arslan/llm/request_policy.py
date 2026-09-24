"""Task-local policy for bounded, tool-free critique requests only."""
from contextlib import contextmanager
from contextvars import ContextVar

bounded_critique = ContextVar("bounded_critique", default=False)


@contextmanager
def critique_request():
    token = bounded_critique.set(True)
    try:
        yield
    finally:
        bounded_critique.reset(token)
