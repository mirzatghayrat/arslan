# L7: goal mode, keep working until the goal is met

| | |
|---|---|
| Decided | The user, 2026-10-28: L7 stays in v0.1.64 as "should", and it merges only if the M64 bench doesn't regress ([README](README.md) §1.1, §3 row "other execution-first rows"; [lead roadmap](../2026-10-17-0162-lead-roadmap.md) L7). ⓪Plan's ruling (2026-11-11): the bench gates the merge itself. It runs on the build branch, with the flag both off and on, before any L7 code PR merges. It doesn't only decide the flag default. The user decided on 2026-11-11: every open question, Q0 to Q8, goes as this card recommends (Decisions, at the end); the mock is approved, so L7-m is done; and goals must actually get completed, so the bench also has a completion bar (Bench plan), stopping too early is treated as the main risk (No progress), and checks Arslan can't verify are flagged before Start (Checks Arslan can't verify). |
| Version | v0.1.64, should |
| Lane | ②Main writes the card and the code. ⓪Plan runs the bench rounds. |
| Rule | One loop. A goal is a task whose acceptance checks are the goal, run by today's `_run_native`. Goal mode adds no tool, no permission and no second loop. Every call goes through the same gates in the same order. With no goal set, the turn behaves as today, and z3's permanent tests are the guard (Fit with LOOP1). |
| Size | About 1,550 product lines in 6 code PRs of about 400 lines or less, each from main and not stacked, plus a bench PR, a mock PR and a report. |

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
  - The Bridge builds `job.event` from a fixed list of keys and drops every other key of the frame (`FrameMapper.swift:167-170`, `jobEvent` at `:322-344`). Its other reader of `job_update` reads only `phase`, `run_id` and `job_id` (`ConversationLinks.swift:162-166`).
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
- **Tests.** z2 (#837) deletes the 154 L0 pins, the gate-order pin matrix and the 51-case tool-table dump. z3 (#841) replaces them with permanent tests. #841 is still open. Its first commit (`2ea3f34e`) has no tool-table test; its second (`2ef08212`) adds `test_tool_offer_table.py`, the offered tool table as a permanent test. Neither is on main yet.

## Design
- **What a goal is.** An objective (up to 4,000 characters) and up to 5 criteria, in the kinds `criteria_to_acceptance` knows: file saved, sources read, mentions, judgement. In a goal, a mentions criterion must name a file, and a judgement criterion is judged over a named file's content (The reply never counts).
  - **User checks.** Only the user's own `check: <command>` lines become deterministic, critical `code_test` checks. Criteria drafting never produces `check:` lines. In a goal, only the host's own run of the check, in place and after its protected files verify, satisfies it (Check files are protected from Start). The worker's matching `run_command` is ordinary work and is never the check's receipt.
  - **The record.** It's a task row with driver `{"kind": "background", "goal": true}`. `checked_driver` widens by exactly that one dict. Its state maps onto existing phases: active is running; complete is succeeded; not started, blocked, paused, budget-limited and interrupted are `waiting_user` with `goal_not_started`, `goal_blocked`, `goal_paused`, `task_budget_exhausted` and `process_interrupted`; waiting for the user's own checks is `waiting_user` with `acceptance_review_required`; cleared is cancelled. No new table and no migration.
- **How it's set: one entry point.**
  - `/goal` is parsed in `handle_user_message` and nowhere else, before any model call, and the reply is one host line. It works from the Mac, from the phone (`chat.send` arrives there) and from a voice transcript.
  - Verbs: `/goal <objective>`, `start`, `status`, `edit`, `note`, `pause`, `resume`, `clear`.
  - From a job: the card's "Keep going until met" button sets a goal with that job's criteria (`criteria_from_acceptance`), and it waits for Start like any other goal.
  - `start_background_work`'s `goal` string stays the job's objective and never sets goal mode. No tool schema changes, and the model never starts goal mode on its own (Q2).
  - **Nothing runs until the user presses Start goal (Q0).** Setting a goal runs one request with no tools that drafts the checks. The goal row waits as "not started", and no job, round or tool call runs. The user edits the checks on the card (the mock's edit step) and presses Start goal, or sends `/goal start` from the phone or by voice. Start queues the background job. Editing a running goal shows the same form.
- **Where it runs.** As a background job (Q1), so the conversation stays free and the user can keep talking by voice. It goes through `task_service.run_turn`, then the same `run_native`, with `JobConfirmations` for its cards. The job's acceptance is the goal.
- **How it continues.** A round is one answer, judged in `turn_answer.finish` at the point where today's repair goes, after the guards and the acceptance checks.
  - If every check passes, with receipts, the goal is met.
  - Otherwise one host message goes back to the model: "Goal round n. Not met: <ids, each with why>. Keep the full objective, work within the existing scope, permissions and remaining budget, and check before claiming." The function returns `None`, and the next step continues.
  - **No goal round on a forced step or in wrap-up.** It keeps today's `not forced`, so the soft limit stays the point where the goal stops. Without that, the 1.5x hard limit would become the real one.
  - This replaces the repair limit of 2 for goal tasks only. The system text and the tools don't change, so K3's prefix holds.
- **The reply never counts.** Progress and completion never read the worker's answer text. A reply that claims a check is met, or quotes the check's own words, meets nothing and is no progress.
  - **Today (main `d0968b36`) the reply can meet a check in three places:**
    - a mentions criterion becomes a `text` rule (`background_jobs.py:109-110`), and `evaluate` checks a `text` rule against the answer (`task_validation.py:176-182`);
    - the model judge's only input is the answer (`task_validation.py:313-331`);
    - `answer-delivered` (`task_service.py:957`), the first check of every job (`background_jobs.py:91-92`), passes on any non-empty answer.
  - **What L7-2 changes, for goal tasks only:**
    - `criteria_to_acceptance` (`background_jobs.py:109-110`) turns a mentions criterion that names a file into a new rule, `file_contains` (path and phrases). `evaluate` reads that file on disk through `file_reader.resolve`, as `_file_saved_on_disk` does (`task_validation.py:106-135`), and finds every phrase. A mentions criterion with no file is flagged as one Arslan can't verify. A goal's checks never contain a `text` rule, except `answer-delivered` (itself a `text` rule, `task_service.py:957`), and L7-2 asserts this in `evaluate` (`:176`) with that one exception.
    - The judge call in `validate_output` (`task_validation.py:313-331`) gets the check's text and the named file's current content, read by the host, at most 20,000 characters, framed as data (`untrusted.wrap_external`). It never gets the answer. With no readable file, the check isn't met.
    - `code_test` (`task_validation.py:239-253`) takes the host's own run of the check, never the worker's last `run_command` with the same argv.
    - `answer-delivered` stays a check of the job, but it never counts as progress, and it can't make a goal met by itself.
- **How done is decided.** Deterministic checks first, then the model checks. **A check is met only through its own condition,** never because a receipt names its path or argv:
  - file saved: the file on disk is non-empty and changed since Start (today's `_file_saved_on_disk`);
  - file contains: the host reads the file and finds every phrase;
  - sources read: the trace's successful reads cover the sources;
  - `check:`: the host's run, in place after the protected files verify, exits 0 (and its output contains what the check asks, if anything);
  - judgement: the judge, given the host-read content of the named file, returns met.
  - A write to a named path, a read, or a command run with the check's argv meets nothing by itself. A "met" from a failed call, or from content the host couldn't read, counts as not met.
  - Receipts and file content reach the judge framed as data (`untrusted.wrap_external`). A page or a file that says "goal achieved" proves nothing.
  - Checks the user confirms themselves end the goal at `acceptance_review_required`, and the user confirms on the card as today (Checks Arslan can't verify).
  - The worker's own claim is never enough, as with STY2's "done without evidence".
- **Check files are protected from Start: verify, then run in place.** A `check:` passes only if the work is done, not because the worker changed the check, its tests or its runner's config. Nothing is copied, and the check always runs on the working copies, so it tests the current code. (Running from copies was dropped: a script run from a copy imports stale sibling code, so an honest check could never pass, and runner checks such as `pytest` or `npm test` name no file in their argv and got no protection at all.)
  - **The protected set.** It is fixed at Start and shown on the form, where the user can add or remove entries:
    - every workspace file the check's argv names, except a file the user named or confirmed on the form as the work's own output (such as T21's `clean/orders.csv`). A drafted criterion can't unprotect an argv file. An argv file that doesn't exist at Start and isn't such an output gets a warning on the form;
    - by default, the runner's conventional test, expected-output and config files anywhere in the working folder:
      - test files: everything under `tests/`, `test/`, `__tests__/` and `spec/`; files named `test_*`, `*_test.*`, `*.test.*`, `*.spec.*` or `*_spec.*`;
      - expected outputs: everything under `__snapshots__/`, `testdata/` and `fixtures/`; files named `*.snap` or `golden*`;
      - config: `conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg` and `Makefile`; the test sections of `pyproject.toml` (`[tool.pytest.*]`, `[tool.tox]`, `[tool.coverage.*]`); the `scripts` and `jest` keys of `package.json`; `jest.config.*` and `vitest.config.*`;
    - the files the runner config points to: the paths and patterns named by pytest's `testpaths` and `python_files`, jest's `testMatch`, `testRegex` and `roots`, and vitest's `include`; and the scripts called by the `package.json` `test` script and by the Makefile `test` recipe (such as `scripts/test.sh`);
    - `conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg` and `pyproject.toml` in every parent folder of the working folder up to the filesystem root, since pytest loads them from its rootdir, which can be higher;
    - any file the user marks on the form.
  - The scan skips `.git`, `node_modules` and virtual environments. **Runner plugins there aren't protected, and the card says so plainly:** a `pytest11` entry point, a `.pth` file or a patched package in `node_modules` is loaded by the runner itself. The completed card lists every file the goal wrote, including under those folders.
  - **A change is any edit, addition or deletion** of a protected file, or a new file in one of those places or matching one of those patterns. So an edited or deleted snapshot, a new `conftest.py` or a new test file stops the goal.
  - **The record.** At Start the host records each protected file's sha256, or the section's sha256 for the `pyproject.toml` sections and `package.json` keys, under Arslan's data folder, where the worker's file tools and the commands profile can't write. At most 2,000 files or 50 MB; beyond that, Start refuses the check and asks the user to narrow the set. No existing entry is ever re-recorded during a goal. The only additions are new files accepted in a declared output path (below), and only a user edit of the goal records a new set.
  - **Before each verdict** the host re-hashes the protected set and looks for new matching files. Only if nothing changed does it run the check in place, in the working folder, through `_run_tool` and its gates. **Right after the run** it hashes the set again. A change found before the run, or made during the run, means the goal doesn't continue: it stops at `acceptance_review_required`, names the files, and is never complete. The check imports the work, so the work can write while the check runs, and a background process can too. That's why a change during the run stops the goal as well. To change a check or its tests, the user edits the goal.
  - **Nothing is adopted, with one exception: declared output paths.** At the edit step, before Start, the user may declare folders the check itself writes to, either on the form or with `outputs: <path>` on the `check:` line (T19's `tests/revealed/`). Drafting can't declare one. In a declared output path, only new files that appear during a host run are accepted, and from then on they are protected like the rest. A new file named like runner config (`conftest.py`, `pytest.ini`, `*.config.*`) isn't accepted. A new file that appears there between runs (the worker's) isn't either. Any edit or deletion of a file already protected there stops the goal. The completed card lists every file the check's runs wrote.
  - **Residual, accepted and disclosed:** the check has to import the work, so code it imports beyond the protected tests, expected outputs and config is unprotected, as are the runner plugins above. T19's `ledger/` is both what the tests import and what the worker must change. A worker that makes that code detect the check and short-circuit isn't caught. It can't make that change stick in a protected file, though: a write during the run stops the goal. The completed card lists every file the goal and the check wrote, so the user can see what changed, and the bench's checkers run hidden suites (T19).
- **Checks Arslan can't verify.** Some checks have no receipt that could ever show them met, such as "looks nice" or "the user is happy". The host flags them, not the model:
  - **The rule.** A check is verifiable when it is file saved with a path, sources read, mentions with a file (file contains), or a `check:` command, or when it is a judgement check over a file the user named: in the objective, or in a check the user wrote or confirmed on the form. A path that drafting added doesn't make a judgement check verifiable, so drafting can't route around the flag by attaching a file to "looks nice". Any other check is flagged as one Arslan can't verify. The drafting request can't clear a flag.
  - **At the edit step, before Start.** Each flagged check is marked on the form. Start goal stays disabled until each one is rewritten into a verifiable check, removed, or marked "I'll confirm this myself". From text, `/goal start` with a flagged check doesn't start: the host line lists the flagged checks, and `/goal start confirm` marks them all as user-confirmed and starts.
  - **User-confirmed checks** are never judged by the model and never count as met by Arslan. They don't count toward progress or toward "blocked".
  - **When only user-confirmed checks are unmet,** the goal stops at once at `acceptance_review_required`, with no further round. The card says what Arslan met, with receipts, and asks the user to look over the rest. The goal is complete only when the user presses Accept result. Otherwise the user edits the goal or resumes it with a note.
  - **A goal of only user-confirmed checks** is refused at Start: there is nothing for rounds to work toward, so the host line suggests a plain job instead.
  - **So a goal never silently runs forever.** A check the judge can never meet with a receipt either can't start, or is the user's, or (if a flag is somehow missed) leaves the goal without progress, so it is blocked at round 3. The budget still ends every goal.
- **No progress. Stopping too early is the main risk,** so "no progress" counts only real progress, never activity.
  - In-turn: `ProgressPolicy` stays as it is. Its stop wraps up and delivers as today, and the goal ends blocked.
  - **Each check's measure.** Progress is read from each check's own condition, evaluated by the host at the verdict, never from the receipts' paths alone and never from the answer:
    - `check:`: the host's run in place, as (exit code, sha256 of its stdout and stderr together);
    - file contains: the set of its phrases found in the file;
    - file saved on a folder with a minimum: the number of qualifying files;
    - sources read: the set of distinct sources read; when the check names a target, only the sources that match it, so reading unrelated files doesn't grow the measure;
    - file saved on one file, and judgement: no partial measure; only becoming met counts.
  - **The seen set.** The host keeps every (check, measure) value this goal has produced, in `Progress.goal`. Resume doesn't clear it, so returning to an old value after a block or a budget stop is never new. `/goal edit` is a spec revision, and `prepare_resume` keeps only evidence, artifacts and `continuation_ref` across one, so an edit starts a fresh seen set along with the fresh audit: the checks themselves may have changed.
  - **A round makes progress when either holds:**
    1. a check that was unmet at the start of the round is met at its end, and it has never been met before in this goal (since its last edit); or
    2. a check that was unmet at the start of the round has a measure at the end of the round that isn't in the seen set (for the counts and sets above, it must also be larger than every earlier value).
  - **Not progress:** tool calls, text, tokens or time; a failed call; anything said in the answer, including a quote of the check; `answer-delivered`; a write, read or command that doesn't change an unmet check's measure, such as rewriting a file with new bytes, appending one byte to a file a check names, or the worker running the check's argv itself; a measure seen before; a check going from met to unmet, or back to met.
  - **The streak.** It is 0 at Start, Resume and Edit. After each round's verdict, a round with progress sets it to 0, and a round without progress adds 1. When it reaches 3, the goal is `blocked` (Codex's audit). So a goal that makes progress at least once in every 3 rounds is never blocked, and only the budget ends it. A goal with no progress in rounds 1, 2 and 3 is blocked right after round 3's verdict.
  - Because a `check:` measure includes its output, a check that keeps failing with a different first error (the next failing test) is progress, and the same failure again is not. A check whose output changes on every run (a clock in it) can look like progress each round. File rewrites can't, since a file's bytes are no check's measure. In that case the budget ends the goal as budget-limited, never complete.
  - **The blocked reply** says what is met, with receipts, and the blocker: the unmet check and its last receipt, such as the exit code and the first error line. It ends with exactly **one step for the user** (SMART's guidance rule), the one thing that would unblock it: a note with a missing fact, a file to add, a check to rewrite, or an approval. The last round's verdict request writes it. If it gives none, or more than one, the host uses a fixed line that names the unmet check and offers Edit and Note. Resume starts a fresh streak.
- **Budgets: wrap up and deliver.** A goal runs on the job's tier and dollar cap and never raises them itself (Q3). At the soft limit, today's finish mode saves and answers. The goal becomes budget-limited, never complete, and the message lists what was done, what isn't met, and Resume.
- **Resume re-queues the job.** It never uses `resume_turn` or the chat socket. Resume comes from `/goal resume` or the card. It runs `prepare_resume` on the goal row, so a changed goal is refused, grants are dropped, completed writes stay fenced in the journal, and `Progress` is carried. Then the same row runs again as a background job: `JobConfirmations`, `steer_key`, and a fresh budget of the same tier and cap. `resume_turn` refuses a goal row. This covers resuming after a block, a budget stop, a pause and a restart.
- **Interruption and steering.**
  - Stop works as for any job.
  - `/goal edit` raises the spec revision. `prepare_resume` already keeps only evidence, artifacts and `continuation_ref` across a revision, so the blocked audit restarts. A running goal reads the new objective at its next round.
  - `/goal note <text>`, or the card's note field, steers the running goal through K9b. The goal job's turn is steerable under its own key, `TurnRequest.steer_key = job id`, so chat messages never land in it. Calls that haven't started are skipped, the next request carries the note, and anything unread goes back.
- **Restart and app quit.**
  - Each round's verdict and counters (round, unmet ids, ids ever met, no-progress streak, the seen set of measures, the protected set's sha256 list, last receipt index) are written as `Progress.goal` in the same checkpoint as the verdict (`checkpoint("goal_round")`), before the continuation message goes out.
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
  - For "no tool schema change", the guard is a permanent tool-table test. Main doesn't have one yet. z3 planned it, and #841's second commit (`2ef08212`) adds it as `test_tool_offer_table.py`, but #841 isn't merged. Each case must offer the same tools with the same schemas, and it is also run once with the flag on and a goal set.
  - **The guard depends on that test pinning schemas too.** At `2ef08212` it pins tool names, order, the shown set and traits, but it compares schema text only between a flip and its base within one run, so a property added to a tool's schema leaves it green. That fix (a per-case schema digest) is being made in #841. The L7-1 gate below includes it.
  - **The gate stays explicit: L7-1 doesn't open until #841, with `test_tool_offer_table.py` pinning each case's schemas, is on main.** If that test leaves #841, L7-1 waits for whichever PR lands it.

## Bench plan
- **When.** The L7 code PRs (L7-1 to L7-6) are reviewed one by one from main and wait, approved and unmerged. ⓪Plan merges their heads into a build branch and benches it. Only if the bench passes do they merge, in order. A PR rebased after the bench must leave the build branch's L7 files unchanged, or the bench reruns. Flag-off code that changes the loop counts: the flag-off arm is benched too.
- **Arms, all on DeepSeek, Arslan only, with fresh instances:**
  - `base`: main before L7, k=3 on every task;
  - `off`: the build branch with the flag off, k=3 on the 13 other tasks and **k=6 on the goal tasks T18–T21**;
  - `on`: the build branch with the flag on and every prompt sent as a goal, with the same k as `off`.
- **Tasks:** T1, T2, T3, T5, T7–T11 (STY2's 9 tasks), T13–T15 and T17 (M64), T18, and the three multi-round tasks T19–T21. That's 17 tasks and 177 runs (`base` 51, `off` 63, `on` 63), plus a 9-run pilot in L7-0, on STY2's model (deepseek-v4-pro), off-peak.
- **L7-0 adds** T18, a goal task: 20 synthetic invoices, sort them and reconcile the totals. Its checker recomputes the totals. It also adds `BENCH_GOAL=1`: the driver turns the setting on in the fresh instance, sends `/goal ` before the prompt, so the criteria are Arslan's own, and then sends `/goal start confirm` without editing them (Q0), so a flagged drafted check becomes user-confirmed instead of keeping the run from starting. Runs that had a flagged check are counted and reported.
- **L7-0 also adds three tasks that need rounds of feedback the worker can't see up front.** The next piece of work doesn't exist, or isn't visible, until the check has run. Each has a fixture (`fixture_t19.py` to `fixture_t21.py`) and a checker (`check_t19.py` to `check_t21.py`) that recomputes the result from disk. The prompt carries a `check:` line, so the goal has a deterministic check in both arms (in `off` the line is plain text the worker may run itself). Each fits under the standard tier's 80 tool calls (`execution_budget.py:49`).
  - **How many rounds this forces, honestly.** None of them can be finished from what is visible at the start: at least one check run must reveal more. A worker that runs the check itself, again and again within one round, can still finish in one round. Goal mode's gain is that the host runs the check at each answer and sends back what it revealed, so an early answer doesn't end the work.
  - **The pilot (in L7-0):** `off` at k=3 on T19–T21 (9 runs, about $2.25). If `off` completes a task in 2 or more of 3 runs, the task is made harder (more stages) before the bench, so the completion bar measures goal mode and not a worker that already loops on its own.
  - **T19, staged test failures (code).**
    - Inputs: a small Python package `ledger/` with 5 modules and one planted bug in each, where the right behaviour is only stated in the tests (a rounding mode, a date convention, an ordering). At the start only the first module's tests are on disk. `tests/run_checks.py` runs the tests revealed so far. When they all pass, it writes the next module's tests (from its own encoded data file) into `tests/revealed/`, prints that new tests were added, and exits 1. After the fifth module passes, it exits 0.
    - Prompt: make `python3 tests/run_checks.py` exit 0 without editing `tests/run_checks.py` or its data file; `check: python3 tests/run_checks.py outputs: tests/revealed/`. The prompt declares the output path, so the check's revealed tests are accepted and every other change under `tests/` stops the goal.
    - Checks with receipts: the host's run of the check exits 0; the checker runs a hidden full suite of all 5 modules, and confirms by sha256 that `tests/run_checks.py` and its data file are unchanged.
    - Feedback not visible up front: the expected behaviour of module k is only in its tests, which appear after module k−1 passes. At least 4 check runs after the first are needed.
  - **T20, a list that arrives in batches (files).**
    - Inputs: 4 batches of 6 synthetic notes, each note with a unique code word and a date. Only batch 1 (`notes/n01.md` to `n06.md`) is on disk at the start. `inbox_check.py` checks the summaries for the notes present. When they pass, it drops the next batch (from its encoded data file `batches.dat`) into `notes/` and exits 1. After batch 4 passes, it exits 0.
    - Prompt: for every note in `notes/`, write `summaries/<same name>.md` with exactly two sentences that include its code word and date, and keep `summaries/index.md` listing every note; `check: python3 inbox_check.py --batches batches.dat`. The argv names both files, so both are protected.
    - Checks with receipts: the host's run of the check exits 0, and the checker recomputes from disk that 24 summaries and the index exist, each summary has exactly two sentences (split on `.`, `!` and `?`) with its note's code word and date, and the index lists all 24.
    - Feedback not visible up front: notes 7 to 24 don't exist until the check has passed on the batch before. At least 3 check runs after the first are needed.
  - **T21, rules revealed by the validator (data).**
    - Inputs: `data/orders.csv`, 300 synthetic rows with 4 planted kinds of fault (non-ISO dates, lower-case currency codes, duplicate order ids, amounts without two decimals), and `validate.py`. It reads the 4 rules from an encoded data file, `rules.dat`, and checks `clean/orders.csv` against the rules revealed so far. When those pass, it prints the next rule and exits 1. After the fourth, it exits 0.
    - Prompt: clean the file into `clean/orders.csv` so that the check exits 0, without editing `validate.py` or `rules.dat`; `check: python3 validate.py --rules rules.dat clean/orders.csv`. The argv names `validate.py` and `rules.dat`, so both are protected. `clean/orders.csv` is named too, but it is the work and doesn't exist at Start, so it isn't protected (the protected set's first rule).
    - Checks with receipts: the host's run exits 0, and the checker re-validates all 4 rules, confirms by sha256 that `validate.py` and its data file are unchanged, and checks the rows. For a duplicate order id, the first row in file order is the one kept; every other row must survive with its values normalized.
    - Feedback not visible up front: rules 2 to 4 are printed only after the rules before them pass. At least 3 check runs after the first are needed.
  - **Residual, disclosed:** T19's and T21's data files are encoded, not secret. A worker that decodes one could see ahead. Each checker reports whether any worker call read its data file.
  ```
  # one proxy per arm, restarted between arms, so each arm has its own cap
  scripts/kernel_bench/start_proxy.sh   # base: BENCH_CAP_USD=8; off: 11; on: 19; pilot: 3; BENCH_RUN_CAP_USD=2.5 for all
  T=T1,T2,T3,T5,T7,T8,T9,T10,T11,T13,T14,T15,T17
  G=T18,T19,T20,T21
  # L7-0's pilot, before the bench: off at k=3 on T19-T21
  BENCH_ROUND=r64-l7-pilot BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks T19,T20,T21 --entrants arslan --repeats 3
  # on main before L7, then twice on the build branch (the second time with BENCH_GOAL=1)
  BENCH_ROUND=r64-l7-base BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T,$G --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-off  BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-off  BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $G --entrants arslan --repeats 6
  BENCH_ROUND=r64-l7-on   BENCH_GOAL=1 BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $T --entrants arslan --repeats 3
  BENCH_ROUND=r64-l7-on   BENCH_GOAL=1 BENCH_FRESH_INSTANCE=1 BENCH_SANDBOX=none .venv/bin/python -m scripts.kernel_bench.runner --tasks $G --entrants arslan --repeats 6
  .venv/bin/python -m scripts.kernel_bench.report --offpeak --round r64-l7-base   # and -off, -on
  .venv/bin/python -m scripts.kernel_bench.done_without_evidence results.jsonl --round r64-l7-base   # and -off, -on
  ```
  The user cleans up T1's Reminders lists afterwards (`cleanup_t1 --delete --yes`). Results go to a persistent folder before the run, and the tables are committed to this card.
- **Written floors.** Each arm must also meet these on its own tasks:
  - STY2 (#658, rounds `sty2c-before-ds` and `sty2d-after-ds`): 20 of 27 passed, and done-without-evidence 4, on the same 9 tasks.
  - M64 (#453, `r64-m64-base`): T13 2/3, T14 3/3, T15 3/3, T17 3/3.
- **Cost: about $31 at DeepSeek peak prices, and up to about $54 with the one pooled rerun, on DeepSeek. Decided by the user on 2026-11-11 (option A), with the per-arm caps below kept.** That is about $10 over the $21 this card estimated before. The extra runs on the goal tasks, which the completion bar needs (below), and the pilot account for the difference. The arms come to about $5.6 for `base`, $8.2 for `off`, $14.5 for `on` and $2.3 for the pilot.
  - STY2's 27 runs cost $2.32-2.61 at peak (#658), about $0.10 a run, so its 9 tasks are about $2.6 per k=3. `r64-m64-base` cost about $1.71 for 48 runs (#453), so T13–T17's 12 runs are about $0.45. T18 is taken as about $0.10 a run, or $0.15 in `on`.
  - T19–T21 are new and unmeasured. They are taken as about $0.25 a run in `base`, `off` and the pilot, and $0.5 a run in `on` (several rounds). The pilot measures the `off` figure before the bench.
  - The `on` arm's 13 other tasks are assumed to cost up to 1.5 times as much.
  - The proxy's cap is one in-process total (`meter.py`), so it is restarted for each arm with its own `BENCH_CAP_USD`: 8 for `base`, 11 for `off`, 19 for `on` and 3 for the pilot, so $41 at most in all, and `BENCH_RUN_CAP_USD=2.5` per run. A 402 stops that arm's round, and it's reported.
  - The one full rerun the bar allows on a miss (below) would add about $23, for about $54 in all. Its arms are capped the same way (11 for `off`, 19 for `on`).
- **The completion bar (the user's priority: goals must actually get completed).** This is a gate in addition to "doesn't regress", and it compares `on` with `off` on the same build branch.
  - **Complete means checked, never claimed.** A run is complete when its task's checker (`check_tN.py`) passes. The checker recomputes the result from the files on disk and the trace's receipts (paths and sha256, exit codes). It never reads the reply's claim or the goal's own status. A run whose reply says "done" while its checker fails is incomplete.
  - **The bar, both of these:**
    1. **The gain, where goal mode acts:** on the goal tasks T18–T21 at k=6 (24 runs per arm), `on` completes at least `off` + 8 runs.
    2. **No loss elsewhere, with a tolerance:** on the 13 other tasks at k=3 (39 runs per arm), `on` completes at least `off` − 3 runs.
  - Together they mean `on` completes at least 5 more of its 63 runs than `off`, so goal-on always completes strictly more than goal-off when the bar passes.
  - **False-pass rate: at most 1.5%.** This is the chance that a goal mode with no real effect passes the bar.
    - How it was computed: exactly, not by sampling. Each goal task's runs in each arm are binomial with the same rate in `off` and `on` (no effect). The four per-task differences were convolved, and the chance of a total of +8 or more was read off. This was done for every combination of the four tasks' rates over 0.1, 0.3, 0.5, 0.7 and 0.9.
    - At one look, the worst case is **1.47%**, with every rate at 0.5. That is gate (1) alone, and gate (2) can only lower it.
    - With the one full pooled rerun allowed below, the whole bar (gate (1) and gate (2) at the assumed rates below) passes a no-effect goal mode at most **1.31%** of the time. Gate (1) alone with that rerun reaches 1.49%.
    - The review recomputed these figures independently, the same way, and they matched.
  - **Power, the whole bar, the same way:** if goal mode lifts each goal task from 0.3 to 0.8, the bar passes about **81%** of the time at one look (about 94% with the rerun). From 0.5 to 0.8, it passes about **41%** (about 52%). Gate (1) alone passes 93% and 47%. Gate (2) passes 87% when goal mode changes nothing on the other tasks. That figure assumes per-task rates matching STY2's 20/27 and M64's (#453), spread as 1, 1, 1, 0.9, 0.8, 0.67, 0.5, 0.4, 0.4 and 0.67, 0.95, 0.95, 0.95.
  - **Why not the per-task rules of the first draft.** At k=3, "no task goes from complete to incomplete" fails a real gain through noise alone: one task at a 0.5 rate loses 2 of its 3 runs about 11% of the time. And rerunning only the tasks behind a miss re-rolls the unlucky draws and keeps the lucky ones, which the review's simulation put at a false-pass rate of roughly 30–40%.
  - **No selective reruns.** On a miss, the only rerun allowed is one full rerun of all 17 tasks in both `off` and `on`, at the same k. The bar is then judged on the pooled runs with doubled thresholds: +16 of 48 on the goal tasks, and −6 of 78 elsewhere. A miss on the pooled runs blocks the merge, as a regression does.
  - **Reported, not gated:** the runs where the goal said complete but the checker failed (drafted checks too weak); the runs with a flagged drafted check; the pilot; and, per task, the round at which each `on` run was met, blocked or budget-limited.
- **"Doesn't regress" means all of these,** for `off` and for `on`, each against `base`. All arms compare at k=3 here, so on T18–T21 only the first 3 of the 6 runs in `off` and `on` count:
  - **Pass^3:** here, the number of tasks passing 3 of 3 in that arm (one entrant, the same 17 tasks) is not lower;
  - total passing runs are at least `base` minus 1, and no task loses 2 or more runs;
  - the done-without-evidence count is not higher (the two stricter counts are reported, not gated);
  - the written floors hold;
  - median cost and wall time per passing run are at most 1.5 times (`on` only; `off` must match within noise).
  - #453's rule applies: every T13–T15 verdict that changes the result is checked by hand.
  - A task that misses gets one more k=3 rerun, and a miss on the rerun blocks the merge. T18–T21 are expected to improve under `on`, and the completion bar gates that, with its own rerun rule.
- **SMART-5** runs once on `off`, single-turn chat with no goal, against its last passing round.
- **Flag.** The `goal_mode` setting (Settings → Advanced) is read in one place, `/goal` parsing in `handle_user_message`. With the flag off, `/goal` is plain text. Its default at the tag goes to the user after the bench (Q6). `DELETE-BY: v0.1.65` once the default is decided.

## Method and PRs
Red tests first:
- the goal is met in round 1;
- a check is unmet, then met;
- blocked after 3 rounds with no progress;
- a rewrite of an unrelated file isn't progress;
- **a long but steady goal isn't stopped:** a scripted goal with 12 rounds that makes progress every 2nd round (an unmet check's measure grows in rounds 2, 4, 6 and so on, nothing in between) is never blocked and is met at round 12;
- **a busy goal with no progress is stopped at round 3:** each round makes 5 tool calls (reads, a write to an unrelated file, the worker running the check's argv itself, the same failing `check:` output from the host) and a long answer. It is blocked right after round 3's verdict, not at round 2 and not at round 4;
- a `check:` that fails with new output (the next failing test) is progress; the same exit code and output again is not;
- appending one byte each round to a file an unmet check names, or rewriting it with new bytes that don't change its measure, isn't progress, and the goal is blocked at round 3;
- a check met, then unmet, then met again is not progress the second time;
- Resume after a block starts the streak at 0 and keeps the seen set, so returning to an old measure after Resume isn't progress;
- **the reply never counts:** a reply that claims every check is met, or quotes each check's text and phrases, meets nothing, is no progress, and the goal isn't complete;
- a mentions check with phrase P: P only in the reply is not met; P in the named file on disk is met; a mentions criterion with no file is flagged at the edit step;
- `answer-delivered` passing is not progress, and a goal whose other checks are unmet isn't met;
- the judge gets the named file's host-read content and never the answer text; a one-line write to a judgement check's path with a reply describing rich content is not met;
- a judgement check whose path was added by drafting is flagged until the user confirms the path on the form;
- **check files protected from Start** (each stops the goal at `acceptance_review_required`, never complete, and names the file):
  - an edited test file (a file under `tests/`, or a `test_*` file the argv doesn't name);
  - a new test file added after Start (a new `tests/test_extra.py`, or a new `conftest.py`);
  - an edited config (`pytest.ini`, the `[tool.pytest.ini_options]` section of `pyproject.toml`, or the `scripts` key of `package.json`);
  - an edited file the argv names (T19's `tests/run_checks.py`, or T21's `rules.dat`);
- **an untouched check still passes in place:** a flat layout with `test_app.py` beside `app.py`, where the worker fixes `app.py` after Start, makes the host's check exit 0 in the working folder, so the work itself is never protected and the code tested is current;
- a runner check with no file in its argv (`pytest -q`, `npm test`) still protects the conventional tests and config;
- **no laundering through the check's run:** work code that rewrites a protected test while the host's check runs (an import-time side effect) stops the goal at `acceptance_review_required`, even after the work file is cleaned; so does a write by a background process during the run;
- **declared output paths:** a new file the check's run writes under a declared output path (T19's `tests/revealed/`) is accepted and protected from then on; an existing protected file there that is modified (or deleted) during a run stops the goal; a new `conftest.py` there, or a new file the worker writes there between runs, stops the goal; drafting can't declare an output path;
- an edited or deleted snapshot (`__snapshots__/`, `*.snap`), or an edited `testdata/` or `fixtures/` file, stops the goal;
- a test file outside the default patterns that pytest's `testpaths` or jest's `testMatch` points to is protected, and so is `scripts/test.sh` called by the `test` script or the Makefile `test` recipe;
- a new `conftest.py` in a parent folder of the working folder stops the goal;
- a drafted criterion naming the check's script as a file to save doesn't unprotect it;
- an edit to `pyproject.toml` outside its test sections, or to `package.json` outside `scripts` and `jest`, doesn't stop the goal;
- the worker running a modified check with the same argv meets nothing;
- the blocked reply has exactly one step for the user, and the host's fixed line replaces a verdict that gives none or two;
- nothing runs before Start: setting a goal makes one drafting request with no tools, no job and no tool call, and `/goal start` or Start goal queues the job;
- the edit step flags "looks nice" and "the user is happy" as checks Arslan can't verify, and Start stays disabled until each is rewritten, removed or marked user-confirmed;
- `/goal start` with a flagged check doesn't start and lists it; `/goal start confirm` marks it user-confirmed and starts;
- when only user-confirmed checks are unmet, the goal stops at `acceptance_review_required` with no further round, and it is complete only after Accept result;
- a goal of only user-confirmed checks is refused at Start;
- a judgement check with no path, source or command that gets past the flag is never met without a receipt, and the goal is blocked at round 3;
- budget-limited: it wraps up, delivers, and is never complete;
- no goal round on a forced step;
- a "met" without its condition holding (a receipt that only names the path or argv, a failed call, content the host couldn't read) is not met;
- a page or a file that says "goal achieved" is not met;
- a note before the first call (K9b under `steer_key`), and a chat message that never reaches the goal;
- `ProgressPolicy` still stops;
- a `check:` command gets the same card as `run_command` (in `test_gate_order.py`);
- drafting never produces `check:`;
- `/goal` is plain text in a scheduled prompt, a resumed instruction (`resume_turn`) and a `start_background_work` goal string;
- `resume_turn` refuses a goal row;
- the boot pass leaves goal rows interrupted;
- the restart matrix.

Mutations, each turning a named test red:
- the blocked threshold set to 2, or to 4;
- tool calls or answer text counted as progress;
- the seen set cleared on Resume;
- the output digest dropped from a `check:` measure (the steady T19-style test goes red);
- a file's sha256 counted as a measure (the one-byte append test goes red);
- the answer text passed to the judge, or a `text` rule allowed in a goal's checks;
- `answer-delivered` counted as progress;
- the worker's `run_command` accepted as a `check:` receipt;
- the protected set's re-hash removed, or new files matching a protected pattern ignored;
- the conventional test and config patterns dropped from the default set (the runner-check test goes red);
- the check run from copies instead of in place (the untouched-check test goes red);
- the after-run hash removed, or the protected set re-recorded after a host run (the laundering test goes red);
- new files accepted outside a declared output path, or edits accepted inside one;
- the parent-folder `conftest.py` scan removed, or the runner-config paths ignored;
- a drafted criterion's file to save allowed to unprotect an argv file;
- a drafted path accepted as making a judgement check verifiable;
- the flag for checks Arslan can't verify removed;
- a user-confirmed check judged by the model;
- a goal job queued when the goal is set, before Start;
- a check met by a receipt that fits its path or argv without its condition;
- a goal round allowed on a forced step;
- a goal that raises its own budget;
- `check:` sent around `_run_tool`;
- the round counted from the transcript;
- `steer_key` falling back to the conversation;
- `/goal` parsed in `_handle_answer`;
- the boot pass cancelling goal rows.

| PR | What | Lines | Review |
|---|---|---|---|
| L7-0 | Bench: T18, the multi-round tasks T19–T21 (fixtures, staged checks and checkers), `BENCH_GOAL` with `/goal start confirm`, per-task repeats for the goal tasks, the completion bar in `report`, and the `off` pilot on T19–T21 | bench only | high |
| L7-m | Mock: the five UI items below. **Done: the user approved it on 2026-11-11** | docs | the user OKs |
| L7-1 | Types and red tests: `GoalSpec`, the `TurnRequest` and `TurnState` fields, `Progress.goal`, the setting, the `checked_driver` dict. Nothing reads them yet | ~150 | high |
| L7-2 | The goal round in `turn_answer.finish`: verdict by each check's own condition, `file_contains`, the judge over host-read content and never the answer (`background_jobs.py:109-110`, `task_validation.py:176-182`, `:239-253`, `:313-331`), the measures, the progress rule and the seen set, continuation, the blocked audit with its one user step, stopping at `acceptance_review_required` when only user-confirmed checks are left, the per-round checkpoint | ~400 | high |
| L7-3 | `/goal` in `handle_user_message`, criteria drafting, the flag for checks Arslan can't verify, the not-started state and Start, goal jobs with `steer_key`, status mapping | ~350 | high |
| L7-4 | Resume as a re-queued job, the boot pass skipping goal rows, `resume_turn` refusing them | ~200 | high |
| L7-5 | `check:` commands as host calls through `_run_tool`, run in place; the protected set (argv files, conventional test and config files, the user's marks) recorded at Start and verified before each verdict | ~250 | max (command policy) |
| L7-6 | Web: the goal card and the chip, after the mock, plus the `goal_state` key on `job_update`. **A Bridge frame change, so the user merges it** | ~350 | high |
| L7-7 | The three bench rounds, the report here, then the merges in order; the flag default goes to the user | docs | — |

## UI (a mock first, L7-m: approved)
- **The user approved the mock on 2026-11-11.** L7-6 builds from it. Its edit step (1C) is where Start goal and the flags for checks Arslan can't verify go. The mock's own wording on the phone ("passes it through unread") is superseded by the frame line below.
- **The mock covers five items:**
  1. the goal card: the existing `JobCard` with the round, spend against the cap, the blocker, and Pause, Resume, Edit, Note and Stop;
  2. the composer chip, with the objective and n of m;
  3. the step where the user edits the drafted criteria, with Start goal (nothing runs before it);
  4. "Keep going until met" on a job card;
  5. "interrupted at round n" with Resume, which re-queues the job.
- **Plus** a Settings toggle, which is small. The island keeps the job's title (`desktop_status.working`).
- **The frame.** The goal's state rides on the backend `job_update` frame under a new key, `goal_state`: status, round, met and total, spend and cap, and the blocker. The existing `goal` string stays the objective and the title. The Bridge reads `job_update`, so adding the key is a Bridge frame change, and the user merges L7-6. That is the cautious reading.
- **The Bridge drops `goal_state`; it doesn't pass it through.** It builds `job.event` from a fixed list of keys (`id`, `conversation_id`, `state`, `title` from `goal`, `current_step` from `step`, `completed`, `total`, `criteria`, and a few more) and drops every other key of the frame (`FrameMapper.swift:167-170`, `jobEvent` at `:322-344`). `ConversationLinks.swift:162-166` reads only `phase`, `run_id` and `job_id`. So no Swift change is needed in v0.1.64, and the effect is that the phone shows today's job card.
- **Phone.** The phone shows the job card it has today: title, the current step, n of m and the checklist. The round and blocker don't show there, because `_job_sink` overwrites `step` with each tool step. Start, pause, resume and note are `/goal` text sent through `chat.send`. Mapping `goal_state` into `job.event` is Q8.

## External evidence
- For each PR: the CI run id on all five checks, z3's tests green and unchanged, and the mutations.
- For the merge: the three bench rounds against `base` and the written floors, the completion bar (`on` against `off`), with run ids and spend.
- A real-Mac check with the user: a `/goal` on T18-style work, a quit mid-round, then Resume.

## Decisions (the user decided on 2026-11-11)
Every question went as this card recommended. Each is decided; the answer is the one written.
0. **Starting: decided.** Nothing runs until the user presses Start goal. Arslan drafts the checks, the user can edit them, and Start begins the work. From the phone or by voice, `/goal start` does the same.
1. **Where a goal runs: decided.** As a background job, so the user can talk while it works, not as the chat turn.
2. **Who sets one: decided.** Only the user, with `/goal` or the job card's button. The model never starts one itself.
3. **Budget: decided.** The job tier and dollar cap, plus an optional per-goal `$N` up to the Settings maximum. Never raised automatically.
4. **At the limit: decided.** Wrap up, deliver, and offer a one-tap Resume. No auto-extend.
5. **After a restart: decided.** Resume with one tap. No auto-resume, since a quit may have been a stop.
6. **Flag default at the tag: decided.** On, if the bench passes, including the completion bar. With no goal set, turns are unchanged.
7. **Judge model: decided.** The turn's own model, with no tools, not a cheaper fixed model.
8. **The phone's goal fields** (round, blocker, status in `job.event`): **decided.** In v0.1.65 with ①iOS. In v0.1.64 the phone shows the plain job card.
