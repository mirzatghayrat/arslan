# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-28, evening.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #428 | Docs, site and READMEs to v0.1.63 | `319eef0e` |
| #454 | STY 20-reply read test (prompts, fixture, blind side-by-side page) | `1a8d010f` |
| #457 | CAP1b: migration 0074 drops `discovery_candidates` | `01354ad6` |
| #460 | INB1: learned practices take effect directly; what is not in effect says why (reviewed by another Claude session at effort=max; merged without Astra, see the Codex rule below) | `55168fad` (main CI 40710426557 success) |
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

The user is merging in ④参谋's order: ~~#451 → #448 → #445 → #446 → #444 → #454 → #428~~ (all merged; also #457). ④参谋 checked every open PR at ~15:10 UTC (heads, reviews, overlap with main); updated since.

**Who merges (user, 2026-10-28, confirmed in ⓪Plan's chat; written up in #467):** sessions enable GitHub auto-merge on docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface, once another session has OK'd the current head and every check is green; the user merges the security surface and ordinary product code. The classifier blocked ⓪Plan's `bind_pr` for auto-merge on #453, so until that is allowed the user merges ⓪Plan's PRs too.

**Codex (user, 2026-10-28 evening):** a PR with an OK from an independent Claude review by another session (effort=max on the security surface) does not go to Codex; Astra only for parts a Claude reviewer cannot review because of safeguards. #465 writes this into the plan.

**Ready now** (another session's OK at the current head, green CI on it):
- #461 (CAP F3): ⓪Plan's max reviewer at `1188c10d`; the later `9ec18990` is test-only (noted on the PR).
- #462 (BR1): ①iOS found a gap after testing build 25 (once Allow was clicked the Bridge dropped to the 10 s pace before the new phone's first hello); ⑥Helper's fix at `cd60c056` keeps the 2 s pace for 60 s after a code is answered; CI 40708948579 success. ①iOS rechecked it: OK (read the diff, relied on that CI run; no frame change). ①iOS does not post on PRs; its verdict is recorded here.
- #456 (F5b-2): ②Main confirmed at `54805cfd`, CI 40677484593 success. After it merges, ⓪Plan's docs sync drops the "Cua stays behind a dev-only build switch" sentence from docs-site and docs/, with the Cua lines already planned after #428.
- #443 (S64-0b): written by ③Hands; independent review by ②Main with its effort=max reviewer, OK at `390aa048`. Main merged in at `d2ab87e5`; CI 40712453311 success. No Astra under the new rule.
- #453 (M64 hand-check fix): ⑥Helper OK at `a3a127f7` after dropping the generic T2 keywords; the rescore with those checks gives identical per-run verdicts (the table holds).
- #458 (this page, SIDE card): ⑥Helper OK at `4cd3a0c0` (facts checked against GitHub); later commits only update this page.
- #463 (BR2): ①iOS OK at `609de05d`, covering `d01381ec` (main merged in, one test line for C5b's renamed edit_file arguments); CI 40713934590 success. Bridge surface: the user merges.
- #459 (PRJ0): ⑤CAP's review at effort=max, OK at `539b684d`, CI 40682295664 success; also checked merged with current main (ruff, 218 tests, tsc, 37 web tests). The classifier blocked ⑤CAP's PR comment, so the review is recorded here; posting it is the user's call.

**Waiting for CI or a re-OK:**
- #464 (code rules, sessions.md §12, card EXC1): ③Hands OK at `057fe7a6` on the PR; `b7059ff3` is its own wording; ③Hands posts that the OK covers it. Best merged after #447 (lane table moves SBX to ③Hands).
- #465 (Codex only when a Claude review is blocked): ③Hands OK at `7c93e2ec`; one pointer added at `e075d479` (no recheck needed, per ③Hands).
- #447 (SBX card): the user answered its seven questions (2026-10-28, ~15:20 UTC), written into the card at `18c88202`; ③Hands posted that the decisions section matches. `cac07791` adds one line from ③Hands' SBX-1 check (SBX-4 sorts `computation_profile`'s set-order lines). Decisions: network N-a (a minimal local proxy, no site list) if SBX-M's breakage is acceptable, otherwise the numbers go back to the user before N-b; manually added MCP servers stay unsandboxed and the form says so; reads stay open minus the protected and closed folders; keep today's card when the sandbox cannot start; "ask only when risky" stays off until S2a-3 and S5a; the re-run share is only recorded; `ssh_exec` onto the builder in SBX-1.
- #466 (INB1 follow-ups F2, F4): independent effort=max review done: **merge after fixes**. Medium: with F2, stopped rows can take `_nearest`'s two slots and push an active rival out of the conflict check, so a conflicting practice can take effect directly (INB1 case 5). Low: a test gap (a merge must not rewrite a stopped row's words), the sheet does not reload on 409, and an optional conditional update. It also recommends making `expected_updated_at` required for `status=active`. Sent to ②Main; the classifier blocked posting it on the PR, so posting is the user's call.

## In progress

| Lane | Work |
|---|---|
| ②Main | INB1 follow-ups F2 + F4 (rebase on #460); after INB2 merges, learned practices use the per-conversation outside-content check too (user, 2026-10-28: a detour or machine quirk takes effect only when `runs.read_outside` says the whole conversation is clean, like "about you"; user corrections unchanged; until then the current-turn mark plus S64-0's carried marks), INB1 UI (waits for the user's mock), INB2 backend (migration 0072), C7c-2 #450 (stacked on #448), C7c-3 onward (waits for the user's answers to C7c Q1/Q2/Q4), SBX after its card |
| ③Hands | SBX-1 (builder written, byte-for-byte check 0 of 32 differ); PRJ0's table drop 0076 after #459 |
| ⑤CAP | CAP1b #457 (0074), CAP1c (0075, after #457), CAP2a (at max) |
| ⑥Helper | STY #452 (draft; gated on the read test and a bench "after" run), SIDE after SUB2 |
| ⓪Plan | M64 (baseline done, hand check #453), STY read test #454 (page with the user), mid-version M1 round, cards |

## Waiting on the user

- The STY read page (export the choices to ⓪Plan).
- Two classifier pass lines in #444: X% of the approvable scope (⓪Plan suggests ≥ 70%) and the failure fallback cap (≤ 5%).
- C7c questions 1, 2, 3 (DELETE-BY move for `/brain/proposals*`), 4.
- Real-Mac checks: FS1 (#451) and the Hands smoke for F5b-2 (#456), both on `SMOKE.md` (#447).
- Making the `language` CI job a required check (branch protection, after #446).
- The side-chat mock (SIDE-0), when it comes.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
