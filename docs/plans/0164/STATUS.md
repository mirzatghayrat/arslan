# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-30, evening.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
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

1. **#475** (INB2) at `b97d7947`, which merges main in with no change to the PR's own diff (⓪Plan compared the added and removed lines; 52 files, +2287/−340). Final review: "merge" at `714ddd5b`. **Merge once its CI is green.**
**Next, not ready yet (don't merge these):**

2. **#512** (FRONT1: A plus the corrected B) at `4eeca06c`, which merges main in. ⓪Plan's effort=max review is running on `5d08b538`. It goes after #475 (hot file).
3. **#490** (Q1 #3, migration 0078): after #475, ②Main merges main in per the reviewer's spec, plus the PUT-lock commit and the `kind_of` PUT guard. The reviewer then glances at it, and it merges last of these.
4. **#507** (SBX-2, Codex): not ready. Its macOS job has 3 real failures for Codex to fix, and the plumbing review asked for fixes. Astra's review is the user's to start. **#508** (ci.yml 69 → 359) is OK'd; the user merges it into the Codex branch.

**Who merges (#467):** sessions auto-merge docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface, after another session's OK on the current head and green checks. The user merges the security surface and ordinary product code. For SB1 and WB1, the user's approval also lets the author auto-merge.

## In progress

| Lane | Work |
|---|---|
| ②Main | #475 waits for CI and the user. Next: the chat-liveness load-tolerance fix (test-only), then the pocket-deletion prep (it waits on the user's go), then #490's merge after #475 |
| ③Hands | #512 (FRONT1) in review. Draft PRs for SBX-3a, 4a, 5a and 7 on SBX-1's builder (they stay unmerged until SBX-2 and SBX-M land). Then NAME1 and TITLE1 |
| ⑤CAP | SKF1, then UNI1a (the backend; UNI1b's notice needs a mock first), then SEC1 and MCPOUT1 |
| ⑥Helper | The final SB1-0 and WB1-0 mocks are sent, each with a "left for you to pick" bar. STY #452 rebases onto main. Then WB1-1 on main (web only) |
| ①iOS | Q1c is done: build 30 is on TestFlight (the user OK'd it on 2026-10-29). An independent review of its Bridge contract commit is running. The real-Mac end-to-end needs a 0.1.64 dev build on the user's Mac |
| Codex (via ⑦Codex) | SBX-2 #507 fixes |
| ⓪Plan | Reviews as PRs open; STATUS; the cut proposal (#515) |

## Waiting on the user

- **The v0.1.64 cut:** [CUT-proposal.md](CUT-proposal.md). Ship without the security chain's tail? It asks four questions. If the cut is adopted, follow-up: `settings_service.py:408-411`'s docstring (and any Settings or release-note wording) says ask_risky's judgement is completed in v0.1.64 (S2a-3). That would become v0.1.65 (④参谋).
- **Merges:** the "Ready" list above, in that order.
- **The STY read, once more:** the exported verdicts are from an earlier page (`3a107ed670ba`), and every row in them is empty: the export happened half a minute after that page was made. So the read hasn't been done yet. Re-read `sty-read-v0164.html` and export again. STY stays in draft until then.
- **Mocks, one sitting:**
  - SB1-0: the sections (match the iPhone, or add 30 days), a time on rows or headings only, and Pinned above or below Projects;
  - WB1-0: the tab name, "Working folder" or "Project folder".
- **SB1 raw material:** a read-only count of conversations by section. ⑥Helper's query was blocked, so the user runs it or allows it.
- **SBX-2 (#507):** relay the macOS failures and the plumbing findings to Codex; start the Astra review session; merge #508 into the Codex branch.
- **Real-Mac checks:** Quick Chat end to end with build 30 (needs a 0.1.64 dev build and pairing); FS1 (#451); the Hands smoke for F5b-2 (#456).
- **Release secrets into an Environment** (plan B for Codex), once the user has the originals of the updater's private key and the Apple certificate.
- **Making the `language` CI job required:** #504 merged with it red. That's a repository setting, so the user does it.
- **A session card from ②Main:** "Make the chat liveness tests load-tolerant" (②Main is doing it now).

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
| S2a-3 tests | "Read `docs/plans/0162/S2a-command-three-layers.md` (S2a-3) and the S2a-3 row of `docs/plans/0164/README.md` §3; write the test content named there for #375 / #376 / #378 / #396 and #406, against the rebased heads." | After SBX-7 and ③Hands' rebase | More decided on 2026-10-29 and 2026-10-30, all by the user:
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
- **FRONT1:** options A and B, in one PR (user, 2026-10-30, in ③Hands' chat). ③Hands is building it; it merges after #475.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
