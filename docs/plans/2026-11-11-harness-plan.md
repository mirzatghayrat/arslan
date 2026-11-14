# Harness plan: getting each model to its ceiling inside Arslan (proposal, for the user to decide)

- **Written by:** the cloud audit, 2026-11-11, at the user's request. Read-only research; no product code was changed.
- **Based on:** the code on main `0eef043a`; the bench records under `docs/plans/0162` and `docs/plans/0164`; published harness practice from Anthropic, OpenAI, DeepSeek, Manus, Factory and Cognition (sources in §11).
- **Status:** a proposal. Every phase, number and date below waits for the user. No card changes until then.
- **How reliable the facts are:** the code facts in §1 come from a subagent's read of main; six of them I rechecked myself (marked ✔). Bench numbers are copied from the written reports; the raw runs are not in the repo.
- **What this is not:** it consolidates practice that has good public evidence. It is not a survey of every open harness or of the research literature (§10).

## 0. One page

1. **Where Arslan is:** the base is solid (budgets, stop conditions, caching, retries). The layer that makes the model perform well was built from incident patches and has never been tuned by measurement. On a five-level scale it sits between levels 2 and 3 (§1).
2. **What "the ceiling" means:** on the same model, reliably ahead of Hermes and OpenClaw and not behind Claude Code; near full marks on Arslan's own tasks and then a harder set; one number on a public leaderboard (§2). A harness can't exceed the model, so every target is a same-model comparison.
3. **How:** build the measurement first (H0), then ten pieces of work in order of evidence (H1–H10). Each has a checkable acceptance line and a veto rule (§4, §5).
4. **Against v0.1.64:** none of these eleven items is in today's list of 64 PRs. Proposed: H0's first PR, H1 and H8a go into v0.1.64 (the 27-task gate has to be restored before the tag anyway); H2–H7 become v0.1.65's main line; H9 and H10 continue (§6).
5. **Size:** about 36 PRs. Most are off the security surface, so they don't draw on the effort=max plus Codex review budget (§6).
6. **Four things for the user to decide are in §9.**

## 1. Baseline

### 1.1 Position on five levels

| Level | Meaning | Arslan |
|---|---|---|
| 1 | The loop runs and tools work | Yes |
| 2 | It runs steadily: budgets, stop conditions, retries, caching | Yes |
| 3 | Tuned by measurement: each change measured alone, tuned per model | No |
| 4 | Checks itself: the program enforces a check before "done" | Background jobs only |
| 5 | Long tasks stay on course: context, plan and memory are designed | Parts exist, untuned |

### 1.2 Evidence in code

| # | Fact | Where | Effect |
|---|---|---|---|
| 1 | The system prompt is about 14,700 characters, one text for every model. Comments name the incident behind each rule. "Act now" appears three times, "don't invent" at least five | `server/orchestrator/answer_rules.py` (file is 21,404 bytes ✔) | Rules dilute each other; capitals written for DeepSeek also go to Claude |
| 2 | `web_search`'s description says "Do at most 1–2 broad searches… answer as soon as you can" ✔ | `server/registry/tool_defs/web.py:9` | Fights "finish the job" |
| 3 | Once a page has been read, every step injects "use at most six relevant comparison rows" ✔ | `server/orchestrator/tool_loop.py:1168-1176` | May be one reason "find 10 jobs" keeps returning 7 or 8 rows (inference; H1 tests it) |
| 4 | On non-Claude models the in-turn history is bounded at a fixed 64,000 characters (96,000 after a web read), whatever the model's window; over it, half is dropped with no summary ✔ | `tool_loop.py:35-36`, `:1179-1181` | A 128k DeepSeek uses about a tenth of its window; one long page can evict everything before it |
| 5 | Tool results are not kept between turns; the next turn sees one line per call | `server/orchestrator/turn_tools.py:26-27,120` | A follow-up about a page read last turn means re-reading or guessing |
| 6 | A chat turn's only acceptance is "an answer was delivered" ✔ | `server/services/task_service.py:985-1039` (`_answer_only`) | Nothing checks "done" |
| 7 | Answer guards check only "drew a chart" and "searched" claims, by Chinese and English regex; file and command claims are unchecked | `server/orchestrator/answer_guards.py:155-164` | A false "done" gets through |
| 8 | Tool work runs at the default temperature 0.7; Claude's effort is never set; OpenAI-compatible and Gemini default to 8,192 output tokens ✔ | `arslan/llm/providers/*.py`; `anthropic_provider.py:56` | Noisier results; long outputs are cut |
| 9 | `search_files` matches literal content only, with no path, file-name or regex; `edit_file`'s errors name a parameter (`old`) that its description calls `old_string` | `tool_defs/files.py:50,83`; `file_tools.py:360-363` | The model falls back to `grep` and `find`, costing steps |
| 10 | Most tool failures return the raw exception; there are three generic recovery hints | `tool_execute.py:148`; `recovery_hints.py:14-26` | No next step after a failure |
| 11 | The plan (`update_plan`) lives for one turn, with no reminder | `server/orchestrator/turn_plan.py:7` | Long tasks drift |
| 12 | The prompt tells the model to call `my_status` and `attach_file`, which aren't resident tools | `answer_rules.py:303,323`; `arslan.py:1034` | Two extra steps each time |
| 13 | Lessons have no measured effect | `server/services/lessons.py` | Could be harmful and nobody would know |

### 1.3 Evidence in the bench records

37 recorded losses with a stated reason: stopped to wait for the user 8, incomplete result 6, missed an instruction detail 6, facts or sources 5, tool or environment 4, the bench itself 4, a regression from Arslan's own change 2, other 3 (`docs/plans/0162/R63-gate-report.md`, `U10-rerun-results.md`, `M1B-baseline-results.md`, `docs/plans/0164/STATUS.md`).

The three that matter most:
- **The tasks lost to Hermes have a fixed cause, unfixed for two rounds.** T3: all six figures right, but the file names no source (`R63-gate-report.md:55`, `U10-rerun-results.md:41`). T2 has not reached 3/3 in any round since early October: too few rows, or links that can't be matched. The report itself says the gap is in Arslan, not in search.
- **Arslan's own changes are a main source of losses.** S2a-2 took T11 on Claude from 3/3 to 0/3; STY2's closing note lost the length measure to OpenClaw for two rounds; the STY2 gate rerun went from 20/27 to 16/27 and from 0 waits to 3.
- **Today's measurement can't tell signal from noise.** Nine tasks × three runs; a difference of two or three is within noise (`R63-gate-report.md` says so).

A same-model, same-question comparison from 2026-11-12 (a tracking-link redirect diagnosis, Opus 5.5) shows the same pattern: Claude Code ran four rounds, formed a hypothesis and tested it, and returned a verified fix; Arslan stopped after one step and returned a list of possible causes, two of them marked as unverified guesses, and asked the user to run the tests. The run trace has not been read, so the cause is not established. It belongs in the capability set (§4.1).

## 2. Targets: how "the ceiling" is measured

| Id | Target | Today | Target value |
|---|---|---|---|
| G1 | Regression set (today's 9 tasks, 5 runs each) on DeepSeek | 22/27 (3 runs each) | ≥ 43/45; 0 waits; "done without evidence" ≤ 1 |
| G2 | Same task, same model, against Hermes (tasks passed 3 of 3) | 1 task behind | At least 1 ahead |
| G3 | Same task, same model, against OpenClaw (task success) | Not measured | Not below it; SMART-5's four measures still not behind |
| G4 | Same Claude model against Claude Code | 17/24 vs 17/24 | Not below it |
| G5 | Capability set (30 new, harder tasks) | None | Baseline first; then 20 points above baseline |
| G6 | Efficiency: median tool steps per task; Claude cache hits | Not recorded; 81% (Claude Code 97%) | Steps down 20% at no higher cost; hits ≥ 90% |
| G7 | A public leaderboard (Terminal-Bench, run privately) | None | Get one number; no target set in advance |
| G8 | Ten everyday jobs the user names | None | 9 of 10 done first time, with no correction |

G1–G4 are hard gates. G5–G8 start with a baseline. These are targets, not predictions.

## 3. Principles

1. **Measure, then change.** Nothing after H0 merges without H0's measurement.
2. **One change at a time.** One PR, one switch, its effect and its cost measured alone.
3. **What the program can enforce, the prompt doesn't plead for.** If a sentence only works in capitals, it belongs in a check in code.
4. **Every mechanism has a delete condition.** A guard, a prompt line or a feature with no measured effect goes. Re-test when models improve.
5. **Tune per model.** One profile each for DeepSeek, Claude and Gemini, and a default for the rest.
6. **No security boundary moves.** Nothing here loosens a card, the sandbox or the outside-content mark. The reviewer and the done-check never answer a card.

## 4. Verification (H0, the precondition for everything else)

### 4.1 Four task sets

| Set | Contents | Purpose | Size |
|---|---|---|---|
| Regression | Today's T1–T17 that pass reliably | Hold the line; pass rate near 100% | About 12 tasks × 5 runs |
| Capability | New tasks written from real failures (several per class in §1.3), plus the user's ten everyday jobs | Show improvement; pass rate deliberately low | 30 tasks × 3 runs (development) or 5 (gate) |
| Held-out | 10 capability tasks set aside and not looked at while tuning | Guard against learning the test | 10 tasks × 5 runs |
| Behaviour | Things it should not do: a one-line question gets no essay, a one-step request opens no sub-session (today's SMART-5 and T17) | Guard against over-effort | About 15 tasks × 3 runs |

Each release adds five new capability tasks and moves the ones that pass reliably into the regression set.

### 4.2 What each run records

Pass or fail; end state (done, waiting, budget used up); tool steps; model requests; input and output tokens; cache hits; dollars; time; cards shown; "done without evidence" (today's `done_without_evidence.py`); and, on a failure, one of the nine classes in §1.3 with one sentence of cause. Results go into one table in the bench root, keyed by commit and switch name.

### 4.3 How a change is judged

- Every change has a switch (`BENCH_ARSLAN_SETTINGS` already sets settings on the test instance, #310). Same day, same model: run with the switch off, then on.
- **Veto:** any regression task falls from 5/5 to 3/5 or lower; or the regression total falls by more than 2 runs; or the behaviour set falls by more than 2; or cost per task rises more than 25% with no gain in passes.
- **Counts as working:** capability passes rise by 3 or more (out of 90), and the held-out set doesn't fall.
- **No effect:** not merged. The exception is a pure removal (a prompt line, a guard): it merges if nothing regresses.
- The PR body gives passes, steps, cost and failure classes for off and on.

### 4.4 Cadence and cost

- Per H PR: regression plus behaviour sets on DeepSeek, about 75 runs.
- Weekly: all four sets, once on DeepSeek and once on Claude.
- Per release: Hermes, OpenClaw and Claude Code on the same tasks.
- **Cost estimate:** in the R63 round Arslan's 27 runs cost $2.18 on DeepSeek and $4.86 on Claude. At that rate a PR-level check is about $6 (DeepSeek), and a full pass about $20 (DeepSeek) plus $45 (Claude). These are estimates.
- **Reading runs:** each week, read ten failed runs end to end and correct their class where it's wrong. A new kind of failure becomes a new capability task.

### 4.5 H0's deliverables and acceptance

- PR 1: repeated runs and off/on comparison; the results table; the failure-class field.
- PR 2: the 30 capability tasks and the held-out set, with checkers. Each checker is first validated against a hand-written reference answer (M64 already met a checker that counted one finding as two, `M64-bench.md:64`).
- PR 3: the behaviour set folded in; the weekly report script.
- **Acceptance:** the same commit run twice through all four sets differs by no more than 3 passes; the four baselines are written down.

## 5. Ten pieces of work

Each gives the goal, the steps, the acceptance line, the size and what it depends on. Sizes are estimates.

### H1 Quick fixes: settings and plain contradictions (about 4 PRs)

- **Goal:** remove limits Arslan sets on itself.
- **Steps:**
  1. Temperature for tool work: set per vendor guidance for DeepSeek, OpenAI-compatible and Gemini instead of 0.7 everywhere (DeepSeek ignores it in thinking mode; Gemini advises defaults). Measure 0.7 against the new value.
  2. Claude: set effort per model, starting at high and then measuring medium; raise the output limit from 8,192 to a sensible value the model allows. The same for the OpenAI-compatible and Gemini 8,192. Check parameter names against each vendor's current docs when building.
  3. Remove "at most 1–2 searches… answer as soon as you can" from `web_search`'s description and the injected "at most six rows", each behind its own switch. Measure whether T2 returns to 10 rows.
  4. Fix the parameter name in `edit_file`'s errors; make `my_status` and `attach_file` resident or take them out of the prompt; add the local time zone to the environment snapshot.
  5. Take ordinary words such as "generating" and "in progress" out of `promise_guard`'s triggers; measure false corrections.
- **Acceptance:** no regression; T2 on DeepSeek ≥ 2/3 with no 7- or 8-row result; the 27 tasks back to ≥ 22/27 with 0 waits.
- **Depends on:** H0 PR 1.

### H2 Context inside a turn and between turns (about 4 PRs)

- **Goal:** keep what should be kept, without breaking the cache.
- **Steps:**
  1. Bound the in-turn history by the model's window (for example 50% of it), not a fixed 64,000 characters.
  2. Over the bound, clear old tool results first: replace the body with one line saying where the saved copy is (long outputs are already saved, `tool_outputs.py`); keep the most recent results whole; keep each call with its result. If that isn't enough, summarise, keeping paths, links and numbers verbatim.
  3. Tell the model that context is tidied automatically, so it doesn't wind down early.
  4. Between turns: for files and pages read last turn, keep the path or link and one line about the content; the outside-content mark stays on them.
  5. Record cache hits per request; clear in whole chunks so the cache isn't invalidated every step.
- **Acceptance:** long capability tasks (five or more sources, twenty or more steps) pass more often; follow-up tasks are answered without re-reading; Claude cache hits ≥ 90%, and DeepSeek's `prompt_cache_hit_tokens` share doesn't fall.
- **Depends on:** H0. Step 4 touches the outside-content mark and takes a security review.

### H3 An enforced check before "done" (about 5 PRs; the strongest evidence)

- **Goal:** "done" needs evidence, checked by the program.
- **Steps:**
  1. **A ledger of the turn's evidence:** the program records what actually happened: files written, commands and their exit codes, links opened. Checkpoints already hold the file differences.
  2. **Checkable conditions from the user's words:** a count ("10"), sources wanted, a file wanted, a table wanted, "shorter". The model lists them at the start and they go in the status block. Only on turns that do work; a one-line question gets none (the behaviour set guards this).
  3. **Deterministic checkers:** the file exists; the table has N rows; the file names its sources; each link was opened this turn; a file said to be edited appears in the differences; a command said to have run succeeded.
  4. **Enforced at the end:** when the model is about to finish, run the checks. A failed one is sent back for repair, at most twice; if it still fails, the answer says plainly which condition wasn't met. Background jobs' `AcceptanceCheck` is the same mechanism, extended to working chat turns.
  5. Fold the two existing regex guards in; `done_without_evidence` becomes the same judgement in the product.
- **Acceptance:** T3 on DeepSeek 3/3 (sources); T2 ≥ 2/3 with every link one that was opened; "done without evidence" ≤ 1 in 27 (4 today); no behaviour regression; cost per task up by no more than 15%.
- **Depends on:** H0 and H2's saved evidence. Checkers are read-only and loosen nothing.

### H4 The prompt, rebuilt (about 4 PRs)

- **Goal:** principles instead of incident patches, with a profile per model.
- **Steps:**
  1. Tag every line of today's prompt: a principle, how to use one tool, or a patch for one incident.
  2. Move tool usage into the tool's own description; merge the patches into principles.
  3. Write the core prompt to about 5,000 characters: identity and tone; how to work (look first, verify after, find another way round an obstacle); when to ask the user; how to answer. Each rule carries its reason.
  4. Add three to five varied good examples, not a list of edge cases.
  5. Profiles: Claude's drops the capitals; DeepSeek's keeps the lines measured to help (such as actually emitting the tool call) and strengthens planning; Gemini's follows its template, with constraints in the system instruction and the question last.
  6. Remove old lines in batches, each measured. What can go without a regression stays gone.
- **Acceptance:** the prompt is at most half its size; no regression in the regression or behaviour sets; SMART-5 length not behind OpenClaw; fewer unnecessary tool calls on Claude (median steps down).
- **Depends on:** H0. It edits the same file as STY2 and SMART-3/4, so it follows them. H1 step 3 comes first.

### H5 The tool surface (about 5 PRs)

- **Goal:** few clear tools that are hard to misuse and say what to do after a failure.
- **Steps:**
  1. `search_files` gains a path, file-name matching and regex, within today's readable roots.
  2. `edit_file` gains replace-all and returns the nearest lines when nothing matches.
  3. **An error contract:** every failure returns what happened, the likely cause and a next step. Start with the twenty most frequent failures in the records.
  4. Merge overlapping tools: `task_progress` / `background_status` / `progress_report`; `remember` / `memory_note`; `list_my_capabilities` / `my_status` / `whats_new`.
  5. On-demand lookup gains synonyms; beyond the three to five most used, make the tools the bench looks up most often resident; a clearer no-match message; the per-conversation set survives a restart.
  6. One rule for head-and-tail truncation, with the description saying where the full text is.
- **Acceptance:** median steps on file tasks down 20%; "tool not available" and "bad arguments" failures halved; the tool table still under 12,000 characters.
- **Depends on:** H0. It is the same work as K6, so one card. Step 1 touches the readable range and takes a security review.

### H6 Planning and long tasks (about 3 PRs)

- **Goal:** a task of dozens of steps stays on course.
- **Steps:**
  1. The plan persists across turns in a conversation; a new turn opens with its unfinished items.
  2. After several steps without a plan update, one reminder in the status block.
  3. Background jobs and sub-sessions write a progress note (done, next, known problems) and read it first after a context reset.
  4. Agree what "done" means before starting: the existing acceptance criteria for background jobs, and the way into goal mode (L7).
- **Acceptance:** capability tasks of thirty or more steps pass more often; an interrupted task continues without starting over.
- **Depends on:** H0 and H2. Align with L7 and S5 before starting.

### H7 An independent review, and research quality (about 3 PRs)

- **Goal:** a second look by something that didn't watch the work.
- **Steps:**
  1. The reviewer is one fresh-context model call that sees the user's request, the final output and the turn's evidence ledger, not the main model's reasoning.
  2. It runs only when the output is weighty: a report or several files written, or a research answer. A one-line question never triggers it.
  3. Research gets a source pass: each conclusion maps to a source opened this turn; what doesn't is flagged or removed.
  4. The reviewer can only say which conditions weren't met and send the work back once. It can't approve an action or answer a card.
- **Acceptance:** "the links don't match the table" in T2 goes to zero; false positives on T13–T15 don't rise; cost per task up by no more than 20%, or it runs for research only.
- **Depends on:** H3. The reviewer's model honours the local-only setting and the BYOK boundary (the same constraint as the classifier's).

### H8 Recovery and unknown outcomes (about 3 PRs; H8a goes into v0.1.64)

- **Goal:** bring the largest loss class, stopping to wait, to zero.
- **Steps:**
  1. **H8a:** when an action's outcome is unknown (typically an AppleScript timeout), look at the real state by a read-only route first (was the reminder created?). Continue if that settles it; stop only if it doesn't. The pending `known_local_failure` fix lives here.
  2. When the user declines a card, the result names a workable next step (a route that doesn't need that card, or a plain statement that it can't be done).
  3. Grow the recovery hints from three to the twenty most frequent failures in H0's records.
  4. Failed calls stay in context.
- **Acceptance:** 0 waits in the regression set for three weeks running; T1 ≥ 2/3 on both models.
- **Depends on:** H0. H8a only reads state and adds no permission.

### H9 The learning loop (about 2 PRs, continuing)

- **Steps:** measure lessons on against off, and turn them off by default if there's no gain; bench failures produce candidate rules that take effect only after a person reads them; repeated tasks of one kind prompt the user to save a skill.
- **Acceptance:** a number shows they help, or they are off.

### H10 Trimming (continuing)

- **Steps:** each release, switch every guard and every injected note off in turn and measure; what can go without a regression is deleted. Repeat with each new model generation.
- **Acceptance:** the count of guards and injected notes only falls, unless a new one arrives with a positive H0 result.

## 6. Schedule and size

| Where | Items | PRs (estimate) | Note |
|---|---|---|---|
| v0.1.64, before the tag | H0 (PR 1), H1, H8a | About 6 | The 27 tasks have to be back at 22/27 with 0 waits before the tag anyway |
| v0.1.65 main line | H0 (the rest), H2, H3, H4, H5, H6, H7, the rest of H8 | About 26 | In place of more features |
| Continuing | H9, H10 | About 4 | Once per release |

- **Order:** H0 → H1 → H8a → (H2 and H5 in parallel) → H3 → H4 → H6 → H7. H4 follows H3 because H3's checks replace many prompt lines, which can then simply go.
- **Review:** only H2 step 4 (the outside-content mark), H5 step 1 (the readable range) and H7 (the reviewer's limits) are on the security surface. The rest take an ordinary review.
- **Against existing cards:** K6 folds into H5; L7 and S5 align with H6; STY2's closing note folds into H3; `known_local_failure` is H8a. The classifier (CLS) and H7's reviewer are different things: one decides permission, the other judges quality; they share the local-only and BYOK constraints.
- **In v0.1.64:** H1 follows ASK1-a, since both change command behaviour and the bench couldn't tell them apart. The 27-task round run for ASK1-a serves as H1's "before" baseline.

## 7. What each stage should show

| After | Expect |
|---|---|
| H0 | Baselines for the four sets; two runs of one commit within 3 passes |
| H1 + H8a | 27 tasks ≥ 22/27, 0 waits; T2 no longer returns 7 or 8 rows |
| H2 | Long and follow-up tasks up; Claude cache hits ≥ 90% |
| H3 | T3 3/3; "done without evidence" ≤ 1; G2 (one task ahead of Hermes) should be reached here |
| H4 + H5 | Median steps down 20%; the prompt halved; SMART-5 not behind |
| H6 + H7 | The capability set 20 points above baseline (G5); G1, G3, G4 |
| Later | A number for G7; the user's ten jobs for G8 |

If a stage doesn't show its number, stop and read the failed runs before going on.

## 8. Risks

| Risk | Answer |
|---|---|
| A change causes another regression | H0's veto rules; one change at a time; a switch that can be turned off |
| It learns the test | The held-out set; new tasks each release; the user's ten jobs |
| Checks and reviews make it slower and dearer | They run only on working turns; send-backs are capped; cost limits are in each acceptance line |
| The prompt rebuild breaks the cache or existing behaviour | Batches, each measured; cache hits measured |
| Weaker models need more support | Per-model profiles; DeepSeek's keeps the lines measured to help |
| Scope grows again | This line is capped at 36 PRs; new ideas go to the next release |
| Bench cost | §4.4's estimate, about $65 a week; the user sets the limit |

## 9. For the user to decide

1. **Is this the main line of v0.1.65, in place of more features?**
2. **Do H0 (PR 1), H1 and H8a go into v0.1.64?** About 6 more PRs, for a release whose 27 tasks don't regress and whose waits are 0.
3. **The bench spending limit:** suggested $30 a week on DeepSeek and $45 on Claude.
4. **Your ten everyday jobs:** ten specific things you most often want Arslan to do. They join the capability set and are G8.

## 10. What this plan doesn't cover

- The number of confirmation cards (ASK1 and CLS on the security line). That is the user's most direct complaint; it runs alongside this line and neither replaces the other.
- The interface, the iPhone app, plugin hooks, new sub-session features.
- Changing or training models.
- **Depth of research.** One subagent read about twenty primary sources. Not done: reading the source of open harnesses (Codex CLI, opencode, OpenHands, Goose, Cline, Aider, Hermes, OpenClaw); what the top leaderboard entries do; the research literature; and automatic optimisation of prompts and tool descriptions against an eval. H0–H5 rest on the strongest evidence and are unlikely to change; H6–H10 and a possible "automatic optimisation" layer are what a deeper round would revise.

## 11. Sources

- Anthropic: [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents); [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents); [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents); [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps); [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents); [Claude Code best practices](https://code.claude.com/docs/en/best-practices); [Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices); [Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing).
- OpenAI: [GPT-5 prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide); [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide).
- DeepSeek: [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode); [Tool calls](https://api-docs.deepseek.com/guides/tool_calls); [Context caching](https://api-docs.deepseek.com/guides/kv_cache).
- Others: [Manus: Context engineering lessons](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus); [Factory: Terminal-Bench](https://factory.com/news/terminal-bench); [Cognition: Don't build multi-agents](https://cognition.com/blog/dont-build-multi-agents); [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent); [OpenClaw compaction](https://docs.openclaw.ai/concepts/compaction); [Hermes Agent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory).
- A subagent fetched and relayed these pages; check the original wording before quoting. OpenAI's post on the Codex loop and the Terminal-Bench leaderboard page could not be read at the time.
