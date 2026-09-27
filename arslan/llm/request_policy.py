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
