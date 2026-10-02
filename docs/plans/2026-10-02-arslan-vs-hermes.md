# Arslan (0.1.49 branch) vs Hermes — formal comparison, 2026-10-02

Approved $3.6 ($3 + $0.6); spent **$3.25** (all attempts incl. voided ones, proxy log).
deepseek-v4-pro for both; Arslan = `claude/0149-kernel` (P1 + search fix), native protocol;
Hermes v0.21.5 with `--ignore-user-config`, isolated HOME. Both in the bench sandbox.
Per cell: last attempt counts; cost/time recomputed from proxy rows inside that attempt.

| task | Arslan Pass^3 | scores | mean $ | mean time | Hermes Pass^3 | scores | mean $ | mean time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1 Reminders | 1/3 | 1, 0, 3 | 0.113 | 211 s | **3/3** | 3, 3, 3 | 0.172 | 274 s |
| T2 jobs table | 1/3 | 0, 0, 3 | 0.103 | 181 s | 1/3 | 2, 3, 2 | 0.253 | 330 s |
| T3 Apple table | **3/3** | 3, 3, 3 | **0.053** | 80 s | 3/3 | 3, 3, 3 | 0.069 | 67 s |
| T5 organise | 3/3 | 3, 3, 3 | 0.094 | 155 s | 3/3 | 3, 3, 3 | **0.071** | 79 s |

T4 (logged-in page) and T6 (phone) not run this round: Arslan lacks both (T4 approved for design).

## What decided the cells (from traces)

- **T1**: both hit macOS `-10004` for AppleScript inside the sandbox. Hermes switched to Swift +
  EventKit every time. Arslan handed back (r1), retried AppleScript variants until it stalled (r2),
  found Swift + EventKit once (r3). Gap = finding an alternative route.
- **T2, Arslan**: r1 and r2 ended with **"Execution budget exhausted: tokens / tool_calls"** —
  the chat turn's hard budget aborted the turn with an empty reply after 11+ successful reads.
  A product bug (violates completion-first): it should wrap up and deliver. r3 passed.
- **T2, Hermes**: r1 table had 10 links whose pages mention neither company nor title (listing
  pages, not the jobs); r3 had one dead link; r2 passed but hit the $0.30 per-run cap.
- **T3**: both perfect; Arslan cheaper. **T5**: both perfect; Hermes cheaper and faster.

## Environment faults handled (voided and re-run, same conditions per task)

Mac slept on battery mid-run (12:16–14:03; keep-awake added); DeepSeek balance ran out twice
(402, topped up); the bench sandbox blocked Arslan's browser twice (Playwright `/tmp` staging —
fixed in product `3d053019`; short socket dirs under `/tmp/arslan-ab-*` — allowed for Arslan's T2
reruns only). Arslan T1/T3/T5 ran without a working browser in all rounds (not needed for them).

## Next

1. Fix the chat-turn budget abort (wrap up and deliver at the soft point; hard limit only stops
   runaways) — the cause of both Arslan T2 failures.
2. Alternative-route persistence (T1) and self-capability claims ("cannot write"), via P2
   status bar + tool descriptions.
3. Re-run T1 + T2 only to verify.

## T2 verification after the fixes (Arslan only, 2026-10-02)

Two rounds. Fixes in between: chat-turn completion first (`6653831a`), zsh here-document temp
files (`08509f69`); browser pre-installed, browser-enabled sandbox. Spent $0.35 + $0.39.

| round | before TMPPREFIX fix | after both fixes |
| --- | --- | --- |
| r1 | 0 — job saved nothing (`python3 - <<'PY'` blocked: zsh heredoc temp in /tmp) | **3** |
| r2 | 3 | 1 — file saved, only 6 jobs found, said so |
| r3 | (cap) | 0 — claimed "no filesystem write capability" (false), gave up after 3 searches |

No more empty-reply aborts (budget) and no more failed saves (heredoc): both fixes hold. What
remains on T2 is behaviour, not plumbing: research yield (finding 10 real job links) and the
false "I cannot write" belief — both P2 work, together with T1's alternative-route gap.
