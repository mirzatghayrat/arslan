# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-28, ~15:30 UTC.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #460 | INB1: learned practices take effect directly; what is not in effect says why (reviewed by another Claude session at effort=max; merged without Astra, see the Codex rule below) | `55168fad` (main CI 40710426557 queued) |
| #444 | Classifier pass lines (option 2 + the cloud audit's six changes); the audit's answer on outside content | `75e40e6f` (its main CI 40710072868 was cancelled when #460 merged; 40710426557 covers both) |
| #446 | LANG1: CI check for Chinese added outside the exceptions; bundled skills in English | `96bdf096` (main CI 40707221804 success) |
| #445 | C5b: delete `__version__`, the unused click/rich deps, and edit_file's old argument names | `d6cef2b0` (main CI 40705243770 success) |
| #448 | C7c-1: remove the dead `RouterDecision` model; C7c's plan as its card | `3f71d029` (main CI 40684400151 success, covering #451 too) |
| #451 | FS1: closing from full screen no longer leaves a black screen (real-Mac check on `SMOKE.md` still open) | `c2bfe497` |
| #455 | S3 checkpoint tests no longer depend on the runner's free disk; CI temp on disk | `69ced22d` (main CI 40680764208 success; it covers #449 too, whose own run 40680379988 was cancelled when #455 merged) |
| #449 | CAP1a: remove the capability discovery centre and the found-for-later rail (⑥Helper reviewed it, OK with optional cleanups, but could not post; an after-the-fact security review of the `capability_flow.py` lines is requested from ③Hands and goes on the PR) | `5ccc5e39` |
| #432 | Security model: hard rules + sandbox + classifier, five modes (user decided 2026-10-28) | `11f05434` |
| #434 | The v0.1.64 plan (user approved 2026-10-28) | `3759f57b` |
| #442 | README §8 points to the Projects decisions | `1a29b685` |
| #441 | D7/D8 reversal recorded; Codex queue: models, replies in English | `b1b54c98` |
| #438 | S64-0: four leaks in the "read outside content" mark, plus F1 | `3ee16b6c` |
| #436 | M64: code-review, split/delegate and inverse bench tasks; same-task Pass^3 | `43667421` |
| #440 | Memory plan in README §8; English-on-GitHub rule | `d7b96c30` |
| #433 | v0.1.64 Inbox: the user's eight points (merged 2026-10-27, before the plan) | `502012f5` |
| #439, #437, #435 | Codex queue, read-only Codex connection, #438 in the queue | `8df2d44e`, `ef356fb5`, `601baee0` |

## Ready for the user to merge

The user is merging in ④参谋's order: ~~#451 → #448 → #445 → #446 → #444~~ (merged) → #454 → #428.

**Codex (user, 2026-10-28 evening):** a PR with an OK from an independent Claude review by another session (effort=max on the security surface) does not go to Codex; Astra only for parts a Claude reviewer cannot review because of safeguards. #465 writes this into the plan. Each has an OK from another session and green CI on its head (see each PR). Also ready: #453 (M64 hand-check fix), #447 (SBX card; its seven questions are for the user).

- #443 (S64-0b): written by ③Hands; independent review by ②Main with its effort=max reviewer, OK at `390aa048` (CI 40675097201 success). No Astra needed under the new rule. ③Hands is merging main in (no force-push) so CI runs on the head you merge; ready after that run.
- #462 (BR1): ①iOS found a gap after testing build 25 (once Allow was clicked the Bridge dropped to the 10 s pace before the new phone's first hello). ⑥Helper's fix at `cd60c056` keeps the 2 s pace for 60 s after a code is answered; CI 40708948579 success. ①iOS rechecked it: OK, ready (it read the diff and relied on that CI run; the pairing pace is still bounded: an open code until it expires, an answered one for 60 s; no frame change). ①iOS does not post on PRs; its verdict is recorded here.
- #464 (code rules, sessions.md §12, card EXC1): docs only; ③Hands OK at `057fe7a6` (posted on the PR), plus its optional wording at `b7059ff3`. Best merged after #447 (lane table moves SBX to ③Hands).
- #465 (Codex only when a Claude review is blocked): docs only; ③Hands asked for missing pointers and the #443 wording, fixed at `7c93e2ec`; waiting for its recheck.
- #466 (INB1 follow-ups F2, F4): an independent effort=max Claude review is running.
- Also ready: #463 (BR2), #457 (CAP1b), #461 (CAP F3); each has its Claude review and says "Codex: not needed".
- #456 (F5b-2): ③Hands' review; ②Main's confirmation of its commit and CI pending.

## In progress

| Lane | Work |
|---|---|
| ②Main | INB1 follow-ups F2 + F4 (rebase on #460); after INB2 merges, learned practices use the per-conversation outside-content check too (user, 2026-10-28: a detour or machine quirk takes effect only when `runs.read_outside` says the whole conversation is clean, like "about you"; user corrections unchanged; until then the current-turn mark plus S64-0's carried marks), INB1 UI (waits for the user's mock), INB2 backend (migration 0072), C7c-2 #450 (stacked on #448), C7c-3 onward (waits for the user's answers to C7c Q1/Q2/Q4), SBX after its card |
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
