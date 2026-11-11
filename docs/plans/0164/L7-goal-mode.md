# L7: goal mode, keep working until the goal is met

| | |
|---|---|
| Decided | The user, 2026-10-28: L7 stays in v0.1.64 as "should", and it merges only if the M64 bench doesn't regress ([README](README.md) §1.1, §3 row "other execution-first rows"; [lead roadmap](../2026-10-17-0162-lead-roadmap.md) L7). |
| Version | v0.1.64, should |
| Lane | ②Main writes the card and the code. ⓪Plan runs the bench rounds. |
| Rule | One loop. A goal is a task whose acceptance checks are the goal, run by today's `_run_native`. Goal mode adds no tool, no permission and no second loop. Every call goes through the same gates in the same order. With no goal set, every pinned LOOP1 turn is byte-identical. |
| Size | About 1,300 product lines in 5 code PRs of about 400 lines or less, each from main and not stacked, plus a bench PR, a mock PR and a report. |

## Reference
Pinned links. Claude Code is closed source, so its docs are cited.
- **Codex `/goal`.** A model-facing `update_goal` tool takes `complete`, `blocked` or `paused`, and `blocked` is allowed only after the same blocker repeats for 3 consecutive goal turns ([spec.rs](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/ext/goal/src/spec.rs#L60)). The statuses are active, paused, blocked, usage-limited, budget-limited and complete ([thread_goal.rs](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/state/src/model/thread_goal.rs#L14)). A continuation prompt asks for a requirement-by-requirement completion audit and sorts each turn into progress, a verified wait or no progress. It also says a goal is never marked complete because the budget is running out ([continuation.md](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/ext/goal/templates/goals/continuation.md)).
- **Claude Code.** In [/goal](https://code.claude.com/docs/en/goal), a small model with no tools judges after each turn whether the condition holds. A [Stop hook](https://code.claude.com/docs/en/hooks) can refuse the stop and return a reason to continue. Plan mode and the todo list show progress.
- **Hermes.** After each turn a judge returns `done`, `blocked`, `continue` or `wait` ([goals.py](https://github.com/NousResearch/hermes-agent/blob/9373dc1e315a68446f9767afd7acd15d4c0642b8/hermes_cli/goals.py#L117)), with a 20-turn default ([:32](https://github.com/NousResearch/hermes-agent/blob/9373dc1e315a68446f9767afd7acd15d4c0642b8/hermes_cli/goals.py#L32)). Shell "gates" have to pass before a goal can complete ([goal_command.py](https://github.com/NousResearch/hermes-agent/blob/9373dc1e315a68446f9767afd7acd15d4c0642b8/hermes_cli/goal_command.py#L81)).
- **OpenClaw.** A goal is session state that survives restarts and keeps going after a final reply, with `/goal` start, edit, pause, resume and clear, a token budget, and a status footer ([goal.md](https://github.com/openclaw/openclaw/blob/44a2948a9eaf4345069d4b652ae382d10dd08f62/docs/tools/goal.md)).
- **Others.** Kilo reports `complete` or `blocked` ([policy.ts](https://github.com/Kilo-Org/kilocode/blob/2649e61b9eca9619f0dcbd3b2c53deb04c8b26ab/packages/opencode/src/kilocode/session/goal/policy.ts#L13)). Goose recipes run shell success checks, with an on-failure step ([retry.rs](https://github.com/block/goose/blob/721edae7284910176fb5d32d6c332aabcb1f738a/crates/goose/src/agents/retry.rs#L14)). OpenHands detects a stuck agent from repeated actions, errors, monologue and alternation ([stuck_detector.py](https://github.com/OpenHands/software-agent-sdk/blob/5ff99f1b6ca28f7d16870b69f57a31351e59bcd0/openhands-sdk/openhands/sdk/conversation/stuck_detector.py#L109)). In Cline the model declares the end with `attempt_completion`, and the user's feedback continues the work ([tools.ts](https://github.com/cline/cline/blob/c5df41f937c496ce8c8e689ba58776593c703dfa/apps/vscode/src/shared/tools.ts#L10)). Devin-like hosted agents are closed and weren't checked.
- **What everyone shares:** an explicit goal set by the user; a check that isn't the worker's word alone; "blocked" only after repeats; a budget that stops the goal without marking it done; and a visible status.
- **Taken:** Codex's 3-round blocked audit and its rule that the budget is never a reason for "complete"; Hermes's and Goose's command checks; the judge from Claude Code and Hermes, here with evidence; OpenClaw's `/goal` verbs.
- **Rejected:**
  - A model-facing `update_goal` tool. It would change the tool table and K3's cached prefix, and let the worker mark its own goal done. Here the host decides from the checks and receipts.
  - A judge that re-starts new turns from outside the loop (Hermes). Rounds continue inside `_run_native`, so the budget, gates and pins are the same ones.
  - Re-deriving goal state from the transcript.
- **Seen, for the user to decide, not built:** Hermes's `wait` verdict, which parks a goal on a running process (it belongs with L6); a per-goal token figure in the status (Codex, OpenClaw); phone buttons for pause and resume (they need a frame).

## Raw material (main `3b8168f0`)
- **The loop.** `tool_loop.py:821` `run_native` builds `TurnRequest` and `TurnState` (`turn_state.py:20`, `:48`). `_run_native:1287` runs the steps. A step that answers goes to `turn_answer.finish`, and a `None` back means the next step answers again. That return is the only way to continue, and goal rounds use it.
- **Acceptance already in the turn.**
  - A task's checks are added to the system text at `tool_loop.py:936`, as "these do not grant tools or permissions".
  - `turn_answer.py:113-137` repairs failed checks at most twice per distinct report (`Progress.validation_repairs`, `max_length=2`, `task_repository.py:44`) and then holds the task with `task_validation_failed`.
  - Model-evaluated checks see only the answer text, never receipts (`task_validation.py:314-348`). A critical check can't be model-only (`contracts.py:110`).
- **Stops.** `ProgressPolicy` (`runtime_policy.py:71`) stops after the same evidence 4 times or the same failing call 3 times. `_step_mode:1060` then enters finish mode: save tools only, then text. The soft limit is the user's tier (`execution_budget.py:49`); the hard limit is 1.5 times that (`:57`); the dollar cap defaults to $2 (`:66`). Pins include `job_stops_on_no_progress` and `job_saved_then_no_progress`; there are 154 in `tests/server/golden/loop1/`.
- **Jobs are almost goals.**
  - `background_jobs.Job:39` has a goal, criteria and the outcomes done, partial, blocked and stopped. `criteria_to_acceptance:84` turns criteria into checks.
  - `_goal_not_reached:353` asks the `job.accomplished` judge (`judgment.py:97`) only when a job has no checks of its own. `turn.completion` is registered and off.
  - A restart cancels jobs and says so once (`:529`).
  - The phone shows a job's title, step, n of m and a checklist from `job_update` (`FrameMapper.swift:322`).
- **Resume and steering.**
  - `task_service.prepare_resume:1060` refuses a changed goal (`task_goal_changed`) and carries `Progress`. `resume_turn:1104` fences completed writes.
  - K9b steering keeps one box per conversation (`steering.py:61`, `:74`). `tool_batch.py:147` skips calls that haven't started when a message waits (pin `message_waiting_before_the_first_call`).
  - Jobs aren't steerable today.

## Design
- **What a goal is.** An objective (up to 4,000 characters) and up to 5 criteria, in the kinds `criteria_to_acceptance` already knows: file saved, sources read, mentions, judgement. The user can add `check: <command>` lines. Each one becomes a deterministic, critical `code_test` check.
  - **The record.** It's a task row with driver `{"kind": "background", "goal": true}`. Its state maps onto existing phases: active is running; complete is succeeded; blocked, paused and budget-limited are `waiting_user` with `goal_blocked`, `goal_paused` or `task_budget_exhausted`; cleared is cancelled. No new table and no migration.
- **How it's set.**
  - `/goal <objective>` in chat, from the Mac, the phone or a voice transcript. It's parsed at the chat entry (`arslan.py`) before any model call, and the reply is one host line.
  - Verbs: `/goal status`, `edit`, `note`, `pause`, `resume`, `clear`.
  - From a task: the card's "Keep going until met" button on a running or finished job starts a goal with that job's criteria (`criteria_from_acceptance`). No tool schema changes. The model never starts goal mode on its own (Q2).
  - At start, one request with no tools drafts the criteria. They show on the goal card, where the user can edit them, and work starts at once.
- **Where it runs.** As a background job, so the conversation stays free and the user can keep talking by voice. It goes through `task_service.run_turn` and then the same `run_native`. The job's acceptance is the goal.
- **How it continues.** A round is one answer. In `turn_answer.finish`, after the guards and the acceptance checks, at the point where today's repair goes:
  - all checks pass, with receipts, means the goal is met;
  - otherwise one host message goes back to the model: "Goal round n. Not met: <ids, each with why>. Keep the full objective, work within the existing scope, permissions and remaining budget, and check before claiming." The function returns `None`, and the next step continues.
  - This replaces the repair limit of 2 for goal tasks only. The system text and the tools don't change, so K3's prefix holds.
- **How done is decided.** Deterministic checks first, then the model checks.
  - A model check may say "met" only by citing receipts: index numbers into this run's trace of successful calls (written bytes and sha256, exit codes, files read). A "met" with no receipt, or one that cites a failed call, counts as not met.
  - Receipts and outside text reach the judge framed as data (`untrusted.wrap_external`). A page that says "goal achieved" proves nothing.
  - Human criteria end the goal at `acceptance_review_required`, and the user confirms on the card as today.
  - The worker's own claim is never enough, as with STY2's "done without evidence".
- **No progress.**
  - In-turn: `ProgressPolicy` stays as it is. Its stop wraps up and delivers as today, and the goal ends blocked.
  - Across rounds: a round makes progress when the set of unmet checks shrinks, or a receipt appears that wasn't there before (a new path, sha256 or exit code). After 3 rounds in a row with no progress and the same unmet set, the goal is `blocked` (Codex's audit). The reply says what is done, the blocker, and one step for the user (SMART's guidance rule). Resume starts a fresh audit.
- **Budgets: wrap up and deliver.** A goal runs on the job's tier and dollar cap and never raises them itself (Q3).
  - At the soft limit, today's finish mode saves and answers. The goal becomes budget-limited, never complete, and the message lists what was done, what isn't met, and Resume.
  - Resume is the existing `resume_turn` path with a fresh budget of the same tier. Completed writes are fenced, and `Progress` is carried.
- **Interruption and steering.**
  - Stop works as for any job.
  - `/goal edit` raises the spec revision. The next round reads the new objective, and the blocked audit restarts.
  - `/goal note <text>`, or the card's note field, steers the running goal through K9b. The goal job's turn is steerable under its own key, `TurnRequest.steer_key = job id`, so chat messages never land in it. Then K9b applies as pinned: calls that haven't started are skipped, the next request carries the note, and anything unread goes back.
- **Restart and app quit.**
  - Each round's verdict and counters (round, unmet ids, no-progress streak, last receipt index) are written as `Progress.goal` in the same checkpoint as the verdict (`checkpoint("goal_round")`), before the continuation message goes out.
  - On boot, the interrupted goal shows "interrupted at round n" and a Resume (Q5). The state is read from the checkpoint and never counted from the transcript.
  - Restart matrix, each case with a test:
    - quit during a model call or a tool call: the round re-runs, and the journal fences writes;
    - quit between the verdict and the checkpoint: the round re-runs once;
    - quit during wrap-up: the goal is budget-limited at resume;
    - quit after "complete" and before the post: the goal stays complete and the post is retried.

## Fit with LOOP1
- **`TurnRequest`** gets `goal: GoalSpec | None = None` and `steer_key: str | None = None`. **`TurnState`** gets `goal_round`, `goal_stall` and `goal_unmet`.
- **No new phase in `_run_native`.** The goal round is a step inside `turn_answer.finish`, after the acceptance checks. `_step_mode`, `_request`, `tool_batch.run_batch`, `_admit` and the gates are untouched, so gate order is unchanged by construction.
- **`check:` commands** run as host calls through `_run_tool`, as `_presearch` does (`tool_loop.py:1038`). They pass every gate a model's `run_command` passes: card, sandbox, offline. Nothing about them is pre-approved.
- **The guard.** With `goal=None`, all 154 LOOP1 pins and the 51-case tool-table dump are identical. Each PR gives the base and head hashes.

## Bench plan
- **Baselines, written:**
  - `r64-m64-base` for T13–T17, the hand-checked table in #453. Arslan's same-task Pass^3 is 2/3; T14 and T15 are 3/3; T17 is 3/3.
  - R63's recompute for T1–T12: Arslan on DeepSeek 6/9 overall, 5/7 same-task ([kernel bench README](../../../scripts/kernel_bench/README.md)).
  - STY2: 20 of 27 passed (#658).
  - Each L7 round also runs a paired goal-off arm on the same main SHA, and the comparison uses that arm. The written numbers are floors.
  - Results go to a persistent folder before the run. The table is committed to this card.
- **L7-0 adds** T18, a goal task: 20 synthetic invoices, sort them and reconcile the totals. Its checker recomputes the totals. It also adds `BENCH_GOAL=1`: the driver turns the setting on in the fresh instance and sends `/goal ` before the prompt, so criteria are Arslan's own.
- **Runs:** DeepSeek, Arslan only, k=3, two arms, T2, T3, T5, T7–T11, T13–T15, T17 and T18 (13 tasks, 78 runs). Off-peak.
  ```
  scripts/kernel_bench/start_proxy.sh   # BENCH_CAP_USD=10, BENCH_RUN_CAP_USD=2.5
  T=T2,T3,T5,T7,T8,T9,T10,T11,T13,T14,T15,T17,T18
  BENCH_ROUND=r64-l7-off BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-on BENCH_GOAL=1 BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  .venv/bin/python -m scripts.kernel_bench.report --offpeak --round r64-l7-off   # and --round r64-l7-on
  .venv/bin/python -m scripts.kernel_bench.done_without_evidence results.jsonl --round r64-l7-on   # and -off
  ```
- **Cost:** about $6 at DeepSeek peak prices. `r64-m64-base` cost about $1.71 for 48 runs; T2 and T3 cost more; the goal arm is assumed to cost up to 1.5 times as much. A 402 stops the round, and it's reported.
- **"Doesn't regress" means all of these, goal-on against goal-off:**
  - same-task Pass^3 is not lower;
  - total passing runs are at least off minus 1;
  - no task loses 2 or more runs;
  - the T13–T15 floors from #453 hold;
  - STY2's three done-without-evidence counts are not higher;
  - median cost and wall time per passing run are at most 1.5 times.
  - A task that misses gets one more k=3 rerun. A miss on the rerun blocks the merge. T18 is expected to improve, and is reported rather than gated.
- **SMART-5 and STY2.** Chat turns carry no goal, so the pins prove those paths unchanged. Both are rerun at ⓪Plan's next bench, as for LOOP1.
- **Flag.** The `goal_mode` setting (Settings → Advanced) is off until the round passes. The code reads `goal_mode` in one place, `/goal` parsing, and with the flag off `/goal` is plain text. `DELETE-BY: v0.1.65` once the default is decided (Q6).

## Method and PRs
Red tests first, as new pinned scenarios:
- the goal is met in round 1;
- a check is unmet, then met;
- blocked after 3 rounds with the same unmet set;
- budget-limited: it wraps up, delivers, and is never complete;
- a "met" without a receipt is not met;
- a page that says "goal achieved" is not met;
- a note before the first call (K9b under `steer_key`);
- `ProgressPolicy` still stops;
- a `check:` command gets the same card as `run_command` (added to the gate-order matrix);
- the restart matrix.

Mutations, each turning a named test red:
- the blocked threshold set to 2;
- the receipt rule dropped;
- a goal that raises its own budget;
- `check:` sent around `_run_tool`;
- the round counted from the transcript;
- `steer_key` falling back to the conversation.

| PR | What | Lines | Review |
|---|---|---|---|
| L7-0 | Bench: T18, `BENCH_GOAL`, and the paired off-arm baseline, committed here | bench only | high |
| L7-m | Mock: the goal card, the composer chip, and the phone's existing job card | docs | the user OKs |
| L7-1 | Types and red tests: `GoalSpec`, the `TurnRequest` and `TurnState` fields, `Progress.goal`, the setting. Nothing reads them yet; the pins and dump hashes are identical | ~150 | high |
| L7-2 | The goal round in `turn_answer.finish`: verdict, receipts for model checks, continuation, the blocked audit, the per-round checkpoint | ~400 | high |
| L7-3 | `/goal` verbs at the chat entry, criteria drafting, goal jobs with `steer_key`, status mapping, the boot pass, Resume | ~400 | high |
| L7-4 | `check:` commands as host calls through `_run_tool` | ~120 | max (command policy) |
| L7-5 | Web: the goal card and the chip, after the mock | ~350 TS | high |
| L7-6 | The on and off rounds, the report here, the flag default to the user | docs | — |

## UI (a mock first, L7-m)
- **Mac.**
  - The existing `JobCard` gains the round, spend against the cap, the blocker line, and Pause, Resume, Edit, Note and Stop.
  - A chip above the composer shows an open goal's objective and n of m.
  - The island keeps the job's title (`desktop_status.working`).
  - The new fields ride as one optional `goal` object on the backend `job_update` frame, read by the web only.
- **Phone.** No new Bridge frame. `job.event` already carries the title, the step, n of m and the checklist. The round and blocker go in `current_step`, and pause, resume and note are `/goal` text sent through `chat.send`.
- **If the reviewer of L7-5 counts the optional field as a Bridge change,** it goes to the user to merge.

## External evidence
For each PR: the CI run id on all five checks, the pin and dump hashes on base and head, and the mutations. For the card: the two bench rounds against the written floors, with run ids and spend. A real-Mac check with the user: `/goal` on T18-style work, quit mid-round, Resume.

## Open questions (recommended answer first)
1. **Where a goal runs:** as a background job, so the user can talk while it works. The alternative is the chat turn.
2. **Who sets one:** only the user, with `/goal` or the job card's button. The model never starts one itself.
3. **Budget:** the job tier and dollar cap, plus an optional per-goal `$N` up to the Settings maximum. Never raised automatically.
4. **At the limit:** wrap up, deliver, and offer a one-tap Resume. Don't auto-extend.
5. **After a restart:** Resume with one tap. Don't auto-resume, since a quit may have been a stop.
6. **Flag default at the tag:** on if the round passes. With no goal set, turns are byte-identical.
7. **Judge model:** the turn's own model, with no tools. A cheaper fixed model would save money but could disagree with the worker's model.
