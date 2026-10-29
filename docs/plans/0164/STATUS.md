# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-29, evening.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #484 | SB1 sidebar card; projects double as groups in v0.1.65; this page | `5fcb4c17` |
| #485 | F5b follow-up: drop the H2 codes nothing says since the Cua Driver engine went | `47bf7345` (its main CI 40807766855 was cancelled by the next merge; 40808069306 at `5fcb4c17` covers it, with #477, #483 and #484) |
| #483 | Migrations 0078 (Q1 #3) and 0079 (SB1) logged | `3e5b61cf` |
| #477 | SBX-1b: SBPL strings written as UTF-8, so non-ASCII paths match | `afd32481` |
| #474 | Classifier pass lines complete; C7c answers (user, 2026-10-29) | `17f52a82` (its main CI 40806097374 was cancelled by the next merge; 40808069306 at `5fcb4c17` covers it) |
| #482 | The user's 10-29 answers on INB2 F2/F4 and Q1 points 3/4 (auto-merged) | `5988cb4d` (main CI 40803537315 success; it covers every merge down to #447, whose own runs were cancelled by the next merge) |
| #458 | SIDE card and this status page | `96c77bf1` |
| #464 | No over-defence (sessions.md §12); EXC1 card | `0955ee49` |
| #456 | F5b-2: delete the Cua Driver engine files | `a1462abe` |
| #461 | CAP1a follow-up: outside names leave `propose_capability`'s sentences | `ccc48187` |
| #466 | INB1 follow-ups (#460 review F2, F4) | `150f9d4b` |
| #479 | Q1a: quick questions on the Mac (migration 0071) | `94957f10` |
| #471 | SBX-1: one builder writes every seatbelt profile | `1ba98620` |
| #447 | SBX card | `3d060b98` |
| #481, #480, #478 | Q1 frame names, paging cursor (strictly older, whole seconds) | `7ba6686d`, `c495bcef`, `b910b9a0` |
| #476 | Migration numbers assigned; CAP2b gets 0077 | `cfc7e77a` |
| #443 | S64-0b: mark attachments and OCR text; frame background job results from outside content | `c2aaff29` (covered with #462 and #467 by main CI 40732986853 on `cfc7e77a`, success; 40731335249 was cancelled) |
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

The user is merging in ④参谋's order (2026-10-29). Batch 1 is done. Batch 2 goes one at a time, with main green between each: **#472 → #463 → #459 → #473**. A PR that turns conflicting or stale is synced by its author session and re-run before it goes to the user.

**Who merges (#467):** sessions auto-merge docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface after another session's OK on the current head and green checks. The user merges the security surface and ordinary product code.

- #472 (CAP2a): final effort=max verdict at `a130afef`, merge; CI 40735022447 success (all five jobs). Security surface. **First of batch 2.**
- #463 (BR2): ①iOS OK at `d01381ec`; Bridge surface. After #472.
- #459 (PRJ0): ⑤CAP's effort=max OK at `539b684d`. After #463.
- #473 (CAP1c, migration 0075 drops `capability_finds`): main merged in at `06117e63` (only the migration-runner test conflicted: 0071 and 0075 both kept); ⓪Plan checked the diff against main is still the reviewed 4 files, 71+/1−. CI 40803555940 success. Drops data. Last.

## In progress

| Lane | Work |
|---|---|
| ②Main | Q1b #486 (Bridge frames; ⓪Plan's effort=max reviewer on `9249401a`), Q1 #3 (migration 0078), then the pocket deletion (the old pocket stays a Mac-only conversation; every phone frame naming it is refused, inbound and outbound: #487). INB2 #475: the user's F2 (allowlist) and F4 (`sensitive: true`) at `40e8a8ab`, main merged in at `4420c21a`; ⓪Plan's effort=max reviewer is rechecking `4420c21a..40e8a8ab`. Then Q1b (Bridge frames, `sent_at`), then Q1 #3 (conversion boundary, migration 0078), then the pocket deletion. #483 logs migrations 0078/0079 |
| ③Hands | **SBX-2 is stopped:** a safety classifier stopped ③Hands' response as it started SBX-2 (2026-10-29), right after reading the SBX card. Per the card's "Risks and rollback", it is not worked around, reworded or moved to another session; no SBX-2 code exists (the local branch `claude/0164-sbx2-default-deny-preset`, not pushed, is clean at `47bf7345`). Waiting for the user. CLS and S5b come after SBX, so this is on v0.1.64's critical path. Then: drop `no_effect` / `partly_done` / `refused` from the Hands outcome words (deletion-only, after #485); after #459, the 0076 table-drop PR (the user merges) |
| ⑤CAP | CAP2b (0077) after #472 |
| ①iOS | Q1c waits on the user's OK on the Quick Ask mock; it can ship with Mac 0.1.64 |
| ⑥Helper | STY #452 (draft), SIDE after SUB2, SB1 after the pocket deletion and INB4 (mock first) |
| ⓪Plan | M64, STY read tally, mid-version M1 round, cards; the docs-site Cua sentence in the v0.1.64 docs pass |

## Waiting on the user

- **SBX-2, stopped by a safety classifier** (see In progress): how to proceed is the user's call.
- **The Quick Ask mock (Q1c)** from ①iOS: no iPhone UI code until it is OK'd. The pocket is deleted in v0.1.64 only if Q1c ships with Mac 0.1.64.
- The STY read page: the user exports the choices (JSON) to ⓪Plan, which tallies them.
- Real-Mac checks: FS1 (#451) and the Hands smoke for F5b-2 (#456), both on `SMOKE.md`.
- Making the `language` CI job a required check (④参谋 is walking through it).
- The side-chat mock (SIDE-0) and the sidebar mock (SB1-0), when they come.

**Decided on 2026-10-29:** the classifier pass lines are complete (≥ 70% of the approvable scope answered; ≤ 5% failure fallback), and C7c Q1–Q4 are answered (experts become skills automatically in the migration; private knowledge goes to the general base with a label; the v1 views and `/brain/proposals*` go in v0.1.65; `list_spawns` is removed now). Recorded in #474. Also decided on 2026-10-29: INB2 F2 is an allowlist and F4 is an optional stricter-only `sensitive: true`; the Bridge passes the envelope `ts` as `sent_at`; a converted quick ask learns from the conversion on; the pocket goes in v0.1.64 if Q1c ships with it, else v0.1.65 (recorded in #482). The pocket's old messages stay as a Mac-only conversation (#487). The sidebar card SB1 is in v0.1.64, and projects double as groups in v0.1.65 (this PR).

## Codex to write (user, 2026-10-29)

**Why:** a safety classifier stopped ③Hands as it started SBX-2. The user had the cloud audit split SBX and S2a-3, and approved the split. What Claude cannot write goes to Codex (SBX card, "Who writes what"). Reviews: Astra (highest level) in a new Codex session, never the session that wrote it. Claude reviews the non-probe plumbing. The existing review queue is in [`docs/plans/0162/STATUS.md`](../0162/STATUS.md), "Codex 待审".

**Where the chain is stuck:** SBX-2 (Codex). HR, CLS, S5a and S5b wait on it; see README §4, "Reordered 2026-10-29". ③Hands does other owed work meanwhile. Its local SBX-2 branch stays untouched.

**How Codex delivers (user, 2026-10-29; replaces the fork plan from earlier that day).** No new account and no fork: Codex signs in with the user's own GitHub. It may push branches and open PRs. **It never merges**, never pushes to `main`, and never pushes to another session's branch. That is an agreement the user accepted, not a technical lock: the user merges every security PR anyway.

**Steps for the user:**
1. Give the ChatGPT Codex Connector access to `mirzatghayrat/arslan` (GitHub → Settings → Applications → the connector → Repository access). Today it is limited to one unrelated public repository (`docs/plans/0162/README.md`, "「只读」怎么做到").
2. In Codex, tell it the rules once: open PRs only, never merge, never push to `main` or to someone else's branch. If Codex has a setting to ask before pushing or merging, consider turning it on (optional).
3. Each Codex branch starts with `codex/`. Each PR gets the label `codex`. Every commit message and PR body says "Author: Codex (model, reasoning level)" and names the reviewer, and the PR carries the four evidence items (`docs/sessions.md` §8) plus its macOS CI run id.
4. The user merges every Codex PR (all are on the security surface).

**A risk to know (⓪Plan, 2026-10-29), your call:** the connector's write access includes workflows. A branch pushed to this repository runs its own workflow files on `push` with the repository's Actions secrets. `release.yml`'s guard (`:25-26`, no `pull_request` trigger) protects against fork PRs, not against a pushed branch. Those secrets include the updater's signing key (`release.yml:132-133`). One option: move the release secrets into a GitHub Environment that only `v*` tags can use and that needs your approval. That is a repository-settings change, so it is yours to decide.

**The tasks (one paste per block).** Each task points to card sections only. Codex designs the tests' content itself from the card; nothing here spells it out.

| Block | Paste this to Codex | Ready? |
|---|---|---|
| SBX-2 | "Write SBX-2 for mirzatghayrat/arslan on a `codex/` branch (open a PR labelled `codex`, never merge): read `docs/plans/0164/SBX-sandbox.md` in full, then do the SBX-2 row of 'PR split' with the scope in 'Who writes what', §1, §2 and §M. Build on SBX-1's builder (`server/services/sandbox_profile.py`, merged). Make the harness parameterised by base name. Not wired to any entry point. Real-seatbelt tests run on the macOS CI job. Follow `docs/sessions.md` §5, §8, §9 and §12. Write everything in English. Put \"Author: Codex\" and the reviewer in each commit and the PR, with the four evidence items and the macOS CI run id." | **Yes** |
| SBX-3p … 6p | "Write SBX-Np (N = 3, 4, 5 or 6): read the SBX card's 'Who writes what' and the SBX-N row and sections it names, then write the real-seatbelt tests that what SBX-N should deny is denied, as parameters of SBX-2's harness. No product code." | After SBX-2 and SBX-M; 6p only with SBX-6 |
| Allowlist after SBX-M | "Read the SBX-M report (`docs/plans/0164/SBX-measurement.md`) and the SBX card §2; propose the allowlist change it calls for, ≤ 50 lines." | After SBX-M |
| S2a-3 tests | "Read `docs/plans/0162/S2a-command-three-layers.md` (S2a-3) and the S2a-3 row of `docs/plans/0164/README.md` §3; write the test content named there for #375 / #376 / #378 / #396 and #406, against the rebased heads." | After SBX-7 and ③Hands' rebase |

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
