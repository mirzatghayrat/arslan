# Kernel bench

Same tasks, same model, several agent kernels — Arslan against Hermes, OpenClaw, DeepSeek Harness
and goose. Built for the 2026-10 kernel comparison; see `docs/plans/2026-10-01-kernel-*.md`.

## What it measures

- **Pass^k**: each task is run k times; it passes only if every run passes (score 3). One success
  shows a task is possible; k in a row shows it is reliable.
- Cost (exact, from the metering proxy), model time (first to last model call), model calls, how each
  run ended. Claiming success without doing it, and touching anything outside the task folder, are
  scored as failures by the checkers.

## 0.1.62 round (M1a): what changed

- **An Arslan run passes only if it ended cleanly (`done`) and the checker gave 3** (`runner.judge`).
  A task left on "needs you", failed or cancelled, a background job that ended blocked, partial or
  out of budget, a timeout, or a driver that never reported are all failures, whatever the files
  say. The driver waits for a task turn's final `task_state` (it comes after the answer), and for
  the server's `succeeded` phase (it used to wait for a `completed` the server never sends).
  Rows record `judge: 2`; `report.py` marks rows from before this rule `(old rule)` and never
  mixes them with new ones.
- **Usage per run** counts only the run's own label from when it started, so a label reused in a
  later round or on another model does not add the earlier spend.
- **`BENCH_FRESH_INSTANCE=1`** starts a brand-new Arslan for every run (`start_arslan.sh fresh-<label>`,
  on the port in `ARSLAN_API`) and stops it once the run's after-turn calls have settled. Use it for
  baselines and before/after comparisons (U10): one instance carries what it learned into the next
  run (K1's after-runs, T11) and makes idle-time calls (E18). Nothing may already answer on the port.
- **Set `BENCH_ROUND` for every round** (and a separate one per model, or for a rerun). It goes
  into the run label (`arslan-T2-r1-k1after`). The meter's per-run cap counts a label over the
  proxy's whole life, so a reused label can be refused with 402 before it starts, and its run
  folder would overwrite the earlier round's.
- **Several turns.** A prompt in `prompts.json` may be a list: Arslan gets each turn in the same
  conversation once the previous one is over; Claude Code resumes its session. The run folder is
  copied to `<run>.turn<N>` between turns for the checker. Other entrants are recorded as
  unsupported for such tasks.
- **A decline with a sentence.** `DECLINES` in `runner.py` names a task's card rules the stand-in
  person declines and the note they add (the card's `note`); only Arslan can be answered that way.
- **One model per entrant** (`--models`), and **Claude Code** as an entrant (pinned in
  `install_entrants.sh`, version recorded per run). Claude models go through a second metering
  proxy (`start_proxy.sh anthropic`, :8901); `report.py` keeps each model on its own row.

## Safety

- Only the metering proxies hold the real keys (`ARSLAN_SPIKE_DEEPSEEK_KEY`, and
  `ARSLAN_SPIKE_ANTHROPIC_KEY` for the Claude proxy); entrants get a dummy key. Caps per run and in total, priced at DeepSeek peak rates; requests are refused at the cap.
- Outside entrants run in a macOS sandbox (`sandbox.sb.template`): writes only under `BENCH_ROOT`; no
  reads of `~/.ssh`, keychains, Arslan's data or the user's real Hermes/OpenClaw/Claude Code config.
  Claude Code also runs `--bare` (no hooks, no CLAUDE.md, no keychain) with no MCP servers.
  DeepSeek Harness sandboxes its own shell and cannot nest, so it runs without ours.
- Arslan runs as a separate test instance with a throwaway HOME and data dir. **For baselines and
  comparisons, start it with `BENCH_SANDBOX=none`** (U10, user's choice A, 2026-10-20). Like DeepSeek
  Harness, Arslan sandboxes its own commands and its artifact checks, and macOS cannot start a
  sandbox inside `sandbox-exec`: under ours, its commands ran with `sandbox: unavailable` and every
  saved file's check came back `not_run`, so tasks stopped at "needs you" for the bench's sake
  (`.swift` and `.md` alike, checked on v0.1.62 + D2). Still in place without the outer sandbox: `env -i`,
  the bench HOME, a fresh instance per run (`BENCH_FRESH_INSTANCE=1`), the dummy key, and Arslan's own
  command sandbox — kept closed by the driver: with `BENCH_SANDBOX=none` it always answers cards the
  sandboxed way, so a card that would run a command outside the sandbox, or re-run one after a stop,
  is declined (#235; before it, 8 such cards were approved in the first option-A rounds and ran as the
  user, on bench paths only). Not in place: Arslan's file-reading tools can reach the user's files by
  absolute path, and action cards (an AppleScript, a Shortcut, Hands) act outside every sandbox — the
  driver approves only T1's Reminders script and T12's synthetic Hands Fixture app. The bench prompts
  never ask for anything else.

## Run

```bash
scripts/kernel_bench/install_entrants.sh          # once; installs into $BENCH_ROOT only
scripts/kernel_bench/start_proxy.sh               # keep running (DeepSeek)
scripts/kernel_bench/start_proxy.sh anthropic     # keep running too, for Claude models
# start an Arslan test instance on :8762 with HOME/ARSLAN_DATA_DIR under $BENCH_ROOT
.venv/bin/python -m scripts.kernel_bench.runner --tasks T3,T5 --entrants arslan,hermes --repeats 3
.venv/bin/python -m scripts.kernel_bench.runner --tasks T5 --entrants arslan,claude-code --repeats 3 \
  --models arslan=claude-sonnet-5-5,claude-code=claude-sonnet-5-5
.venv/bin/python -m scripts.kernel_bench.report --offpeak
```

The test instance asks only for risky commands (`shell_confirm_policy=ask_risky`), as every round before
v0.1.63 did; the app's own default is now "ask before every command". `BENCH_SHELL_POLICY=ask_all` runs a round
on that default instead (the final M1 records one such DeepSeek run for reference).

## Tasks

| id | task | checker |
| --- | --- | --- |
| T3 | Apple's last three full fiscal years, revenue and net income, as a table with sources | `check_t3.py` (SEC 10-K values, ±0.3%) |
| T5 | Organise a synthetic Downloads folder by type, mark duplicates, delete nothing | `check_t5.py` (manifest-based; any loss or outside change = 0) |

T1 (Reminders), T2 (job list), T4 (watch a page behind a login) and T6 (phone message) are added
before the first full comparison round.

## T7–T11 (0.1.62 round, M1b): local, no web pages

| Task | Fixture | Checker (3 = pass) | Who can run it |
| --- | --- | --- | --- |
| T7 long command | `slow_job.py` computes a 220M-step SHA-256 chain (48–65 s on an M-series Mac) and never finishes before 60 s, then prints its end | `check_t7.py`: `answer.txt` holds it; the checker recomputes it from what the fixture returned (~65 s), so a shortened or edited run gives a wrong answer | all |
| T8 three turns | `notes.md`; the runner keeps `<run>.turn1`, `<run>.turn2` | `check_t8.py`: after turn 1, three `##` sections using the notes (3+ key numbers); after turn 2, section 2 at 10 chars to 60% of before, sections 1 and 3 unchanged; after turn 3, one more Markdown table and all three sections kept | Arslan, Claude Code |
| T9 precise edits | `project/` with six files | `check_t9.py`: three renames and one version bump byte for byte; nothing else changed; no new file | all |
| T10 long log | `service.log`, 5,000 generated lines | `check_t10.py`: the reply names the first cause's line (±2) and the cause | all |
| T11 declined, then another way | `workspace/` with five `.bak` files | `check_t11.py`: the stand-in declined at least one card (driver count) with "move them to trash"; every `.bak` ends up in `workspace/trash/`, nothing lost | Arslan |
| T12 Hands on a Mac app | the synthetic "Hands Fixture" app (`scripts/hands_fixture`, as `hands_smoke.py` uses); needs a running Hands with Accessibility and Screen Recording, `ARSLAN_HANDS_APP` passed to `start_arslan.sh`, and `BENCH_ARSLAN_DATA` set to the instance's data folder | `check_t12.py`: ≥3 looks at the fixture with a screenshot (the instance's Hands trace), the reply reads back "K1 check" and reports "saved:K1 check" | Arslan |

No answer is ever written into the agent's folder: what a checker needs (T7's seed and chain
length, T10's line) is returned by the fixture and kept by the runner. An Arslan run that does
not end cleanly fails whatever the checker scored (M1a).

## T13–T17 (v0.1.64, M64): code review, split / delegate / summarise

| Task | Fixture | Checker (3 = pass) | Who can run it |
| --- | --- | --- | --- |
| T13 / T14 / T15 code review (Python / TypeScript / Swift) | `fixture_t13.py` … `fixture_t15.py`: a small synthetic git repo in `repo/`, `main` plus one PR commit on `feature`; four planted bugs each, two of them in code the PR does not change (T13 P4 and T15 S4: the PR changes a contract and an untouched caller breaks) | `check_t13.py` … `check_t15.py` hold the bugs (file, line ranges, type, keywords) and `EXTRAS`, true flaws that were not planted (flagging them costs nothing); `review_kit.py` reads `review.md` (else the reply), gives each finding at most one bug (the nearest), matches type keywords in prose only (not in code), and scores caught / planted and false positives. The matching rule is in `review_kit`'s docstring; each finding's verdict is in the record. 3 = all caught, at most one false positive | all |
| T16 split, delegate, summarise | `regions/<north,south,west>/orders.csv`; the answers stay with the runner | `check_t16.py`: each `out/<region>.md` right (the top product read from the line that claims it), `summary.md` covers all three, and 2–4 sub-sessions opened (from the run's tool-call record, `tool_record.py`); the record also keeps cost and `rate_limited_429` | Claude Code; Arslan once the SUB card's tool lands |
| T17 one step, no hand-off | `prices.txt` | `check_t17.py`: 0 if a sub-session was opened or work delegated (`delegate_work` counts), or no tool-call record; else 3 if `answer.txt` holds the sum | Arslan, Claude Code |

`report.py` prints, under the per-task table, two totals per entrant and model: Pass^k over every
task with an unsupported task counted as not passed (the figure rounds before v0.1.64 used), and
the **same-task** Pass^k over only the tasks every entrant on that model supports (R64 gates on
this one). `--round NAME` keeps one round's runs. Recomputed from R63's raw results: DeepSeek
Arslan 6/9 and 5/7, Hermes 6/9 and 6/7 (one task short on the same tasks); Claude Arslan and
Claude Code 5/9 and 5/8 each.

## T1 / T2 / T4 / T6 (0.1.49)

| Task | Fixture | Checker | Human step | Arslan |
| --- | --- | --- | --- | --- |
| T1 Reminders | a per-run list `对比测试-<run>` named in the prompt | `check_t1.py` reads only that list (JXA, read-only); dates relative to the run day | macOS asks once per entrant to allow Reminders | runs |
| T2 jobs table | empty run folder | `check_t2.py`: columns, 10 rows, 10 distinct links, ≥5 pages opened by the checker with ≥80% matching; bot-blocked links cap at 2 + `needs_manual_review` | spot-check rows the checker could not open | runs |
| T4 / T4x login page | `site_t4.py` on 127.0.0.1, fake account per run; page changes at +60 s (T4) or sessions expired (T4x) | `check_t4.py` from the reply + the site's phase log; any agent-phase login attempt costs the top score (T4x: scores 0) | `--manual-login`: log in once in that entrant's own browser; the password is printed to the terminal only | **unsupported by design**: isolated browser profile, no loopback |
| T6 file to phone | seeded spreadsheet in the run folder; `fake_telegram.py` delivers the message | `check_t6.py`: byte-identical file in the test chat | none (no real bot, no token) | **unsupported**: no messaging channel |

Not yet verified (do before the first paid round, at no model cost where possible):
- T1's JXA reader against the real Reminders app (first use shows the macOS permission prompt).
- How each outside entrant's browser keeps a session for T4 (the runner pauses for the human, but each entrant's browser differs).
- The Hermes gateway launch for T6 (`base_url` pointed at the fake server): `runner.py` refuses T6 for Hermes until this is done.

Cleanup: `python -m scripts.kernel_bench.cleanup_t1` lists the bench's Reminders lists;
`--delete --yes` deletes them (the user runs that).

**Action cards (`propose_action`)** act outside every sandbox, on the user's real apps. The driver approves only a T1 AppleScript that drives Reminders and nothing else (Arslan's own `script_kind` says `("app", ["Reminders"])`) and T12's Hands app card for "Hands Fixture"; risky steps (e.g. Delete), every other app, Shortcuts and websites are declined and counted as `actions_declined`, apart from T11's `declined` (until 2026-10-19 it approved them all).
