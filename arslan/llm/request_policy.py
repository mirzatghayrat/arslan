"""Task-local policy for bounded, tool-free critique requests only."""
from contextlib import contextmanager
from contextvars import ContextVar

bounded_critique = ContextVar("bounded_critique", default=False)

# A critique is a short structured judgment, never a long generation. 0.1.40
# evidence: 7 of 8 thinking-mode critiques spent the whole output budget on
# reasoning and returned nothing; all 12 non-thinking critiques returned JSON
# within 1,539 output tokens. Temperature 0: an adjudication should not vary.
CRITIQUE_MAX_OUTPUT_TOKENS = 2048
CRITIQUE_TEMPERATURE = 0.0


@contextmanager
def critique_request():
    token = bounded_critique.set(True)
    try:
        yield
    finally:
        bounded_critique.reset(token)


# 0.1.63 K3: how long Claude keeps this request's cache entries for the system and the history.
# True while a person is chatting (they come back within the hour; the hour costs 2x to write, five
# minutes 1.25x); background work and everything else keep the default five minutes. The provider
# sends the hour only to Claude on Anthropic's own host (or a listed verbatim proxy).
long_prompt_cache = ContextVar("long_prompt_cache", default=False)


@contextmanager
def prompt_cache(*, long: bool):
    token = long_prompt_cache.set(long)
    try:
        yield
    finally:
        long_prompt_cache.reset(token)
