# P3 acceptance against Hermes — partial (2026-10-03)

Build: main with P3 (`run_command` workspace sandbox, PR #99 = `157463fd`). Same model for both
(deepseek-v4-pro), same tasks, off-peak (Saturday 06:30 Beijing). Approved budget $5; proxy cap $4.50 at
peak prices.

**Stopped after 7 valid runs: the DeepSeek account ran out of credit** (upstream 402 from call 124; the
proxy cap was not reached). Spent $0.98 at peak prices ≈ **$0.49 actual** (off-peak).

## Results (first repeat of each task only — not a Pass^3 result)

| task | Arslan | Hermes |
| --- | --- | --- |
| T1 Reminders | 3 (108 s, $0.079) | 3 (135 s, $0.119) |
| T2 jobs table | **1** (393 s, $0.372): saved, but 6 of 10 rows; said so honestly | 3 (148 s, $0.183) |
| T3 Apple financials | 3 (102 s, $0.103) | 3 (27 s, $0.049) |
| T5 tidy Downloads | 3 (72 s, $0.077) | invalid (402 before its first call) |

Costs are at peak prices; the actual charge is half.

## Did the sandbox get in the way?

No, on this sample. Arslan's commands all ran inside the sandbox, and **no sandbox card appeared** (0 of 4
runs). Confirmation cards per run: 1, 1, 1, 0. Earlier rounds without the sandbox showed 0–7 per run, mostly 0–2.
So interruptions did not rise, though four runs is too few to call it. T5 (moving files inside the task folder) and
T1 (Reminders through Swift/EventKit) passed with the sandbox on. The T2 failure is the known research-yield
problem (six jobs found), not the sandbox.

## Bench changes in this round

- Driver `BENCH_CARDS=sandboxed`: with Arslan's own sandbox on, the stand-in approves deleting and installing
  inside it; it declines every card that would let a command out of the sandbox, outward actions, and Apple
  Events (they bypass the file sandbox, because Finder does the work) except for Reminders in T1.
- Runner `BENCH_ROUND`: T1's Reminders list name gets a round suffix, so a list left over from an earlier
  round is not read as this run's.

## Not yet verified

Pass^3 on every task. 17 runs remain: Arslan T1–T5 r2–r3, Hermes T5 r1 and T1–T5 r2–r3. They need the
DeepSeek account topped up. Resuming: start the proxy with `BENCH_CAP_USD` = 4.50 − 0.98 (the proxy does not
remember what was spent before a restart), then `python -m scripts.kernel_bench.rerun` for those cells, or the
runner for repeats 2–3.

Known limit, noted for the record: Apple Events (`osascript`, Shortcuts) act through other apps and are not
confined by the file sandbox; they still need their own card ("controls other apps").
