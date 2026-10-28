# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-28, evening.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #443 | S64-0b: mark attachments and OCR text; frame background job results from outside content | `c2aaff29` (main CI 40731335249 running; covers #462 and #467) |
| #462 | BR1: Bridge polls every 2 s while a pairing code is open, and for 60 s after it is answered | `cd6e7edb` |
| #467 | sessions.md §5 "Who merges": sessions auto-merge non-security PRs (the first one merged by auto-merge) | `ba5964dd` |
| #453 | M64 hand check of r64-m64-base: missing keywords, one T15 extra; generic T2 words left out | `8532152f` (main CI 40723824079 running; it covers #470, #468, #469 and #465 too, whose own runs were cancelled by the next merge) |
| #465 | Codex only for what a Claude review cannot cover | `579c606d` |
| #469 | STY2 card: Arslan's working method, deeper not bigger | `4081d6d7` |
| #468 | sessions.md §6: a new card has four lines | `756dd841` |
| #470 | LANG1: exempt the published docs site under `docs/docs/` (fixes main's red `language` job) | `55582c65` |
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
- #456 (F5b-2): ②Main confirmed at `54805cfd`, CI 40677484593 success. After it merges, ⓪Plan's docs sync drops the "Cua stays behind a dev-only build switch" sentence from docs-site and docs/, with the Cua lines already planned after #428.
- #458 (this page, SIDE card): ⑥Helper OK at `4cd3a0c0` (facts checked against GitHub); later commits only update this page.
- #463 (BR2): ①iOS OK at `609de05d`, covering `d01381ec` (main merged in, one test line for C5b's renamed edit_file arguments); CI 40713934590 success. Bridge surface: the user merges.
- #447 (SBX card): ③Hands OK at `017660a2` (posted on the PR), all checks green. Order: **#447 → #471 → #477**. Already all-green, so a session cannot auto-merge it: the user merges.
- #471 (SBX-1: one profile builder, all five profiles on it): ③Hands; ②Main's max reviewer: merge after fixes, all four in at `39ac6ae0`, ②Main's recheck OK; CI 40728593104 success (macOS 60). **Ready for the user, after #447.**
- #477 (SBX-1b: seatbelt non-ASCII path encoder; stacked on #471): ③Hands; ②Main's max review asked for one test (a non-ASCII protected file, literal, under real seatbelt), added at `f8da97c5`; recheck OK; CI 40733737208 success (macOS 69). **Ready for the user. Order: #447 → #471 → #477.** Next in the lane: SBX-2 stacked on it. Follow-up for ⓪Plan after it lands: the bench's `sandbox.sb.template` substitutes `{ROOT}`/`{HOME}` unescaped; use `sbpl_string`.
- #472 (CAP2a: the save-a-skill card; deletes Skill Forge, the curator and candidates): independent effort=max review: no path writes a skill without a click; what is shown is what is stored; 16 of 16 mutations caught. Fixes F4–F7 and R1 done (`4063335b`, recheck running). **User decided F1/F2 (2026-10-29): keep the mark.** A skill saved from a card that showed the outside line is stored as `authored-outside`; reading it later marks the turn; the outside line reflects the whole conversation (INB2's `runs.read_outside`). F8 decided with it. F3 is a follow-up. Security surface: the user merges.
- #473 (CAP1c: migration 0075 drops `capability_finds`): ⑥Helper OK at `a09b0392`; ⑤CAP fills in the CI run id and the backup note (last three archives). Drops data, so the user merges.
- #459 (PRJ0): ⑤CAP's review at effort=max, OK at `539b684d`, CI 40682295664 success; also checked merged with current main (ruff, 218 tests, tsc, 37 web tests). The classifier blocked ⑤CAP's PR comment, so the review is recorded here; posting it is the user's call.

**Waiting for CI or a re-OK:**
- #464 (code rules, sessions.md §12, card EXC1): OK at the current head `3e4e6fb4` (③Hands at `b7059ff3`, ⑥Helper re-OK after the main merge); all checks green, so the user merges. Best after #447.
- #466 (INB1 follow-ups F2, F4): the same effort=max reviewer rechecked twice; at `759a6bb2` (the scan-window fix and the F2 test nit added): **merge** once CI 40723524451's macos job is green (the other four passed). The conditional UPDATE (finding 4) is the user's call. Learned-practice write: the user merges.

## In progress

| Lane | Work |
|---|---|
| ②Main | INB1 follow-ups F2 + F4 (rebase on #460); after INB2 merges, learned practices use the per-conversation outside-content check too (user, 2026-10-28: a detour or machine quirk takes effect only when `runs.read_outside` says the whole conversation is clean, like "about you"; user corrections unchanged; until then the current-turn mark plus S64-0's carried marks), INB1 UI (waits for the user's mock), INB2 backend (migration 0072), C7c-2 #450 (stacked on #448), C7c-3 onward (waits for the user's answers to C7c Q1/Q2/Q4), SBX after its card |
| ③Hands | SBX-1 #471 in review; SBX-2 (default-deny base and service allowlist as a preset, not wired; macOS behaviour tests; corpus harness) from #471's head after ②Main's findings; PRJ0's table drop 0076 after #459 |
| ⑤CAP | CAP1b #457 (0074), CAP1c (0075, after #457), CAP2a (at max) |
| ⑥Helper | STY #452 (draft; gated on the read test and a bench "after" run), SIDE after SUB2 |
| ⓪Plan | M64 (baseline done, hand check #453), STY read test #454 (page with the user), mid-version M1 round, cards |

## Waiting on the user

- The STY read page: sent to the user on 2026-10-29; the user exports the choices (JSON) to ⓪Plan, which tallies them.
- Real-Mac checks: FS1 (#451) and the Hands smoke for F5b-2 (#456), both on `SMOKE.md` (#447).
- Making the `language` CI job a required check: main is green again (CI 40723824079 on `8532152f`, including `language`); the user agreed in principle and ④参谋 is walking through the ruleset setting.
- Allowing `bind_pr` and `set_auto_merge` in the user's settings (④参谋 is walking through it); then ⓪Plan tries auto-merge on the next non-security docs PR.
- The side-chat mock (SIDE-0), when it comes.

**Decided on 2026-10-29:** the classifier pass lines are complete (≥ 70% of the approvable scope answered; ≤ 5% failure fallback), and C7c Q1–Q4 are answered (experts become skills automatically in the migration; private knowledge goes to the general base with a label; the v1 views and `/brain/proposals*` go in v0.1.65; `list_spawns` is removed now). Recorded in #474.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
