"""The sandbox gets the LAST TURN of the main thread as read-only background.

User's ruling: N = 1 turn, where a turn is one `user` message plus everything up
to the next one. The reasoning is about which surface this is for — a spawn's
DELIVERABLE already has its own refine/confirm path, so the sandbox only needs
enough context to answer conceptually about what is being discussed with Arslan
in the main chat.

Measured first, because "N turns" was nearly the wrong unit. In the user's own
database a message ranges from 52 characters (median) to 21,960 (max) — a
factor of 420. So the turn boundary decides WHERE to cut and a character budget
decides HOW MUCH, or one screenshot-sized report turns a bounded feature into an
unbounded cost paid on every sandbox turn.

Three labelling obligations, each with a failure it prevents:
  boundary   the model must be able to tell background from its own conversation
  identity   it is READ-ONLY and NOT the task — otherwise the spawn reads the
             user's instructions to Arslan as instructions to itself
  truncation if anything was dropped, say so. A spawn that believes it has the
             whole story answers confidently from a partial one.
"""
from __future__ import annotations

from server.db.models import ArslanMessage
from server.ws import sandbox as sandbox_mod


async def _seed(client, cid: str, rows: list[tuple[str, str]]) -> None:
    async with client.db_maker() as db:
        for role, content in rows:
            db.add(ArslanMessage(conversation_id=cid, role=role, content=content))
        await db.commit()


async def test_it_takes_only_the_most_recent_turn(client):
    await _seed(client, "t", [
        ("user", "OLD question"),
        ("arslan", "OLD answer"),
        ("user", "NEW question"),
        ("arslan", "NEW answer"),
    ])

    block = await sandbox_mod.main_thread_context("t")

    assert "NEW question" in block and "NEW answer" in block
    # Discriminating: taking "the last N messages" instead of the last TURN
    # would pull OLD answer in whenever a turn happens to be short.
    assert "OLD question" not in block and "OLD answer" not in block


async def test_a_turn_includes_everything_after_the_user_message(client):
    """Not just the reply — a turn can contain a spawn's summary too, and that
    is part of what is being discussed."""
    await _seed(client, "t", [
        ("user", "the question"),
        ("arslan", "the reply"),
        ("spawn_summary", "the spawn's deliverable"),
    ])

    block = await sandbox_mod.main_thread_context("t")
    assert "the question" in block
    assert "the reply" in block
    assert "the spawn's deliverable" in block


async def test_it_says_it_is_read_only_background_and_not_the_task(client):
    await _seed(client, "t", [("user", "q"), ("arslan", "a")])
    block = await sandbox_mod.main_thread_context("t")
    lowered = block.lower()
    assert "read-only" in lowered or "只读" in block
    assert "not your task" in lowered or "不是你的任务" in block


async def test_it_is_delimited_at_both_ends(client):
    """Without a closing marker the model cannot tell where background stops and
    its own conversation starts."""
    await _seed(client, "t", [("user", "q"), ("arslan", "a")])
    block = await sandbox_mod.main_thread_context("t")
    lines = [ln for ln in block.splitlines() if ln.strip()]
    assert lines[0].startswith("["), lines[0]
    assert lines[-1].startswith("["), lines[-1]


async def test_an_oversized_turn_is_truncated_and_says_so(client):
    """The 420x range is why this exists. A single report can be 22k characters;
    without a budget the sandbox pays for it on EVERY turn."""
    await _seed(client, "t", [("user", "q"), ("arslan", "x" * 40_000)])

    block = await sandbox_mod.main_thread_context("t")

    assert len(block) < 20_000, f"no budget applied: {len(block)} chars"
    assert "…" in block or "省略" in block or "truncated" in block.lower()


async def test_a_short_turn_is_NOT_marked_truncated(client):
    """Discriminating: always emitting the truncation notice would satisfy the
    test above and teach the spawn to distrust context that is in fact
    complete."""
    await _seed(client, "t", [("user", "q"), ("arslan", "a")])
    block = await sandbox_mod.main_thread_context("t")
    assert "省略" not in block and "truncated" not in block.lower()


async def test_an_empty_thread_yields_nothing_rather_than_an_empty_frame(client):
    """A brand-new main thread has no turn. Emitting the header with nothing in
    it would tell the spawn 'here is the context' and then show it nothing —
    worse than saying nothing at all."""
    assert await sandbox_mod.main_thread_context("no-such-thread") == ""


# ---------------------------------------------------------------------------
# The wiring. A correct helper with no caller is the shape that keeps catching
# me — and a source assertion is the right tool here only because what is being
# asserted IS a call site's presence, not a behaviour.
# ---------------------------------------------------------------------------

def test_the_endpoint_actually_calls_it_and_only_once_per_session():
    import inspect

    src = inspect.getsource(sandbox_mod.sandbox_endpoint)
    assert "main_thread_context(" in src, "the helper has no caller"
    # Once per session, not per turn: re-reading it every turn would put a
    # drifting block into the system prompt and bust the cached prefix.
    assert "if main_ctx is None:" in src


def test_it_goes_into_the_system_prompt_not_the_transcript():
    """If it were appended to `transcript`, the sandbox would treat background
    as something someone said here — and it would be summarised into the
    deliverable and distilled into memory on merge."""
    import inspect

    src = inspect.getsource(sandbox_mod.sandbox_endpoint)
    assert "system = f\"{system}\\n\\n{main_ctx}\"" in src
    assert "transcript.append({\"role\": \"user\", \"content\": main_ctx" not in src


def test_the_client_sends_the_thread_id_with_every_user_message():
    """The server cannot fetch a thread it has not been told about. Before this,
    `conversation_id` arrived only on confirm_merge."""
    import pathlib

    panel = (pathlib.Path(__file__).resolve().parents[2]
             / "web" / "src" / "components" / "SandboxPanel.tsx").read_text(encoding="utf-8")
    send = panel[panel.index("type: 'user_message'"):][:400]
    assert "conversation_id: conversationId" in send


async def test_a_turn_whose_messages_are_all_blank_yields_nothing(client):
    """🔴 Added because a mutation exposed a hole: the empty-thread test above
    exits at the `no rows` guard, so the SECOND guard — a turn that has rows but
    nothing renderable — was never exercised. Deleting it emitted a header and a
    footer with nothing between them: "here is the context", followed by no
    context."""
    await _seed(client, "blank", [("user", "   "), ("arslan", "")])
    assert await sandbox_mod.main_thread_context("blank") == ""
