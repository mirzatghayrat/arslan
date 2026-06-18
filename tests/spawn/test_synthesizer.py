"""Tests for CLI synthesis — P1.2 LLM-generated CLI with retry."""
import pytest

from arslan.models import LLMResponse
from arslan.spawn.synthesizer import SynthesisError, synthesize_cli


GOOD_CLI = """\
import sys
if len(sys.argv) > 1 and sys.argv[1] == "doc":
    print("usage")
    sys.exit(0)
sys.exit(1)
"""

BROKEN_CLI = "import sys\nsys.exit(2)\n"


class _FakeAdapter:
    """Returns scripted `content` values, one per chat() call."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = 0

    async def chat(self, system, user, **kwargs):
        self.calls += 1
        return LLMResponse(content=self._scripts.pop(0), usage={})


async def test_synthesize_returns_valid_cli_on_first_try():
    adapter = _FakeAdapter([GOOD_CLI])
    script = await synthesize_cli(adapter, name="x", slug="x", need="search prices")
    assert "doc" in script
    assert adapter.calls == 1


async def test_synthesize_retries_then_succeeds():
    adapter = _FakeAdapter([BROKEN_CLI, GOOD_CLI])
    script = await synthesize_cli(adapter, name="x", slug="x", need="search prices")
    assert "sys.exit(0)" in script
    assert adapter.calls == 2


async def test_synthesize_raises_after_max_attempts():
    adapter = _FakeAdapter([BROKEN_CLI, BROKEN_CLI, BROKEN_CLI])
    with pytest.raises(SynthesisError):
        await synthesize_cli(adapter, name="x", slug="x", need="x", max_attempts=3)
    assert adapter.calls == 3


async def test_synthesize_strips_markdown_fences():
    fenced = "```python\n" + GOOD_CLI + "```\n"
    adapter = _FakeAdapter([fenced])
    script = await synthesize_cli(adapter, name="x", slug="x", need="x")
    assert not script.lstrip().startswith("```")
    assert "import sys" in script
