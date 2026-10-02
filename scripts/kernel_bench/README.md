# Kernel bench

Same tasks, same model, several agent kernels — Arslan against Hermes, OpenClaw, DeepSeek Harness
and goose. Built for the 2026-10 kernel comparison; see `docs/plans/2026-10-01-kernel-*.md`.

## What it measures

- **Pass^k**: each task is run k times; it passes only if every run passes (score 3). One success
  shows a task is possible; k in a row shows it is reliable.
- Cost (exact, from the metering proxy), model time (first to last model call), model calls, how each
  run ended. Claiming success without doing it, and touching anything outside the task folder, are
  scored as failures by the checkers.

## Safety

- Only the metering proxy holds the real DeepSeek key (from `ARSLAN_SPIKE_DEEPSEEK_KEY`); entrants get
  a dummy key. Caps per run and in total, priced at DeepSeek peak rates; requests are refused at the cap.
- Outside entrants run in a macOS sandbox (`sandbox.sb.template`): writes only under `BENCH_ROOT`; no
  reads of `~/.ssh`, keychains, Arslan's data or the user's real Hermes/OpenClaw config.
  DeepSeek Harness sandboxes its own shell and cannot nest, so it runs without ours.
- Arslan runs as a separate test instance with a throwaway HOME and data dir.

## Run

```bash
scripts/kernel_bench/install_entrants.sh          # once; installs into $BENCH_ROOT only
scripts/kernel_bench/start_proxy.sh               # keep running
# start an Arslan test instance on :8762 with HOME/ARSLAN_DATA_DIR under $BENCH_ROOT
.venv/bin/python -m scripts.kernel_bench.runner --tasks T3,T5 --entrants arslan,hermes --repeats 3
.venv/bin/python -m scripts.kernel_bench.report --offpeak
```

## Tasks

| id | task | checker |
| --- | --- | --- |
| T3 | Apple's last three full fiscal years, revenue and net income, as a table with sources | `check_t3.py` (SEC 10-K values, ±0.3%) |
| T5 | Organise a synthetic Downloads folder by type, mark duplicates, delete nothing | `check_t5.py` (manifest-based; any loss or outside change = 0) |

T1 (Reminders), T2 (job list), T4 (watch a page behind a login) and T6 (phone message) are added
before the first full comparison round.

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
