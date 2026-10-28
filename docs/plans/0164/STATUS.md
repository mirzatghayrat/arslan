# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-28, ~12:00 UTC.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #455 | S3 checkpoint tests no longer depend on the runner's free disk; CI temp on disk | `69ced22d` |
| #449 | CAP1a: remove the capability discovery centre and the found-for-later rail (after-the-fact security review of the `capability_flow.py` lines requested from ③Hands; it had no review recorded on GitHub) | `5ccc5e39` |
| #432 | Security model: hard rules + sandbox + classifier, five modes (user decided 2026-10-28) | `11f05434` |
| #434 | The v0.1.64 plan (user approved 2026-10-28) | `3759f57b` |
| #442 | README §8 points to the Projects decisions | `1a29b685` |
| #441 | D7/D8 reversal recorded; Codex queue: models, replies in English | `b1b54c98` |
| #438 | S64-0: four leaks in the "read outside content" mark, plus F1 | `3ee16b6c` |
| #436 | M64: code-review, split/delegate and inverse bench tasks; same-task Pass^3 | `43667421` |
| #440 | Memory plan in README §8; English-on-GitHub rule | `d7b96c30` |
| #439, #437, #435 | Codex queue, read-only Codex connection, #438 in the queue | `8df2d44e`, `ef356fb5`, `601baee0` |

## Ready for the user to merge

The user is merging in ④参谋's order: #451 → #448 → #445 → #446 → #444 → #454 → #428. Each has an OK from another session and green CI on its head (see each PR). Also ready: #453 (M64 hand-check fix), #447 (SBX card; its seven questions are for the user).

- #443 (S64-0b): ②Main's OK at `390aa048`, CI green. Waits for the user's Codex Astra run.
- #456 (F5b-2): ③Hands' review; ②Main's confirmation of its commit and CI pending.

## In progress

| Lane | Work |
|---|---|
| ②Main | INB1 (backend done; UI waits for the user's mock), INB2 backend (migration 0072), C7c-2 #450 (stacked on #448), C7c-3 onward (waits for the user's answers to C7c Q1/Q2/Q4), SBX after its card |
| ③Hands | PRJ0 (deletions; table drop 0076), CAP1b #457 review, #449 security review |
| ⑤CAP | CAP1b #457 (0074), CAP1c (0075, after #457), CAP2a (at max) |
| ⑥Helper | STY #452 (draft; gated on the read test and a bench "after" run), SIDE after SUB2 |
| ⓪Plan | M64 (baseline done, hand check #453), STY read test #454 (page with the user), mid-version M1 round, cards |

## Waiting on the user

- The STY read page (export the choices to ⓪Plan).
- Two classifier pass lines in #444: X% of the approvable scope (⓪Plan suggests ≥ 70%) and the failure fallback cap (≤ 5%).
- C7c questions 1, 2, 3 (DELETE-BY move for `/brain/proposals*`), 4.
- The SBX card's seven questions (#447), mainly network N-a vs N-b.
- Real-Mac checks: FS1 (#451) and the Hands smoke for F5b-2 (#456), both on `SMOKE.md` (#447).
- Making the `language` CI job a required check (branch protection, after #446).
- The side-chat mock (SIDE-0), when it comes.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
