# L7: goal mode, keep working until the goal is met

| | |
|---|---|
| Decided | The user, 2026-10-28: L7 stays in v0.1.64 as "should", and it merges only if the M64 bench doesn't regress ([README](README.md) §1.1, §3 row "other execution-first rows"; [lead roadmap](../2026-10-17-0162-lead-roadmap.md) L7). ⓪Plan's ruling (2026-11-11): the bench gates the merge itself. It runs on the build branch, with the flag both off and on, before any L7 code PR merges. It doesn't only decide the flag default. |
| Version | v0.1.64, should |
| Lane | ②Main writes the card and the code. ⓪Plan runs the bench rounds. |
| Rule | One loop. A goal is a task whose acceptance checks are the goal, run by today's `_run_native`. Goal mode adds no tool, no permission and no second loop. Every call goes through the same gates in the same order. With no goal set, the turn behaves as today, and z3's permanent tests are the guard (Fit with LOOP1). |
| Size | About 1,400 product lines in 6 code PRs of about 400 lines or less, each from main and not stacked, plus a bench PR, a mock PR and a report. |

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
  - A judge that re-starts new turns from outside the loop (Hermes). Rounds continue inside `_run_native`, so the budget and the gates are the same ones.
  - Re-deriving goal state from the transcript.
- **Seen, for the user to decide, not built:** Hermes's `wait` verdict, which parks a goal on a running process (it belongs with L6); a per-goal token figure in the status (Codex, OpenClaw).

## Raw material (main `c8163075`)
- **The loop.** `tool_loop.py:821` `run_native` builds `TurnRequest` and `TurnState` (`turn_state.py:20`, `:48`). `_run_native:1287` runs the steps. A step that answers goes to `turn_answer.finish` (`:1330`), and a `None` back means the next step answers again. That return is the only way to continue, and goal rounds use it.
- **Acceptance already in the turn.**
  - A task's checks are added to the system text at `tool_loop.py:936`, as "these do not grant tools or permissions".
  - `turn_answer.py:107-133` repairs failed checks at most twice per distinct report, and never on a forced step (`:115`). The limit is `Progress.validation_repairs`, `max_length=2` (`task_repository.py:44`). After that the task is held with `task_validation_failed`.
  - Model-evaluated checks see only the answer text, never receipts (`task_validation.py:314-339`). A critical check can't be model-only (`contracts.py:118`).
  - `code_test` passes on the last `run_command` in the trace with the same command and argv (`task_validation.py:239-253`).
- **Stops.** `ProgressPolicy` (`runtime_policy.py:71`) stops after the same evidence 4 times or the same failing call 3 times. `_step_mode:1060` then enters finish mode: save tools only, then text. The soft limit is the user's tier (`execution_budget.py:49`); the hard limit is 1.5 times that (`:57`); the dollar cap defaults to $2 (`:66`).
- **Jobs are almost goals.**
  - `background_jobs.Job:39` has a goal, criteria and the outcomes done, partial, blocked and stopped. `criteria_to_acceptance:84` turns criteria into checks.
  - The `job_update` frame already sends the objective as the string `goal` (`:72`). The web reads it as the title (`arslanStore.ts:557`, `:570`). So does the Bridge, for the phone's `job.event` (`FrameMapper.swift:334`).
  - `_job_sink` writes each tool step into `step`.
  - `start_background_work` already takes a required `goal` string, the job's objective (`registry/tool_defs/tasks.py:85`).
  - `_goal_not_reached:353` asks the `job.accomplished` judge (`judgment.py:97`) only when a job has no checks of its own. `turn.completion` is registered and off (`:113`).
  - The boot pass cancels every interrupted background row and says so once (`:529-552`).
- **Resume and steering.**
  - `checked_driver` (`task_service.py:961-967`) accepts exactly `{"kind": "host"}` or `{"kind": "background"}`.
  - `prepare_resume:1060` refuses a changed goal (`task_goal_changed`), drops grants and carries `Progress`. `resume_turn:1104`, reached from the socket's `resume_task` (`ws/arslan.py:598-613`), runs the task again as a foreground turn in the socket's lock, `steerable=True`.
  - K9b steering keeps one box per conversation (`steering.py:59-80`). `tool_batch.py:147` skips calls that haven't started when a message waits.
  - Jobs aren't steerable: `background_body` has no `steerable`.
- **Entry points.** `handle_user_message` (`arslan.py:266`) is called only from the socket (`ws/arslan.py:577`, `:643`). `_handle_answer` is also reached by the scheduler (`scheduler.py:433`) and by `resume_turn` with the saved instruction (`task_service.py:1121`).
- **Tests.** z2 (#837) deletes the 154 L0 pins, the gate-order pin matrix and the 51-case tool-table dump. z3 (#841) replaces them with permanent tests.

## Design
- **What a goal is.** An objective (up to 4,000 characters) and up to 5 criteria, in the kinds `criteria_to_acceptance` already knows: file saved, sources read, mentions, judgement.
  - **User checks.** Only the user's own `check: <command>` lines become deterministic, critical `code_test` checks. Criteria drafting never produces `check:` lines. A matching `run_command` by the worker also satisfies a check: it's the same command and argv, through the same gate.
  - **The record.** It's a task row with driver `{"kind": "background", "goal": true}`. `checked_driver` widens by exactly that one dict. Its state maps onto existing phases: active is running; complete is succeeded; blocked, paused, budget-limited and interrupted are `waiting_user` with `goal_blocked`, `goal_paused`, `task_budget_exhausted` and `process_interrupted`; cleared is cancelled. No new table and no migration.
- **How it's set: one entry point.**
  - `/goal` is parsed in `handle_user_message` and nowhere else, before any model call, and the reply is one host line. It works from the Mac, from the phone (`chat.send` arrives there) and from a voice transcript.
  - Verbs: `/goal <objective>`, `status`, `edit`, `note`, `pause`, `resume`, `clear`.
  - From a job: the card's "Keep going until met" button starts a goal with that job's criteria (`criteria_from_acceptance`).
  - `start_background_work`'s `goal` string stays the job's objective and never sets goal mode. No tool schema changes, and the model never starts goal mode on its own (Q2).
  - At start, one request with no tools drafts the criteria. The user can edit them on the card, and work starts at once.
- **Where it runs.** As a background job (Q1), so the conversation stays free and the user can keep talking by voice. It goes through `task_service.run_turn`, then the same `run_native`, with `JobConfirmations` for its cards. The job's acceptance is the goal.
- **How it continues.** A round is one answer, judged in `turn_answer.finish` at the point where today's repair goes, after the guards and the acceptance checks.
  - If every check passes, with receipts, the goal is met.
  - Otherwise one host message goes back to the model: "Goal round n. Not met: <ids, each with why>. Keep the full objective, work within the existing scope, permissions and remaining budget, and check before claiming." The function returns `None`, and the next step continues.
  - **No goal round on a forced step or in wrap-up.** It keeps today's `not forced`, so the soft limit stays the point where the goal stops. Without that, the 1.5x hard limit would become the real one.
  - This replaces the repair limit of 2 for goal tasks only. The system text and the tools don't change, so K3's prefix holds.
- **How done is decided.** Deterministic checks first, then the model checks.
  - A model check may say "met" only by citing a receipt from this run's trace: a successful call that fits the criterion. A file criterion needs a write or read of its path, with bytes and sha256. A sources criterion needs a read. A command criterion needs its exit code.
  - A "met" with no receipt, with a receipt from a failed call, or with one that doesn't fit counts as not met.
  - Receipts and outside text reach the judge framed as data (`untrusted.wrap_external`). A page that says "goal achieved" proves nothing.
  - Human criteria end the goal at `acceptance_review_required`, and the user confirms on the card as today.
  - The worker's own claim is never enough, as with STY2's "done without evidence".
- **No progress.**
  - In-turn: `ProgressPolicy` stays as it is. Its stop wraps up and delivers as today, and the goal ends blocked.
  - Across rounds: a round makes progress when the set of unmet checks shrinks, or a new receipt fits an unmet check. A rewrite of an unrelated file, or the same receipt again, doesn't count. After 3 rounds in a row with no progress and the same unmet set, the goal is `blocked` (Codex's audit).
  - The reply says what is done, the blocker, and one step for the user (SMART's guidance rule). Resume starts a fresh audit.
- **Budgets: wrap up and deliver.** A goal runs on the job's tier and dollar cap and never raises them itself (Q3). At the soft limit, today's finish mode saves and answers. The goal becomes budget-limited, never complete, and the message lists what was done, what isn't met, and Resume.
- **Resume re-queues the job.** It never uses `resume_turn` or the chat socket. Resume comes from `/goal resume` or the card. It runs `prepare_resume` on the goal row, so a changed goal is refused, grants are dropped, completed writes stay fenced in the journal, and `Progress` is carried. Then the same row runs again as a background job: `JobConfirmations`, `steer_key`, and a fresh budget of the same tier and cap. `resume_turn` refuses a goal row. This covers resuming after a block, a budget stop, a pause and a restart.
- **Interruption and steering.**
  - Stop works as for any job.
  - `/goal edit` raises the spec revision. `prepare_resume` already keeps only evidence, artifacts and `continuation_ref` across a revision, so the blocked audit restarts. A running goal reads the new objective at its next round.
  - `/goal note <text>`, or the card's note field, steers the running goal through K9b. The goal job's turn is steerable under its own key, `TurnRequest.steer_key = job id`, so chat messages never land in it. Calls that haven't started are skipped, the next request carries the note, and anything unread goes back.
- **Restart and app quit.**
  - Each round's verdict and counters (round, unmet ids, no-progress streak, last receipt index) are written as `Progress.goal` in the same checkpoint as the verdict (`checkpoint("goal_round")`), before the continuation message goes out.
  - The boot pass skips goal rows. They stay `waiting_user` with `process_interrupted`, and nothing cancels them. The card reads "interrupted at round n" from the last checkpoint, never from the transcript, and offers Resume (Q5).
  - Restart matrix, one test per row:
    - quit during a model call or a tool call: the row is interrupted; Resume re-runs that round, and the journal fences writes;
    - quit between the verdict and its checkpoint: the round isn't recorded, so Resume runs it once more;
    - quit during wrap-up: the row is interrupted, and Resume starts a fresh budget;
    - quit after "complete" and before the result is posted: the row is succeeded, and the post goes out on boot;
    - quit while paused, blocked or budget-limited: the row is unchanged.

## Fit with LOOP1
- **`TurnRequest`** gets `goal: GoalSpec | None = None` and `steer_key: str | None = None`. **`TurnState`** gets `goal_round`, `goal_stall` and `goal_unmet`.
- **No new phase in `_run_native`.** The goal round is a step inside `turn_answer.finish`, after the acceptance checks. `_step_mode`, `_request`, `tool_batch.run_batch`, `_admit` and the gates are untouched, so gate order is unchanged by construction.
- **`check:` commands** run as host calls through `_run_tool`, as `_presearch` does (`tool_loop.py:1038`). `_run_tool` passes `_admit` and every gate (`:493-560`): card, sandbox, offline. Nothing about them is pre-approved.
- **The guard (⓪Plan's ruling).** z3's permanent tests (#841) replace the L0 pins. With no goal set, each L7 code PR keeps them green unchanged:
  - `test_gate_order.py`;
  - `test_turn_refusal_stops.py`, `test_turn_steering.py`, `test_turn_branches.py`, `test_turn_answer_guards.py` and `test_turn_executor_calls.py`;
  - `test_command_gate_refusals.py`.
  - For "no tool schema change", the guard is z3's permanent behavioural tool-table test: each case offers the same tools with the same schemas. It is also run once with the flag on and a goal set. Until it lands on main, L7-1 doesn't open.

## Bench plan
- **When.** The L7 code PRs (L7-1 to L7-6) are reviewed one by one from main and wait, approved and unmerged. ⓪Plan merges their heads into a build branch and benches it. Only if the bench passes do they merge, in order. A PR rebased after the bench must leave the build branch's L7 files unchanged, or the bench reruns. Flag-off code that changes the loop counts: the flag-off arm is benched too.
- **Arms, all on DeepSeek, Arslan only, k=3, with fresh instances:**
  - `base`: main before L7;
  - `off`: the build branch with the flag off;
  - `on`: the build branch with the flag on and every prompt sent as a goal.
- **Tasks:** T1, T2, T3, T5, T7–T11 (STY2's 9 tasks), T13–T15 and T17 (M64), and T18. That's 14 tasks and 126 runs, on STY2's model (deepseek-v4-pro), off-peak.
- **L7-0 adds** T18, a goal task: 20 synthetic invoices, sort them and reconcile the totals. Its checker recomputes the totals. It also adds `BENCH_GOAL=1`: the driver turns the setting on in the fresh instance and sends `/goal ` before the prompt, so the criteria are Arslan's own.
  ```
  scripts/kernel_bench/start_proxy.sh   # BENCH_CAP_USD=12, BENCH_RUN_CAP_USD=2.5
  T=T1,T2,T3,T5,T7,T8,T9,T10,T11,T13,T14,T15,T17,T18
  # on main before L7, then twice on the build branch (the second time with BENCH_GOAL=1)
  BENCH_ROUND=r64-l7-base BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-off  BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-on   BENCH_GOAL=1 BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  .venv/bin/python -m scripts.kernel_bench.report --offpeak --round r64-l7-base   # and -off, -on
  .venv/bin/python -m scripts.kernel_bench.done_without_evidence results.jsonl --round r64-l7-base   # and -off, -on
  ```
  The user cleans up T1's Reminders lists afterwards (`cleanup_t1 --delete --yes`). Results go to a persistent folder before the run, and the tables are committed to this card.
- **Written floors.** Each arm must also meet these on its own tasks:
  - STY2 (#658, rounds `sty2c-before-ds` and `sty2d-after-ds`): 20 of 27 passed, and done-without-evidence 4, on the same 9 tasks.
  - M64 (#453, `r64-m64-base`): T13 2/3, T14 3/3, T15 3/3, T17 3/3.
- **Cost:** about $9 at DeepSeek peak prices. `r64-m64-base` cost about $1.71 for 48 runs; T1–T3 cost more; the `on` arm is assumed to cost up to 1.5 times as much. A 402 stops the round, and it's reported.
- **"Doesn't regress" means all of these,** for `off` and for `on`, each against `base`:
  - **Pass^3:** here, the number of tasks passing 3 of 3 in that arm (one entrant, the same 14 tasks) is not lower;
  - total passing runs are at least `base` minus 1, and no task loses 2 or more runs;
  - the done-without-evidence count is not higher (the two stricter counts are reported, not gated);
  - the written floors hold;
  - median cost and wall time per passing run are at most 1.5 times (`on` only; `off` must match within noise).
  - #453's rule applies: every T13–T15 verdict that changes the result is checked by hand.
  - A task that misses gets one more k=3 rerun, and a miss on the rerun blocks the merge. T18 is expected to improve under `on`. It's reported, not gated.
- **SMART-5** runs once on `off`, single-turn chat with no goal, against its last passing round.
- **Flag.** The `goal_mode` setting (Settings → Advanced) is read in one place, `/goal` parsing in `handle_user_message`. With the flag off, `/goal` is plain text. Its default at the tag goes to the user after the bench (Q6). `DELETE-BY: v0.1.65` once the default is decided.

## Method and PRs
Red tests first:
- the goal is met in round 1;
- a check is unmet, then met;
- blocked after 3 rounds with the same unmet set;
- a rewrite of an unrelated file isn't progress;
- budget-limited: it wraps up, delivers, and is never complete;
- no goal round on a forced step;
- a "met" without a receipt, with a failed receipt or with an unfitting one is not met;
- a page that says "goal achieved" is not met;
- a note before the first call (K9b under `steer_key`), and a chat message that never reaches the goal;
- `ProgressPolicy` still stops;
- a `check:` command gets the same card as `run_command` (in `test_gate_order.py`);
- drafting never produces `check:`;
- `/goal` is plain text in a scheduled prompt, a resumed instruction (`resume_turn`) and a `start_background_work` goal string;
- `resume_turn` refuses a goal row;
- the boot pass leaves goal rows interrupted;
- the restart matrix.

Mutations, each turning a named test red:
- the blocked threshold set to 2;
- the receipt rule or the fit rule dropped;
- a goal round allowed on a forced step;
- a goal that raises its own budget;
- `check:` sent around `_run_tool`;
- the round counted from the transcript;
- `steer_key` falling back to the conversation;
- `/goal` parsed in `_handle_answer`;
- the boot pass cancelling goal rows.

| PR | What | Lines | Review |
|---|---|---|---|
| L7-0 | Bench: T18, `BENCH_GOAL` | bench only | high |
| L7-m | Mock: the five UI items below | docs | the user OKs |
| L7-1 | Types and red tests: `GoalSpec`, the `TurnRequest` and `TurnState` fields, `Progress.goal`, the setting, the `checked_driver` dict. Nothing reads them yet | ~150 | high |
| L7-2 | The goal round in `turn_answer.finish`: verdict, receipts and fit, continuation, the blocked audit, the per-round checkpoint | ~400 | high |
| L7-3 | `/goal` in `handle_user_message`, criteria drafting, goal jobs with `steer_key`, status mapping | ~350 | high |
| L7-4 | Resume as a re-queued job, the boot pass skipping goal rows, `resume_turn` refusing them | ~200 | high |
| L7-5 | `check:` commands as host calls through `_run_tool` | ~120 | max (command policy) |
| L7-6 | Web: the goal card and the chip, after the mock, plus the `goal_state` key on `job_update`. **A Bridge frame change, so the user merges it** | ~350 | high |
| L7-7 | The three bench rounds, the report here, then the merges in order; the flag default goes to the user | docs | — |

## UI (a mock first, L7-m)
- **The mock covers five items:**
  1. the goal card: the existing `JobCard` with the round, spend against the cap, the blocker, and Pause, Resume, Edit, Note and Stop;
  2. the composer chip, with the objective and n of m;
  3. the step where the user edits the drafted criteria at start;
  4. "Keep going until met" on a job card;
  5. "interrupted at round n" with Resume, which re-queues the job.
- **Plus** a Settings toggle, which is small. The island keeps the job's title (`desktop_status.working`).
- **The frame.** The goal's state rides on the backend `job_update` frame under a new key, `goal_state`: status, round, met and total, spend and cap, and the blocker. The existing `goal` string stays the objective and the title. The Bridge reads `job_update`, so adding the key is a Bridge frame change, and the user merges L7-6. In v0.1.64 the Bridge passes `goal_state` through unread.
- **Phone.** The phone shows the job card it has today: title, the current step, n of m and the checklist. The round and blocker don't show there, because `_job_sink` overwrites `step` with each tool step. Pause, resume and note are `/goal` text sent through `chat.send`. Mapping `goal_state` into `job.event` is Q8.

## External evidence
- For each PR: the CI run id on all five checks, z3's tests green and unchanged, and the mutations.
- For the merge: the three bench rounds against `base` and the written floors, with run ids and spend.
- A real-Mac check with the user: a `/goal` on T18-style work, a quit mid-round, then Resume.

## Open questions (recommended answer first)
1. **Where a goal runs:** as a background job, so the user can talk while it works. The alternative is the chat turn.
2. **Who sets one:** only the user, with `/goal` or the job card's button. The model never starts one itself.
3. **Budget:** the job tier and dollar cap, plus an optional per-goal `$N` up to the Settings maximum. Never raised automatically.
4. **At the limit:** wrap up, deliver, and offer a one-tap Resume. Don't auto-extend.
5. **After a restart:** Resume with one tap. Don't auto-resume, since a quit may have been a stop.
6. **Flag default at the tag:** on, if the bench passes. With no goal set, turns are unchanged.
7. **Judge model:** the turn's own model, with no tools. A cheaper fixed model would save money but could disagree with the worker's model.
8. **The phone's goal fields** (round, blocker, status in `job.event`): in v0.1.65 with ①iOS. In v0.1.64 the phone shows the plain job card.
