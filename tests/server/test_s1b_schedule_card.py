"""S1b (U14 d): the schedule card shows what the task will do, and what a scheduled run may do (card S1).

Before S1b the card showed the task's name and cadence; the text it will run each time was not on it,
so a yes covered a prompt nobody saw. Now:
- the tool loop hands the prompt to the card callback, and the `propose_schedule` frame carries it;
- what the phone's Bridge reads from that frame is unchanged (⓪Plan, Q8): `call_id`, `perm_kind`,
  `title`, `expires_at`, `name` and `when` are the same with and without the prompt. FrameMapper ignores
  any other key; ①iOS's FrameMapper test pins that side;
- a prompt longer than a card shows is refused, never cut (as an MCP call's arguments, ⓪Plan's review of
  S1a): not even under a grant;
- the model is told the bounds a scheduled run has (unattended; writes only in Arslan's own folder; no commands
  in v0.1.63; only MCP tools the server marks read-only; steps that need an OK are refused and listed).
"""
from server.orchestrator import arslan, tool_loop
from server.services import approvals, permissions
from server.ws import protocol

BRIDGE_READS = ("type", "call_id", "perm_kind", "title", "expires_at", "name", "when")


async def _schedule(args, confirm):
    async def tools():
        return [{"key": "schedule_task", "description": "x"}]
    return await tool_loop._dispatch_tool("schedule_task", args, "", resolve_tools=tools, emit=lambda e: None,
                                          tool_timeout_s=5, tool_trace=[], convo=[], conversation_id="conv-s",
                                          confirm_schedule=confirm)


async def test_the_card_is_given_the_prompt(execution_db):
    seen = []

    async def confirm(name, when, prompt=""):
        seen.append((name, when, prompt))
        return False
    await _schedule({"name": "digest", "when": "every: 86400", "prompt": "Summarise my inbox"}, confirm)
    assert seen == [("digest", "every: 86400", "Summarise my inbox")]


async def test_a_prompt_longer_than_a_card_shows_is_refused(execution_db):
    asked = []

    async def confirm(name, when, prompt=""):
        asked.append(prompt)
        return True
    out = await _schedule({"name": "digest", "when": "every: 86400",
                           "prompt": "x" * (protocol.DETAIL_MAX + 1)}, confirm)
    assert out["ok"] is False and out["code"] == "too_long_to_show" and asked == []


async def test_the_frame_carries_the_prompt_and_the_bridge_reads_the_same(execution_db):
    frames = []

    async def asker(frame):
        frames.append(frame)
        return {"approved": False, "scope": None, "note": "", "by": "mac"}
    confirmations = approvals.JobConfirmations("conv-s", "job-1")
    confirmations.asker = asker
    with permissions.asking_with(asker):
        await confirmations.schedule("digest", "every: 86400")
        await confirmations.schedule("digest", "every: 86400", prompt="Summarise my inbox")
    without, with_prompt = frames
    assert with_prompt["prompt"] == "Summarise my inbox" and "prompt" not in without
    assert {k: without.get(k) for k in BRIDGE_READS if k not in ("call_id", "expires_at")} \
        == {k: with_prompt.get(k) for k in BRIDGE_READS if k not in ("call_id", "expires_at")}
    assert with_prompt["title"] == "Schedule “digest”?"


async def test_the_model_is_told_what_a_scheduled_run_may_do(execution_db, monkeypatch):
    every = {t["key"]: t["description"] for t in await arslan._every_tool()}
    text = every["schedule_task"]
    # v0.1.63: no commands in a scheduled run (until S2a-3); writes only in Arslan's own folder.
    assert "Arslan's own folder" in text and "runs no commands" in text and "refused" in text and "Inbox" in text
    assert "sandboxed commands" not in text
    assert "only calls MCP tools the server marks read-only" in text      # R63's audited clause (mcp/executor)
