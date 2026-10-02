# P3 acceptance against Hermes (2026-10-03)

Build: main with P3 (`run_command` workspace sandbox, PR #99 = `157463fd`) and Island I1. Same model for both
(deepseek-v4-pro), same tasks, off-peak (Saturday morning, Beijing). Approved $5; spent **$3.05 at peak prices ≈
$1.53 actual**. The run paused once when the DeepSeek account ran out of credit; after the top-up the remaining
17 runs were resumed with the cap lowered by what had been spent. Four failed calls that cost $0 were removed
from the usage log so the timings stay honest; the original log is kept next to it.

## Results (T1, T2, T3, T5 × 3 each; T4/T6 are not supported by Arslan yet)

| task | Arslan | Hermes |
| --- | --- | --- |
| T1 Reminders | **3/3** · $0.025 · 76 s · 5 calls | 2/3 · $0.058 · 142 s · 15 calls (r3: list not created, said so) |
| T2 jobs table | **1/3** · $0.167 · 313 s · 22 calls | **3/3** · $0.093 · 160 s · 19 calls |
| T3 Apple financials | 3/3 · $0.041 · 77 s | 3/3 · $0.026 · 36 s |
| T5 tidy Downloads | 3/3 · $0.053 · 113 s | 3/3 · $0.046 · 100 s |

Per-run means; cost at actual off-peak price.

Compared with the 2026-10-02 comparison:
- T1 went from Arslan 1/3 vs Hermes 3/3 to **Arslan 3/3 vs Hermes 2/3**, and Arslan is less than half the cost.
- T2 went from both 1/3 to Hermes 3/3 vs Arslan 1/3.
- T3 and T5 are unchanged: both 3/3.

## The sandbox

- **No sandbox card in 12 Arslan runs.** Every command ran inside the sandbox; T5 (moving files in the task
  folder) and T1 (Reminders through Swift/EventKit) passed with it on.
- Confirmation cards per run: 1, 1, 0 · 1, 2, 2 · 1, 2, 2 · 0, 0, 0. That is a mean of 1.0, against 0–7 (mostly
  0–2) in earlier rounds without the sandbox. Interruptions did not rise.

## What held T2 back

1. **Research yield**: r1 and r3 found 6 of 10 jobs; r3 did not say it fell short. This is the same failure as
   in earlier rounds.
2. **Script cards**: four cards asked about `python3 -c …` or heredoc scripts (`hermes:script execution via
   -e/-c flag` / `via heredoc`). The bench stand-in declined them, because its sandboxed policy approves only
   delete and install. In T2 r2 and r3 that ended the background job (`task_failed`); r2 still passed.
   - With P3, a script can write only inside the workspace, temp and caches, so this card no longer protects
     anything the sandbox does not already protect.
   - **Recommended follow-up**: when the sandbox is on, script execution via -c/-e/heredoc runs without a card,
     as Codex does inside its sandbox. Outward, deleting, installing and other-app rules still ask.
   - T2 should then be re-measured.

## Bench changes in this round

- Driver `BENCH_CARDS=sandboxed`: with Arslan's own sandbox on, the stand-in approves deleting and installing
  inside it. It declines every card that would let a command out of the sandbox, outward actions, and Apple
  Events (they bypass the file sandbox, because Finder does the work), except Reminders for T1.
- Runner `BENCH_ROUND`: T1's Reminders list name gets a round suffix, so a list left over from an earlier round
  is not read as this run's.

## Not yet verified

- T4 and T6 (Arslan has no logged-in browser pages or messaging channel yet).
- T2 with the script-card follow-up.
- Known limit, for the record: Apple Events (`osascript`, Shortcuts) act through other apps and are not
  confined by the file sandbox. They keep their own card ("controls other apps").
