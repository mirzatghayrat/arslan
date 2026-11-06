# LOOP1: a simple agent loop, with the same features

| | |
|---|---|
| Decided | The user, 2026-11-07, relayed by ④参谋: restructure now, before SUB, S5a and SIDE add to the loop. This overrides the 11-04 decision to split `tool_loop.py` after the tag. |
| Version | v0.1.64, must |
| Lane | LOOP1's own session. ⓪Plan coordinates and reviews, with a fresh subagent per PR at the effort below. ③Hands reviews the Hands family and agrees slice d. |
| Rule | No behaviour change, no new feature or setting, gate order unchanged, existing assertions unchanged. A move that would change behaviour stops and is reported. Two exceptions, each its own PR: the id fix (#722) and slice f. |
| Size | 22 PRs, each from main, not stacked: the id fix, L0, b, a (6), c1 (2), c2 (2), c3 (3), e, f, d (2), z (2). Moved lines don't count toward the 400-line guide: `--color-moved` and the pins carry their proof, and new or changed lines stay small. Net product lines about flat until d1. |

## Reference
- One tool object: [Codex `ToolExecutor`](https://github.com/openai/codex/blob/c1c07853fe6e8e712f264030a30758cfa80eedfe/codex-rs/tools/src/tool_executor.rs#L106), [OpenClaw `AgentTool`](https://github.com/openclaw/openclaw/blob/0e0bebb48c1cd87d24e59cc9d38ad2d0c6879581/packages/agent-core/src/types.ts#L505). Duplicate names refused at assembly: [Goose](https://github.com/block/goose/blob/4facf56cbab049142809d9afa4648ebe6823ba80/crates/goose-agent/src/machine.rs#L90).
- Turn state and phases: [Hermes `_LoopState`](https://github.com/NousResearch/hermes-agent/blob/7a04692b039164ebc02ee989238b748196cc97e8/agent/conversation_loop.py#L1461). The shape only: typed fields and explicit calls, no reflection.
- Stages around a tool: [dsh pipeline](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/tool-execution-pipeline.md) (gates, execute, after).
- **Rejected:** Goose re-deriving state from the transcript (Arslan records state when it happens and never replays it); bashlex and tree-sitter (d2); Hermes's name sets for per-tool traits.
- **Seen, for the user's v0.1.65 talk, not here:** OpenClaw's derived turn taint, ZeroClaw's signed tool receipts.

## Raw material (main `bcd9ad20`)
- `server/orchestrator/tool_loop.py`: 3,789 lines. `_run_native:3057` is 733 lines, 24 parameters, 22 name tests, 13 record sites. `_dispatch_tool:1426` is 534 lines, 18 parameters, 19 name tests, 27 record sites. `_model_call:707` is 165 lines.
- A built-in tool lives in up to five places: description and offer condition in `arslan._every_tool:1201` (450 lines); schema in `_NATIVE_PARAM_SCHEMAS:2004` (62 entries, 385 lines); executor in `executors.EXECUTORS`; gate in `_dispatch_tool`; traits in name sets (`parallel_reads.READS`, `task_service._READ_TOOLS`, `untrusted._OUTSIDE_TOOLS`, `replay_safety.REPLAY_SAFE_BUILTINS`, `WRAP_UP_TOOLS`). Eight have no executor and are branches in the batch loop: `update_plan`, `ask_user_choice`, `escalate`, `find_tools`, `use_tool`, `propose_plan_change`, `propose_capability`, `create_skill`.
- `seed_catalog` rows feed the registry's display and assignment, not the model: out of scope, C7's to delete.
- `"run_command"` is in 17 `server/` files, most of them display (`tool_review`, `desktop_status`, `run_process`). A handful is the realistic floor; it is reported, not targeted.
- `arslan.py`: 1,650 lines. The prompt is eight constants (`:43-219`, `:329`) built into one byte-stable prefix (K3's cache). `_handle_answer_body:893` is 193 lines.
- Tests: 190 files mention `tool_loop`. `_dispatch_tool` is called by keyword in 33 files, `run_native` about 140 times, and 21 names are patched on the module (`_get_adapter` 228 times).

## Method
1. **Pin first, on today's main (`L0`, tests only).** Scripted turns through `run_native` with a fake adapter and a fake tool table: every frame in order, every request's messages and tools, and the return value, byte for byte, as per-scenario JSON. A pairwise gate-order matrix: a call that trips two gates is answered by the earlier one. Both exist only to carry LOOP1 (`DELETE-BY: v0.1.64`, with slice z). The traces hold no volatile value and don't make rework for other lanes: a failure names the one regenerate command, and a PR that changes behaviour on purpose commits the new JSON, so its diff shows the change.
2. **Move, then prove.** Each PR passes the same pinned tests. Test files change only where a patch must follow a moved function. `run_native(**kwargs)` and `_dispatch_tool(...)` keep their keyword forms; each builds its typed object once.
3. **Definitions move, they are not copied.** A family's description and schema leave the old place in the PR that adds its `Tool`, so nothing is defined twice and no other lane's edit has two homes. Traits move last, all together (a6). `tests/server/test_loop1_tool_table.py` dumps the offered table and schemas across 54 cases of the offer conditions (job, someone to ask, Hands, browser, workspace, read default, LAN, SSH, shell, project). The dump is identical on a PR's base and head, and the PR gives both hashes.
4. **Mutation on every gate move.** Swap two gates, drop a refusal, flip a default: the pinned tests go red, and the PR says which.

## External evidence
Each PR: the CI run id on all five checks, the `--color-moved` result (moved lines against new lines), the table dump's hashes, the mutations. Slice-level: SMART-5 and STY2 don't regress at ⓪Plan's next bench.

## Slices
| | What | Review | Target |
|---|---|---|---|
| L0 | The pinned tests and the table dump | high | no product line |
| b | `TurnRequest` (the caller's inputs, frozen), `TurnState` (replaces `_facts`), `ToolTurn` (replaces the 12 gate keywords) | high | `_run_native` 2 parameters, `_dispatch_tool` a call and a turn. **Tell ⓪Plan.** |
| a1 | `Tool`, `Offer`, the registry and its check at import (unique names, an object schema, the executor's key matches); web and memory family | high | **New tools register here. Tell ⓪Plan.** |
| a2 | Jobs and tasks, next after a1 | high | **Tell ⓪Plan.** |
| a3 | Files, capability and self, schedule, SSH and LAN | high | |
| a4 | Terminal | max | |
| a5 | Hands, browser and Mac | ③Hands | `_every_tool` under 30 lines; `_NATIVE_PARAM_SCHEMAS` derived |
| a6 | Traits on the tool, no default values, checked at import; today's name sets derive from them | max (`untrusted`, `task_service`) | sets equal before and after |
| c1 | Pure moves out of `tool_loop.py`: answer guards, turn text and streams, salvage, `_model_call`, the eval budget (2 PRs) | high | under 2,900 lines |
| c2 | `_dispatch_tool` as stages: admit, gates in today's order, execute, after. Per-tool gates by lookup (`Tool.gate`), the command gate in its own module (2 PRs) | max | `_dispatch_tool` under 60 lines |
| c3 | `_run_native` as phases: open turn, step mode, step notes, fit history, request, tool batch (per-call stages, host tools by lookup), finish answer. Locals move to `TurnState` as each phase leaves. `_handle_answer_body` split the same way (3 PRs) | high; max where a phase moves a permission path | no function over 150 lines; `tool_loop.py` under 1,500 |
| e | The prompt in named per-rule pieces (`answer_rules.py`) | high | identical bytes, hash in the PR |
| f | A stopped reply closes its open step in the window: on `run_cancelled` a step still `running` becomes `error` | high | no spinner on a stopped reply |
| d1 | After #686. The server sends the card's summary and `web/src/lib/commandSummary.ts` goes; the vectors stay as a server test. No Bridge frame changes; if one must, ⓪Plan hears first, because that is the user's merge | max | about 500 lines of TypeScript gone |
| d2 | After S2a-3 merges, agreed with ③Hands. Readers stop re-reading a command `shell_grammar` understood. A command it doesn't understand keeps its named rules on the raw text, and `card_purpose` keeps its own step reading: the grammar gives no steps for those and drops redirect targets | max | one parse of an understood command |
| z | Last, after the other lanes' open PRs have landed, split by test group so it isn't rebased across everyone (2 PRs). Tests call the new modules; adapters and pins deleted. Checked by AST: the test-name set and every assertion unchanged | high | no LOOP1 `DELETE-BY:` left |

**The gate for SUB, S5a and SIDE:** b, a1, and any family they extend, moved next after a1. a3–a6 don't block them.

**Slice f, what already holds:** the in-turn trajectory is memory only and goes with the stopped task, so no later request can carry an open call (`host_run:94`). The run record closes a pending step as failed (`run_recorder:267`), and the task journal marks an unfinished write for reconciliation (`task_service:727`). Only the window is open: `arslanStore.ts:694` folds a `running` step into the stopped reply, and `ProcessList.tsx:118` draws it as a spinner.

**Parser licences (d2):** bashlex is GPLv3+, so it can't ship in an Apache-2.0 app. tree-sitter and tree-sitter-bash are MIT, but they add native wheels to the packaged app. S2a-3's `shell_grammar.py` (#375) is standard library only and already an allowlist, so it is the reader to build on (d2).

## Done means
Every tool defined once; dispatch by lookup; no function in the loop path over about 150 lines (the path: `tool_loop.py`, the modules split from it, `_handle_answer_body`); `tool_loop.py` well under 2,500 lines; CI green; SMART-5 and STY2 no worse at ⓪Plan's next bench.
