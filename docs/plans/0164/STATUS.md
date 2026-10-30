# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-30, late evening.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #534 | Tests: a card's wait is a clock jump, not a real sleep (LOAD2 part 1) | `7e2dcd70` |
| #533 | STATUS: the CAP4a-2 runtime question for the user | `561535b0` |
| #532 | Tests: a job's result is read after the job reports it (LOAD2) | `bd380ab5` |
| #530 | WB1-2: Overview is the workbench's default tab; the fixed tabs become icons | `2044f5b3` |
| #529 | Migration 0081 reserved for SEC1 | `01c6665f` |
| #516 | This page, 10-30 evening | `4de8cab6` |
| #524 | ci.yml: the macOS job expects 362 cases (merged into the Codex branch of #507, not main) | `6810e000` |
| #523 | SBX: listening denied for now; decide how it returns before SBX-3 (user, 2026-10-30) | `35afe571` |
| #521 | Tests: the still-working beat test waits until the turn is recorded | `9b89f1d9` (main CI 41021298870 success; the runs on `48da0348`, `2e59cee4`, `ddedabcd`, `5af69382` and `0628d26c` were cancelled by the next merge, and this one covers them) |
| #522 | Q1: kind-changing resend wording matches the code | `0628d26c` |
| #517 | WB1-1: the workbench is a fixed row (Working folder, Progress, Browser); the Task tab goes; Bing words in the address field | `5af69382` |
| #518 | DIFF1 and DIFF2 cards | `ddedabcd` |
| #514 | WB1-3 Changes; Working folder chosen | `2e59cee4` |
| #475 | INB2: "about you" memories take effect when the user is present and the conversation is clean | `48da0348` |
| #515 | The v0.1.64 cut proposal (not adopted, see below) | `2e8a3b65` |
| #513 | WB1-2 Overview; FRONT1 decided | `e8580458` |
| #504 | Follow-up cards NAME1, TITLE1, MCPOUT1 | `b3f31303` |
| #502 | CAP gh- follow-up: migration 0080 marks old Discover skills as outside | `12ff908f` (main CI 40990735670 success) |
| #499 | CAP3a-1: capability rows (section, origin, deletable, last used); DELETE refuses built-ins | `89675b4d` |
| #496 | CAP2b: migration 0077, promoted skills marked by source; drops skill_candidates | `5f4047bd` (main CI 40985240648 success) |
| #495 | CAP1a follow-up: MCP labels; odd tool names mark the turn | `d153f293` |
| #486 | Q1b: the Bridge takes Quick Chat and new conversations | `cd56cc8a` |
| #501 | This page, 10-30 | `3192ba1b` |
| #494 | PRJ0: migration 0076 drops `project_habits` and `project_levels.habit` | `80de850a` (main CI 40976699220 running when this was written) |
| #497 | Codex plan A: Codex commits locally, the user pushes | `2eb00abb` (main CI 40838498833 success) |
| #493 | SBX and S2a-3 split between Claude and Codex; Codex queue; reordered chain | `e1f505ce` |
| #492 | Q1c scope (Quick Chat), retry-kind rule, FRONT1, STATUS after batch 2 | `947a036c` |
| #491 | Hands: drop `partly_done` and `refused` | `423b828a` (main CI 40827479020 success, covering #492 and #493) |
| #473 | CAP1c: migration 0075 drops `capability_finds` | `4e44843f` (main CI 40819237121 success) |
| #459 | PRJ0: delete learned gate-advancing, rhythm stats and stall reminders | `a528c3ff` (main CI 40817737252 success) |
| #463 | BR2: a turn offers each file once, its last version | `63d58666` (main CI 40816568246 success) |
| #472 | CAP2a: delete Skill Forge, the curator and the candidates; `create_skill` becomes a card | `efa64c44` (main CI 40812701073 success) |
| #489 | WB1 workbench card; one mock with SIDE-0 | `c83d7ed9` |
| #488 | This page: batch 1 done; SBX-2 stopped | `77fdbc64` |
| #487 | Q1: the pocket's old messages stay a Mac-only conversation; every phone frame naming it is refused | `b17ac722` (its run 40809106133 and #488's 40809540713 were cancelled by the next merge; 40809665261 at `c83d7ed9` covers #487, #488 and #489, success) |
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

Only PRs with an independent effort=max OK **at the current head** and green CI are listed here. All of them are on the security surface, so the user merges each one.

1. **#490** (Q1 #3, migration 0078) at `b9acf73b`. CI is green.
2. **#512** (FRONT1: A plus the corrected B) at `85b6f46c`. CI is green.
3. **#519** (SKF1: which skills read as Arslan's own is an allowlist) at `60d02f77`. CI is green.

**Under review, not ready yet (don't merge these):**

- **#526** (UNI1a) at `a3a5255d` and **#536** (SEC1, server half): ⓪Plan's effort=max reviews are running.
- **#525** (Q1 #4, retire the pocket): ②Main fixed the review's F1–F4 in `71dbc0ce` (on a merge of main); its full backend suite is running, then ⓪Plan's reviewer takes a glance. It also waits on the user's go after Q1c ships.
- **#527** (MCPOUT1): stacked on #519; retargeted to main once #519 merges.
- **#507** (SBX-2, Codex) at `8751d6f7`: all five checks are green. Astra's review is posted (08:51Z): Medium 1 is fixed by #524, and Medium 2 is addressed in `8751d6f7`. Left: confirm the Medium 2 fix, and ⓪Plan's plumbing re-OK at `8751d6f7`.
- **#520, #531, #535** (SBX-3a, 4a, 5a, ③Hands): drafts. They don't merge before SBX-2 and SBX-M.

**Who merges (#467):** sessions auto-merge docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface, after another session's OK on the current head and green checks. The user merges the security surface and ordinary product code. For SB1 and WB1, the user's approval also lets the author auto-merge.

## In progress

| Lane | Work |
|---|---|
| ②Main | #525 after F1–F4 (pocket retirement); C7c-2 #450 |
| ③Hands | SBX-3a #520, 4a #531, 5a #535 drafts; SBX-7 next; then NAME1 and TITLE1 |
| ⑤CAP | CAP4a-1 (skills pinned to a sha, scanned and hashed before the card); CAP4a-2 waits on the runtime question below. Its PRs #519, #526, #527, #536 are open |
| ⑥Helper | LOAD2 part 2 (`server/mcp/session.py`, stdio's closed pipe) after #534; then LOAD3; WB1-3; STY #452 waits on the read |
| ①iOS | Q1c done (build 30 on TestFlight). After #525 merges, it copies the 42-example `messages.json` again |
| Codex (via ⑦Codex) | SBX-2 #507 fixes |
| ⓪Plan | Reviews of #526 and #536 (effort=max); this page; LOAD3 card (README §3.11b) |

## Waiting on the user

- **CAP4a-2: when the runtime downloads (⑤CAP).** The card says resolve → lock → card. Making a lock needs a runtime (uv for PyPI, npm for npm), which today downloads only after the user says yes. The options:
  - (a) download Arslan's own pinned, checksummed runtime before the card;
  - (b) if the runtime is missing, show the card without a lock and stop the install if the lock pulls in anything the card didn't name;
  - (c) recommended: first a small card that only asks to download the runtime, then the real card with its lock. This keeps "nothing downloads before a yes".

  CAP4a-1 (skills pinned to a sha, with every file scanned and hashed before the card) goes ahead meanwhile.
- **UNI1b and SEC1 mocks** (⑤CAP), sent as private links.
- **Merges:** the "Ready" list above, in that order.
- **The STY read, once more:** the exported verdicts are from an earlier page (`3a107ed670ba`), and every row in them is empty: the export happened half a minute after that page was made. So the read hasn't been done yet. Re-read `sty-read-v0164.html` and export again. STY stays in draft until then.
- **SB1-0 mock picks:** the sections (match the iPhone, or add 30 days), a time on rows or headings only, and Pinned above or below Projects. (WB1's tab name is decided: Working folder.)
- **SB1 raw material:** a read-only count of conversations by section. ⑥Helper's query was blocked, so the user runs it or allows it.
- **SBX-2 (#507):** merge it once Medium 2 and the plumbing re-OK are confirmed (security surface).
- **Real-Mac checks:** Quick Chat end to end with build 30 (needs a 0.1.64 dev build and pairing); FS1 (#451); the Hands smoke for F5b-2 (#456).
- **Release secrets into an Environment** (plan B for Codex), once the user has the originals of the updater's private key and the Apple certificate.
- **0077's `authored` skip (#519 review, low):** 0077 leaves alone any promoted candidate's row already labelled `authored`. The old Forge and create_skill accepted any category, so a skill_creator row labelled literally `authored` still reads as Arslan's own. Recommended: drop `authored` from 0077's `_UNMARKED` before v0.1.64 ships; no released build has 0077.
- **`unknown` skills (#519):** not deletable today (D7), and they can be switched off. Should they be deletable like `authored`? No real row is `unknown` today.

**Decided on 2026-10-29:** the classifier pass lines are complete (≥ 70% of the approvable scope answered; ≤ 5% failure fallback), and C7c Q1–Q4 are answered (experts become skills automatically in the migration; private knowledge goes to the general base with a label; the v1 views and `/brain/proposals*` go in v0.1.65; `list_spawns` is removed now). Recorded in #474. Also decided on 2026-10-29: INB2 F2 is an allowlist and F4 is an optional stricter-only `sensitive: true`; the Bridge passes the envelope `ts` as `sent_at`; a converted quick ask learns from the conversion on; the pocket goes in v0.1.64 if Q1c ships with it, else v0.1.65 (recorded in #482). The pocket's old messages stay as a Mac-only conversation (#487). The sidebar card SB1 is in v0.1.64, and projects double as groups in v0.1.65 (this PR).

## Codex to write (user, 2026-10-29)

**Why:** a safety classifier stopped ③Hands as it started SBX-2. The user had the cloud audit split SBX and S2a-3, and approved the split. What Claude cannot write goes to Codex (SBX card, "Who writes what"). Reviews: Astra (highest level) in a new Codex session, never the session that wrote it. Claude reviews the non-probe plumbing. The existing review queue is in [`docs/plans/0162/STATUS.md`](../0162/STATUS.md), "Codex 待审".

**Where the chain is stuck:** SBX-2 (Codex). HR, CLS, S5a and S5b wait on it; see README §4, "Reordered 2026-10-29". ③Hands does other owed work meanwhile. Its local SBX-2 branch stays untouched.

**How Codex delivers: plan A (user, 2026-10-29, final for now).** Codex writes and commits locally and does not push. The ChatGPT Codex Connector keeps its current access, which does not include `arslan`. The user pushes Codex's branch and opens the PR. The rules stay the same:
- branches start with `codex/`, and PRs carry the label `codex`;
- every commit message and PR body says "Author: Codex (model, reasoning level)" and names the reviewer;
- PRs carry the four evidence items (`docs/sessions.md` §8) and the macOS CI run id;
- Codex never merges, never pushes tags, and never changes `.github/`;
- the user merges every Codex PR, since all of them are on the security surface.

**Pushing a Codex branch (the user runs this).** Run it in the folder where Codex worked, which is Codex's own checkout of `arslan`, after Codex says its branch is committed. `<branch>` is the branch Codex names, for example `codex/sbx2-default-deny-base`. `<body file>` is the PR body Codex wrote, with the four evidence items.

```bash
git fetch origin
git status
git log --oneline origin/main..<branch>
git diff --stat origin/main...<branch> -- .github
git push -u origin <branch>
gh pr create --repo mirzatghayrat/arslan --base main --head <branch> --label codex --title "<title Codex gave>" --body-file "<body file>"
```

- Before pushing, check three things:
  - `git status` is clean;
  - the log shows only Codex's commits;
  - **the `.github` diff prints nothing.**
- If the `.github` diff lists anything, don't push. In plan A your push is the only gate. A pushed branch's workflows run with the repository's secrets (only fork PRs are cut off), so tell ⓪Plan; a Claude session makes any workflow change in its own PR (②Main's review of #497).
- The first time only, create the label: `gh label create codex --repo mirzatghayrat/arslan --description "Written by Codex"`.
- Then tell ⓪Plan the PR number. Claude reviews the plumbing, and Astra reviews the rest.

**Later, plan B (Codex pushes by itself):** only after the release secrets are protected (see "Waiting on the user").

**Why plan B waits (⓪Plan and ②Main, 2026-10-29):** giving the connector write access would include workflows and Actions. Two workflows read the repository's secrets, and both have `workflow_dispatch`: `release.yml:32` and `secrets-preflight.yml:26`. Those secrets include the updater's signing key (`release.yml:132-133`). With that access, Codex could dispatch either workflow on a `codex/` branch, which runs that branch's edited copy, or push a branch that adds a workflow of its own. `release.yml`'s guard (`:25-26`, no `pull_request` trigger) only protects against fork PRs. `ci.yml` reads no secrets.
The fix, for when the user has the originals, is to move the secrets into a GitHub Environment:
- the Environment holds every `APPLE_*` and `TAURI_*` secret;
- its lock is a required reviewer, you. A "`v*` tags only" rule is not a lock when the same login can push tags;
- both `release.yml`'s job and `secrets-preflight.yml`'s job name the Environment, or they lose the secrets.
That is a repository-settings change. The `environment:` lines for the two workflows are proposed at the same time, not before.

**The tasks (one paste per block).** Each task points to card sections only. Codex designs the tests' content itself from the card; nothing here spells it out.

| Block | Paste this to Codex | Ready? |
|---|---|---|
| SBX-2 | "Write SBX-2 for mirzatghayrat/arslan on a local `codex/` branch. Commit, don't push; the user pushes and opens the PR. Read `docs/plans/0164/SBX-sandbox.md` in full, then do the SBX-2 row of 'PR split' with the scope in 'Who writes what', §1, §2 and §M. Build on SBX-1's builder (`server/services/sandbox_profile.py`, merged). Make the harness parameterised by base name. Not wired to any entry point. Real-seatbelt tests run on the macOS CI job. Follow `docs/sessions.md` §5, §8, §9 and §12. Write everything in English. Put 'Author: Codex' and the reviewer in each commit, and write the PR body to a file with the four evidence items; the macOS CI run id is added once CI has run." | **Yes** |
| SBX-3p … 6p | "Write SBX-Np (N = 3, 4, 5 or 6): read the SBX card's 'Who writes what' and the SBX-N row and sections it names, then write the real-seatbelt tests that what SBX-N should deny is denied, as parameters of SBX-2's harness. No product code." | After SBX-2 and SBX-M; 6p only with SBX-6 |
| Allowlist after SBX-M | "Read the SBX-M report (`docs/plans/0164/SBX-measurement.md`) and the SBX card §2; propose the allowlist change it calls for, ≤ 50 lines." | After SBX-M |
| S2a-3 tests | "Read `docs/plans/0162/S2a-command-three-layers.md` (S2a-3) and the S2a-3 row of `docs/plans/0164/README.md` §3; write the test content named there for #375 / #376 / #378 / #396 and #406, against the rebased heads." | After SBX-7 and ③Hands' rebase |

More decided on 2026-10-29 and 2026-10-30, all by the user:
- #475 H1 "trace notes back", H2 "count the project card", and old notes fail closed;
- #486 G1 "server fails closed";
- #495 "mark odd MCP tool names";
- #496 "split by source";
- MCP tool descriptions from an approved server stay unmarked, as a stated limit;
- the English name is "Quick Chat";
- Codex works under plan A.

**Decided on 2026-10-30 (user, relayed by ④参谋):**
- **Deletable scope:** skills Arslan wrote (`authored` and `authored-outside`) and connections the user added by hand may be deleted, as #499 and #500 built them. Built-in and seeded items stay non-deletable (409). The deleted skill's text goes to the Trash.
- **The long-term approach over minimal patches:** cards SKF1, UNI1 and SEC1 (README §3.12).
- **FRONT1:** options A and B, in one PR (user, 2026-10-30, in ③Hands' chat). It is #512: OK from the security side at `7dd5eade`, with a small window-title fix to land before the user merges.

**Not adopted (user, 2026-10-30):** the v0.1.64 cut (#515). The user's words: 「现在没有按"截断方案"吧，我不太想一直有任务推到后面只为了快上线新版本 我只是想要合理推进 不要老是原地踏步」. The scope stays as planned. What the user wants is steady, visible progress: every lane busy on its next card, reviews in parallel, no PR left idle on a sync or a review, and Codex's next SBX block queued as soon as the previous one lands. Progress is reported as PRs merged per round and what moved on the critical path.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
