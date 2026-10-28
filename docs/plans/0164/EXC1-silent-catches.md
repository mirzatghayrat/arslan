# EXC1: the 32 silent broad catches

⓪Plan, 2026-10-28. User's request (relayed by ④参谋): go through every broad `except` that silently swallows, and from then on a new one needs a comment saying why. The rule is `docs/sessions.md` §12, rule 4. Tier: **could**. It blocks nothing and runs in the v0.1.64 cleanup lane.

## What is there (main `96bdf096`)

Counted with an AST walk over `server/` and `arslan/`, tests excluded. A handler counts when it catches `Exception`, `BaseException` or everything (bare `except`), alone or in a tuple, and its body is only `pass`. 808 `try` blocks, 294 broad handlers, **32 silent**.

21 of the 32 already say why, 20 on the `except` line (for example `— the window may be gone; the decision stands`) and one on the `pass` line (`task_service.py:867`, "logged by _kept"; move it to the `except` line). **11 say nothing** beyond `# noqa: BLE001` or no comment at all:

| File:line | What it wraps |
|---|---|
| `server/services/lessons.py:357` | `desktop_status.push` after a lesson is learned |
| `server/services/run_registry.py:106` | one sink in the fan-out of a run's events (no `noqa` either) |
| `server/services/turn_facts.py:146` | `recap_service.log_event` after facts are saved |
| `server/services/usage_retention.py:107` | awaits its own loop task at shutdown; also swallows `CancelledError` |
| `server/services/scheduler.py:548` | the same shape as `usage_retention.py:107` |
| `server/services/agent_browser.py:126` | awaits a task it just cancelled; also swallows `CancelledError` |
| `server/services/crypto_boot.py:220` | a trial decrypt: success means "already current", so the exception is the expected path |
| `server/orchestrator/tool_loop.py:2494` | building the synthesis adapter; on failure the turn silently keeps the main adapter. **Likely "log it".** (hot file) |
| `server/orchestrator/arslan.py:560` | `emit` of `fact_saved` / `memory_proposed` (hot file) |
| `server/ws/arslan.py:644` | sending the error frame and closing after an internal error |
| `server/db/migrations/versions/_0023_run_kb_sources.py:13` | a migration's `downgrade` |

The 21 with a reason still get a look: a reason can be stale. Ten of the 32 are in old migrations (`_0021`, `_0022`, `_0023`, `_0027`, `_0028` twice, `_0031`, `_0032`, `_0034`, `_0036`), all in `downgrade` steps.

## What to do

For each of the 32, one of three:

1. **Narrow it** to the exceptions that can actually happen there (for example `OSError`, `RuntimeError`, `sqlite3.OperationalError`, `WebSocketDisconnect`), or
2. **Log it** (`logger.debug` or `logger.warning` with the exception), or
3. **Keep it** with a reason on the `except` line, in the form `# noqa: BLE001 — <why swallowing is right here>`.

Rules:

- **No behaviour change.** Narrowing only where the remaining exceptions provably can't be raised there; when unsure, log instead of narrowing. Never narrow a catch that guards a security decision, a ledger write or a confirm card without the owner's review (③Hands for Hands files, ②Main otherwise).
- **Migrations:** applied migrations are history. Only comment-only changes (option 3), no code change.
- **`CancelledError`:** swallowing it is right only when awaiting a task this code just cancelled or stopped. Say so in the comment. Anywhere else, re-raise.
- **Hot files** (`server/orchestrator/tool_loop.py`, `server/orchestrator/arslan.py`; `docs/sessions.md` §3): small changes, merged after any open K-line PR on the same file.
- **Bridge contract files** (`server/services/phone_*.py`): comment-only, no change to frames.

## Keeping it at zero

Add a small check so a new silent broad catch without a reason fails CI: an AST walk (the same definition as above) that fails on a silent broad handler whose `except` line has no text after `noqa: BLE001 —`. Either a test in `tests/` or a script in the existing `lint` job. The check lands in the same PR as the cleanup, or right after it. Ruff's `BLE001` is not enabled today (`pyproject.toml` `[tool.ruff]` selects the defaults), and enabling it would flag all 294 broad handlers, so it is not the tool here.

## PRs

One PR, or two if it passes about 800 product lines (it won't; this is comments plus a few narrowed types): **EXC1** cleanup plus the check. No migration.

## Acceptance

- The count script reports 0 silent broad handlers without a reason.
- Every narrowed handler: a test that raises the exception the handler is supposed to absorb still passes, or the PR says why no test can raise it.
- Full backend suite green on CI (run id cited).
- Evidence, four items (`docs/sessions.md` §8).
