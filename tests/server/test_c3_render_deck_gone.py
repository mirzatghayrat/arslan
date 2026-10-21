"""C3a: `render_deck` is gone (card C3; ⓪Plan's Q1).

The deck-authoring skill told the main agent to call render_deck, but `_arslan_tools` never offered it,
and it was called 0 times. The executor, its pptx renderer, the catalog toolset and the request schema
go. Taken with it:
- **The claim check for decks.** A turn that makes a .pptx with run_command and says so is not an
  unverified claim any more: there is no render_deck it could have called instead.
- **Not the zero-tool check.** A turn that called no tool and says it made a PPT is still a
  fabrication. That check moves to promise_guard, the only user left, and goes with C7's zero-tool tier.
- **The packaged selftest still catches the PIL regression** by importing python-pptx itself, which
  attachment inspection still uses and which imports PIL.
"""
import importlib.util

from server.orchestrator import promise_guard, tool_loop
from server.registry import seed_catalog, seeder
from server.registry.executors import EXECUTORS
from server.services import replay_safety, task_service


def test_render_deck_is_not_a_tool_any_more():
    assert "render_deck" not in EXECUTORS
    assert "render_deck" not in tool_loop._NATIVE_PARAM_SCHEMAS
    assert importlib.util.find_spec("server.services.deck_pptx") is None
    assert "deck" not in {ts["key"] for ts in seed_catalog.TOOLSETS}
    assert "deck" in seeder.RETIRED_TOOLSET_KEYS


def test_a_pptx_made_with_run_command_is_not_an_unverified_claim():
    trace = [{"tool": "run_command", "result": {"ok": True}}]
    assert tool_loop._unverified_claim("PPT 已生成，可直接下载 report.pptx。", trace, {"run_command"}) is None


def test_a_zero_tool_turn_that_claims_a_deck_is_still_caught():
    assert promise_guard._zero_tool_fabrication("PPT 已正式生成并交付，共10页。") == "claims:deck"
    assert not hasattr(tool_loop, "_claims_deck") and not hasattr(tool_loop, "_CLAIMS_DECK_RE")


def test_no_tool_list_still_names_render_deck():
    assert "render_deck" not in replay_safety.REPLAY_SAFE_BUILTINS
    assert "render_deck" not in task_service._LOCAL_WRITE_TOOLS
    assert "render_deck" not in tool_loop._PROMISES_ACTION_RE.pattern
