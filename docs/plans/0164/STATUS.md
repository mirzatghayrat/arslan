# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-11-01 (UTC), afternoon. Five more PRs have merged since midday (#621, #632, #637, #623, #635). The user decided SBX-3a's D1 and D2 as recommended. The list below is for the user's return.

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
| #623 | CAP5c: a hand-added npx or uvx package is pinned to one exact version, or refused with why | `741a1154` |
| #637 | Judgments: each row names the run it belongs to (run_id, migration 0085) | `9d31b625` |
| #632 | Hands trace: each entry names the run it was made in (run_id) | `f492b722` |
| #621 | L11-3a: Overview's Remove works from the rules record (macOS count 421) | `537fdb77` |
| #635 | Docs: migration 0085 is judgments.run_id; next free is 0086 | `cd12973f` |
| #614 | INB5b-3: every waiting thing has a row that says why | `a1cffee9` (main CI 41292077511 success, covering the six below it too) |
| #612 | INB5b-3: the Scheduled page reads the server's count, and opening a task marks it seen | `9e1811bd` |
| #611 | INB5b-3: a stopped job's card waits out a scroll, and a held button looks held | `ac1ebcc2` |
| #610 | INB7-a: Progress leads with what waits on you, and the cost opens by model | `4372a98b` |
| #608 | UNI1b-4: a ZWNJ or ZWJ between two ASCII letters joins nothing, so it is marked | `35301b62` |
| #619 | SBX-3p (Codex): the commands' denial gates, 56 strict xfails (macOS count 420). Astra: merge, two non-blocking P3s queued for Codex | `a3d6abb8` |
| #605 | INB5b-2: the Inbox is gone; what waits on you is one number on Progress | `826b8920` |
| #617 | IMG1 card: Markdown images from the web | `cba1a243` |
| #616 | STATUS: morning list additions and the user's 11-01 decisions | `e94f338b` |
| #607 | UNI1b-3: the import scan blocks only Tag characters and bidi controls; whatever else shows nothing is counted | `11940e65` |
| #602 | INB5b-1: what waited in the Inbox comes back to its conversation | `ca10c0db` |
| #601 | INB7-1: a job a restart cut short says so when it happens | `431b1cc1` |
| #584 | CAP4a-3c: the one-click list (D) decides which Registry MCP entries get a card | `2ceabb40` |
| #618 | L11-3 card; K10 + L11 smoke steps | `19b55a22` |
| #563 | CAP4a-3a: the scan blocks "download and run" (a known limit: two parts unreviewed) | `6953a7c4` (main CI 41255177791 success, covering the morning batch) |
| #606 | CAP5b: each one-click install downloads into its own cache | `845feff8` |
| #452 | STY: warm but not fake in chat; four rules for task reports | `022b97aa` |
| #603 | L11-2: "make this a rule for this folder?" | `209e5381` |
| #590 | INB5a: one count of what waits on you (migration 0084) | `b4cdc0b4` |
| #597 | UNI1b-2: VS15/VS16 and IVS budget; the listing scans what the import scans | `f107f594` |
| #569 | CAP4a-3b: an MCP server's license is read at the installed version | `e40cae3a` |
| #565 | Hands: app names shown cleaned everywhere | `ce12502e` |
| #613 | STATUS: the morning merge list | `425396f1` |
| #609 | Tests: LOAD5, DIFF2's marker test survives a busy signer | `0595fb22` |
| #600 | Tests: INB4's retry test | `0de91cc8` |
| #599 | STATUS: the bedtime batch | `27639d13` |
| #591 | The user's 14:45 decisions; SBX-M ran; CAP5a's hand-added limit | `874cc159` |
| #594 | L11-1: a file's and a message's language have their own rule | `fe611fbc` |
| #595 | K10-1: a folder's rules (AGENTS.md, else CLAUDE.md) go into each turn | `71cc82f4` |
| #589 | INB4: "done, not seen" in the sidebar, the project row's most urgent state, the seen mark (migration 0083) | `2f43d0d8` |
| #585 | INB3: the Scheduled page, with a sidebar entry that carries a dot | `3206dfa0` |
| #588 | DIFF2-2 web: a repo folder's branch, PRs and files in Overview's Changes | `20c143cc` |
| #587 | DIFF2-1 server: Changes for a working folder that is a git repo | `61bc615f` |
| #586 | UNI1b: hidden characters in a skill's text are always marked; the save card and the import panel count them | `a2e38bfe` |
| #577 | CAP5a: an installed connection is pinned to its first test's tools; a change stops it until the user accepts | `aa1d4f32` |
| #582 | JUDGE1 clean: at boot, drop ledger rows that hold memory text from before digests | `9af258f6` |
| #560 | Tests: MEM1's fail-safe through the real judge | `d4b287c4` |
| #598 | SBX-2 (Codex): check network allow shapes and TCP deny order. Astra (high) and Claude (effort=max) reviewed | `baabe4ea` |
| #596 | Migration 0084 to INB5a; next free is 0085 | `ad610bc7` |
| #592 | SBX-M report: the SBX-2 corpus on the user's Mac | `71f79c3d` |
| #593 | Tests: the sbx_mac corpus is opt-in for a local run; CI's macOS step unchanged | `ce12f08a` |
| #579 | Migration 0083 to INB4; next free was 0084 | `f5470042` (main CI 41211934156 success, covering #574 … #579) |
| #580 | DIFF1 web: a turn's change opens side by side from Overview's Changes | `7c8bf7c4` |
| #450 | C7c-2: migration 0073 drops router_decisions | `313707bb` |
| #581 | INB6: a scheduled fire keeps its run, a read keeps its paths, diagnosis counts host runs | `ee961611` |
| #557 | EXC1b: every silent broad except that returns or continues says why | `a0874c7f` |
| #548 | TITLE1: the model's approval texts name the step by a model title | `507c99ed` |
| #559 | MEM1: memory write hygiene | `ca8583e8` |
| #561 | CAP4a-2: an MCP server's lock is resolved before the card, and a yes installs exactly that lock | `3c8a40fe` |
| #574 | SBX-2 (Codex): preserve TCP allow pairs and reject port-22 exclusions | `9c57ea5f` |
| #583 | DIFF2 card | `ef6283b2` |
| #578 | The user's 10-31 decisions: DIFF1/DIFF2 picks, allowlist D, UNI1b B, JUDGE1 clean | `c26af15c` (main CI 41203188734 success, the first full run since #570) |
| #575 | SBX-M runbook | `300e391e` |
| #573 | K10 + L11 card: folder rules (`AGENTS.md`) and where the output's language comes from | `0a61369f` |
| #571 | This page: tonight's merge order; lanes restarted | `2876f11a` (main CI 41200897587 covers everything from `dc926523` on; the runs on `dc926523`…`0a61369f` were cancelled by the next merge) |
| #555 | EXC1a: every silent broad `except: pass` says why on its line, and a test keeps it so | `53c68977` (main CI 41199089324 queued when this was written; the four runs before it were cancelled by the next merge) |
| #567 | JUDGE1: stored lessons reach the judge only where memory may be shown; the judge keeps digests | `318d0b02` |
| #553 | DIFF1 server: one changed path of a turn as a line diff | `dbbb9a81` |
| #526 | UNI1a: one cleaner for names; skill bodies keep ordinary text; bidi controls shown escaped (migration 0082) | `e3cef4a1` |
| #570 | SBX-2 fix (Codex): the any-declared mode refuses port exclusions. Astra (high) and Claude (effort=max) reviewed | `dc926523` |
| #572 | SMOKE.md: SB1's real-Mac steps | `f97b0f1b` |
| #566 | This page: INB questions, INB3 mock, the next queue | `06b2c785` |
| #545 | WB1-3: Overview's Changes, what each turn did in your folders, with its undo | `6180d52c` |
| #554 | Hands: the access card's heading is Arslan's words; the model's why is its own line | `98879c65` |
| #568 | INB3 server half: what could not be asked, per conversation | `6087ed1c` |
| #519 | SKF1: every skill the user has reads unframed (D2), in one place | `a2bb4a25` |
| #539 | CAP4a-1: a skill's card shows what was fetched, scanned and hashed at one commit | `be31eb43` |
| #536 | SEC1 server half: a secret in a connection's address or arguments can move to an encrypted store (migration 0081) | `c0dd6a7c` |
| #547 | NAME1: provider-safe tool names | `a8edd8eb` |
| #542 | ci.yml: a strict xfail counts as ran; every xfail pins `raises=` | `e6895710` |
| #537 | LOAD2 part 2: a stdio program that exits early is a closed connection | `f966a8e7` |
| #552 | LOAD4 card; this page | `bc2d814b` |
| #551 | Tests: LOAD4, four waits a loaded machine overran | `8e112bf7` |
| #550 | SB1-2: pin and drag in the sidebar (migration 0079) | `b7fdbc78` |
| #549 | SBX card: the listening sources read; one more SBX-M measurement | `56712874` |
| #546 | This page: #519 merges after #539's scan fixes | `a98ad04a` |
| #543 | SB1-1: newest first under the iPhone's date sections; collapse with ⌃⌘S | `f1bc0beb` |
| #544 | This page, late night | `da4cc46d` |
| #541 | Tests: LOAD3, the budget credit after a card is guarded; three load flakes fixed | `9506dc23` |
| #540 | The user's decisions D1–D3 on capabilities; this page, night | `ee9b7b54` |
| #507 | SBX-2 (Codex): the default-deny preset and the macOS corpus, staged and not wired. Astra's two reviews are posted; ⓪Plan's plumbing re-OK at `8751d6f7` is posted, and what landed is exactly that commit | `aace2b11` (main CI 41031727159 success) |
| #528 | LOAD2 and LOAD3 cards; this page, late evening | `f2b2038a` |
| #512 | FRONT1: when the model may ask Hands for the front (A), and an honest needs-focus refusal (B, corrected) | `b19d4dbb` |
| #490 | Q1 #3: a quick question turned into a chat learns from then on (migration 0078) | `7b6ebea1` |
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

## Ready for the user to merge (in this order)

Every PR below is OK'd at the head shown, with the verdict posted on the PR. A PR stacked on another is retargeted to main by its lane once the one below it lands, then re-checked at the new head. A draft needs **Ready for review** clicked first, whenever the lane's own ready step was blocked.

1. **#628** at `00873a42` (a draft, CI green; click Ready first): SEC1 follow-up, a credential in a `--name=value` option.
2. **#630** at `783f7b4a` (INB follow-ups from the #611 and #605 reviews) and **#615** at `f8bf4a8f` (set-aside reminders). Both are on main now, and the re-check found their diffs identical. #630 is green; #615's macOS job was still running at this update.
3. **#626** (L11-3d): #621 has landed, so ⑥Helper is retargeting it to main and merging main in. It goes back on this list once ⓪Plan has re-checked the new head and CI is green. It's a draft, so click Ready.
4. **The INB7 chain, in this order:** #622 `8f496450` → #624 `a69094f0` → #627 `3d7ab9a4` → #629 `07ce3a98` → #631 `2b21e843` → #633 `02da15c4` → #634 `15767a0e` → #636 `91c9304b`.
   - #622 is on main, with green CI. Each of the others is stacked on the one before it, and its diff was re-checked identical at the head shown.
   - As each lands, ②Main retargets the next one to main and merges main in. ⓪Plan re-checks it, and then it needs CI.
   - **#634:** #637 has landed, so ②Main is switching the 「诊断」 judgments from by-time to by-run_id. ⓪Plan delta-checks that change, so #634's head will move from the one shown.
   - **#636** waits on your call about the full lists (see below).

**Not ready yet:**
- **#604** (CAP4a-3d) at `be2cf748`: re-checked OK, with KEEP_FOR gone and F3 a stated limit. It waits for the web keep button, whose mock needs your OK first.
- **#625** (CAP4a-3c follow-up): it conflicts with main since #623 landed, because both change the CAP install code. ⑤CAP merges main in, and then ⓪Plan re-checks it. If the classifier stops the push, it waits for your OK in ⑤CAP's session.

**Under review or on hold (don't merge these):**

- **#525** (Q1 #4, retire the pocket): a draft until Q1c ships and you say go. It now conflicts with main; ②Main merges main in when it's time.
- **#520** (SBX-3a, ③Hands) at `de71df02`, a draft: main is merged in, and #619's file keeps its path while 3a's is renamed. The counts are 422 and EXPECTED_XFAIL 56 (423 if #621 lands first).
  - **The flip onto the default-deny base is blocked.** ③Hands measured it on macOS 26.6.2: the current preset passes 20 of #619's 56 cases.
  - Gates 1 and 3 are decided (D1 and D2, below). Two gates are still open, both queued for Codex: 2, the mach allowlist (`SYSTEM_MACH_SERVICES = ()` at `server/services/sandbox_profile.py:117`) plus the DNS entry, and 4, multiprocessing's `/mp-` names.
  - The flip, the BUILT_BASES line and EXPECTED_XFAIL → 0 go in one commit, and the effort=max review waits for that commit.
- **#531, #535, #538** (SBX-4a, 5a, 7): drafts. They pick up 3a after the flip, so the carry happens once.

**Who merges (#467):** sessions auto-merge docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface, after another session's OK on the current head and green checks. The user merges the security surface and ordinary product code. For SB1 and WB1, the user's approval also lets the author auto-merge.

## In progress

| Lane | Work |
|---|---|
| ②Main | #634's by-run_id switch (#637 has landed); retargets the INB7 chain as each parent lands |
| ③Hands | Marks D1 and D2 decided in #520's body; then idle until Codex's gates 2 and 4 are done |
| ⑤CAP | Merges main into #625; #604 waits on the keep mock |
| ⑥Helper | #626's retarget to main; the L11-3b mock |
| Codex (via ⑦Codex) | Queued: SBX-3a gate 2 first (the mach allowlist and the DNS entry, which gives online commands their network back), then gate 4; #619's two Astra P3s |
| ④参谋 | Main CI and the user's return list |
| ⓪Plan | Re-checks as heads move; this page |

## Waiting on the user

- **#636's full lists:** (b) keep the Hands trace in Settings › Hands, and (a) drop the judgments list. Both recommended.
- **The drawer:** drop the radar and the sparkline (recommended).
- **The 「要你做」 label:** the chip and the tile now share it, with a title. It's kept unless you say otherwise.
- **CAP9's mock**, sent as a private link.

- **IMG1's scope** (#617): A, web images as a chip that opens in the browser (recommended); B, a CSP on the main window; C, a CSP in the reader's HTML and Word frames. Recommended: A + C now, B after A is on a real Mac.
- **#604's keep button:** the mock (the parked row plus 「keep it」, on CAP5a's board) needs your OK before ⑤CAP builds it.
- **L11-3b's mock** (Memory's lesson rows show the rule state), once ⑥Helper sends it. The extra, "also remove it from AGENTS.md", is recommended no.
- **③Hands' session effort:** switch it to high, per the pacing rule (②Main is switched).

- **SEC1 mock** (⑤CAP), sent as a private link.
- **A probe-rule slip in ⑤CAP's session (reported by ⑤CAP itself):** while editing #526, one bare `python -c "import server.services…"` ran outside probe.sh/pytest, without a scratch HOME. ⑤CAP says it opened no file on purpose. The rule exists because of #409 (a real-HOME import read the real key file). Whether anything more is needed, for example rotating a key, is your call; ⑤CAP notes the command in #526's PR body.
- **(Done: the load flakes below are LOAD4, #551.)** Earlier note: `test_mcp_discovery_v2.py:256` (two servers' writes didn't overlap under load) and `test_inb2_presence_entry_points.py:80` [phone-chat-send] (presence read before it was written). A third is `test_chat_liveness_0159.py:146` (`test_a_message_sent_right_after_the_answer_is_not_queued`): it starts a 4 s `threading.Timer` fallback before the first turn, so a slow pair of turns under load lets the fallback fire first (②Main; not the test #521 fixed). Not a decision; listed so they aren't lost.
- **SBX-2's any-declared network mode can't hold a port deny (explained; recorded on #507):** on macOS 26.6.2 the profile compiler drops a `localhost:<port>` deny for about 7.8% of ports when `*:*` is also allowed, and an IPv4-mapped connect passes it at every port. Proxy and port-22 modes hold. **Released v0.1.63 isn't affected:** no shipped profile denies a TCP port, and every path-based network deny was checked by bytecode diff and a runtime connect (#507, with file:line). SBX-2 isn't wired, so nobody is exposed. Codex's fail-closed fix is merged (#570, `dc926523`: any-declared refuses `denied_ports`), and its follow-up is #574 with #576. **Your call:** whether any-declared stays a mode at all, together with the listening decision. Also from it: Seatbelt's `localhost` matches the Mac's LAN IP.
- **An SBX-2 deny that let a connection through once (③Hands, on macOS 26.6.2; since #570 the any-declared case is a build-time refusal, and the SBX-M loop measures the proxy and port-22 cases):** `test_sbx2_kernel.py::test_listener_refusal_and_arslan_port_exclusion[any-declared-default-deny]` connected to a denied port (errno 0) once in a 14-minute run, and passed 4 of 4 alone. It goes into SBX-M as a repeat loop (hundreds of runs, each errno recorded, and a check that the connecting process was the sandboxed one). What follows is your call once that's measured.
- **Real-Mac checks:** Quick Chat end to end with build 30 (needs a 0.1.64 dev build and pairing); FS1 (#451); the Hands smoke for F5b-2 (#456).
- **Release secrets into an Environment** (plan B for Codex), once the user has the originals of the updater's private key and the Apple certificate.

**Decided on 2026-10-29:** the classifier pass lines are complete (≥ 70% of the approvable scope answered; ≤ 5% failure fallback), and C7c Q1–Q4 are answered (experts become skills automatically in the migration; private knowledge goes to the general base with a label; the v1 views and `/brain/proposals*` go in v0.1.65; `list_spawns` is removed now). Recorded in #474. Also decided on 2026-10-29: INB2 F2 is an allowlist and F4 is an optional stricter-only `sensitive: true`; the Bridge passes the envelope `ts` as `sent_at`; a converted quick ask learns from the conversion on; the pocket goes in v0.1.64 if Q1c ships with it, else v0.1.65 (recorded in #482). The pocket's old messages stay as a Mac-only conversation (#487). The sidebar card SB1 is in v0.1.64, and projects double as groups in v0.1.65 (this PR).

## Codex to write (user, 2026-10-29)

**Why:** a safety classifier stopped ③Hands as it started SBX-2. The user had the cloud audit split SBX and S2a-3, and approved the split. What Claude cannot write goes to Codex (SBX card, "Who writes what"). Reviews: Astra (highest level) in a new Codex session, never the session that wrote it. Claude reviews the non-probe plumbing. The existing review queue is in [`docs/plans/0162/STATUS.md`](../0162/STATUS.md), "Codex 待审".

**Where the chain is (2026-10-30, night):** SBX-2 is merged (#507, `aace2b11`); next is SBX-M on the user's Mac. Before that it was stuck at SBX-2 (Codex). HR, CLS, S5a and S5b wait on it; see README §4, "Reordered 2026-10-29". ③Hands does other owed work meanwhile. Its local SBX-2 branch stays untouched.

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

**Decided on 2026-11-01 (user, relayed by ④参谋).** The user's words: 「D1、D2 按推荐」. Both are the recommended options in [#520's "Decisions for the user, before the flip"](https://github.com/mirzatghayrat/arslan/pull/520#decisions-for-the-user-before-the-flip), recorded in [SBX-sandbox.md](SBX-sandbox.md), §3:
- **D1, listening:** SBX-3a flips with listening still denied. This keeps the 10-30 decision and adds no code. How listening comes back is decided in NET, either a per-run listen card or a Network Extension filter.
- **D2, online-mode commands until SBX-6:** offline until Codex's DNS entry (gate 2) exists, then any-declared. Outbound TCP behaves as in v0.1.63, and UDP is denied. The gap it keeps, Arslan's ports over loopback, is v0.1.63's, and SBX-6 closes it. #619's commands mode list also needs any-declared.

**Decided on 2026-10-30 (user, relayed by ④参谋):**
- **Deletable scope:** skills Arslan wrote (`authored` and `authored-outside`) and connections the user added by hand may be deleted, as #499 and #500 built them. Built-in and seeded items stay non-deletable (409). The deleted skill's text goes to the Trash.
- **The long-term approach over minimal patches:** cards SKF1, UNI1 and SEC1 (README §3.12).
- **FRONT1:** options A and B, in one PR (user, 2026-10-30, in ③Hands' chat). It is #512: OK from the security side at `7dd5eade`, with a small window-title fix to land before the user merges.

**Decided on 2026-10-30, night (user, relayed by ④参谋).** The user's words: 「1. 接受建议改成 a；2.（1）现在就跟你说 直接按主流做法： Claude Code 和 Codex 对装过的技能一律信任，读的时候不加框。（2）也按主流做法；3.也按主流做法」 and 「SB1 侧栏、STY 盲读 都可以 刚看了demo」. Recorded in full in [CAP-capabilities.md](CAP-capabilities.md), "Decided on 2026-10-30", and [CAPX-followups.md](CAPX-followups.md).
- **D1, CAP4a-2: option (a).** Arslan's own pinned, checksummed uv and Node runtime makes the lock before the card; one card shows the locked versions.
- **D2, skills follow mainstream practice:** every skill the user has is trusted and read unframed, as in Claude Code and Codex. Origin marks stay as data for deletion and display. Skills of unknown origin are deletable. #519 is reworked to match; 0077's `authored` skip is moot. Stated limit: the same trust model as MCP descriptions from approved servers; the guard is at install time.
- **D3:** UNI1b is a notice only, never blocking. SEC1's move is an optional offer that never blocks a connection; #536's storage (`${NAME}` plus the encrypted column) stays.
- **SB1-0:** the user is fine with either option on all three toggles, so ⑥Helper chose: the iPhone's sections (Today / Yesterday / Previous 7 days / Older, with Older folded by month and a count per month, by the iPhone's own `ConversationGroups.make` rules), time in the headings only, and Pinned above Projects. Recorded in #543.
- **STY:** the user has no preference between the two sides of the read, so the read no longer blocks #452. The card's bench gate is unchanged.

**Not adopted (user, 2026-10-30):** the v0.1.64 cut (#515). The user's words: 「现在没有按"截断方案"吧，我不太想一直有任务推到后面只为了快上线新版本 我只是想要合理推进 不要老是原地踏步」. The scope stays as planned. What the user wants is steady, visible progress: every lane busy on its next card, reviews in parallel, no PR left idle on a sync or a review, and Codex's next SBX block queued as soon as the previous one lands. Progress is reported as PRs merged per round and what moved on the critical path.

**Decided on 2026-10-31, about 12:40 UTC (user, relayed by ④参谋).** The user's words: 「全按推荐，DIFF1 用左右对照，白名单选 D，UNI1b 草图推荐选 B（我还是那个要求 借鉴主流agent产品做法，不要过度防御）」. In full in [CAP-capabilities.md](CAP-capabilities.md), "Decided on 2026-10-31".
- **DIFF1-0:** a side-by-side diff; created and deleted files open, as the mock recommended. The web half goes ahead (⑥Helper).
- **DIFF2-0:** the diff covers everything since the branch left main, as Claude's does; a PR opens in the workbench's Browser tab; the PR row shows its checks (⑥Helper).
- **CAP4a-3:** allowlist D. Packages from any verified domain are one-click (the lock, the scan and the sandbox still apply); remote servers only from B's vendor list. A remote whose publisher has no verified domain is manual-only. The Registry re-check runs once a day per server and on the first start after an update.
- **CAP4a-2:** the runtimes are fetched on first need, not shipped in the app.
- **JUDGE1:** a one-time clean at boot of the judge-ledger rows from before JUDGE1 that hold stored lesson text (⑥Helper; it deletes data, so an independent effort=max review, and the user merges).
- **INB2 and skills:** kept as is. After a skill read, "about you" memories wait for the user. A stated limit.
- **UNI1b:** option B of ⑤CAP's mock.
- **The standing rule, repeated:** follow mainstream agent products, and don't over-defend (`docs/sessions.md` §12).

**Decided on 2026-10-31, about 14:45 UTC (user, relayed by ④参谋).** The user's words: 「都按推荐」, after the four items that were "to confirm".
- **The INB card's questions 1–11:** as the card recommends. For the two that had no card recommendation:
  - Q3: during Do Not Disturb or Focus, approval cards don't pop. They wait in the conversation and the badge still shows, as Claude's and Codex's desktop notifications follow Focus.
  - Q4: only a "family" category is added for now.
- **K10 + L11, D1–D5 (#573):** as recommended.
  - The classifier doesn't see folder rules.
  - "Make this a rule" writes the folder's `AGENTS.md`.
  - Folder rules count as outside content, except a file exactly as the user added it.
  - There is no global file.
  - A file's language defaults to the user's message.
- **The `sbx_mac` corpus:** opt-in for local full-suite runs. CI's macOS job is unchanged (③Hands).
- **Skills from before CAP4's checks:** left as they are, with no one-time rescan. This is now the user's decision.

**SBX-M ran on 2026-10-31** (the user, at main `ef6283b2`, macOS 26.6.2 25G83).
- The corpus: 293 cases, 293 passed; 101 rows need a look.
- The listener loop: 30/30 in each mode.
- The report is `SBX-measurement.md` (#592, `71f79c3d`).
- The two boundary-open rows (the hard-link measurement on today's shipped bases) are a probe artifact, not a shipped gap; no point release (the effort=max assessment, #592 comment 6545067946). The probe fix is in Codex's SBX-3p paste.

**Decided on 2026-10-31, about 17:45 UTC (user, relayed by ④参谋).** The user's words: 「1 允许，2B，3A，4 都按推荐，5 允许」.
1. **The #584 and #563 pushes:** allowed. ⑤CAP pushes them in its own session; no other session pushes for it.
2. **INB7:** **B**: all of it goes into v0.1.64, the map and the timeline replay included (②Main). The plan is the newest board, F ("fused", version 11 of ②Main's canvas). That board came after C+, when the user asked to fuse it with today's Activity.
   - Usage's tiles are on top, with 「要你做」 as the first tile. One time axis carries a runs lane and replay. 「最近的工作」 is the only list. The map follows. An inspector holds 「要你做」, 「回放」, 「改动」 and 「诊断」.
   - PRs: a, the rename, the tiles and the per-model cost; b, the axis; c, the list and the inspector; d, the map; e, removing the morning brief; f, the read-only progress tool.
   - **Decided after (user, relayed by ④参谋: 「并进去」):** the Hands, judgment, scheduled-task and per-model cards fold into the page. The duration heatmap shows only for 7 and 30 days.
3. **The import scan:** **A**. The rule that blocks an import blocks only Tag characters and bidi overrides. Every other hidden character is counted and marked, not blocked, as GitHub's warning does. This is a new small PR on the security surface (⑤CAP).
4. **L11-0:** both picks as recommended. The rules show as an Overview row, and the card has two buttons, Add and Not now. L11-2 can be built now (⑥Helper).
5. **The SB1 count:** allowed. The classifier still stopped the relayed OK, so the user allowed it in ⑥Helper's session directly, and it ran read-only, counts only.
   - 50 conversations, 5 of them in a project.
   - By section: Today 0, Yesterday 2, Previous 7 days 20, Older 28 (one month group).
   - So Older needs no "show more" today. Pinned can't be read yet, since the installed database predates 0079.

**Decided on 2026-11-01, morning (user, relayed by ④参谋).** The user's words: 「1A，2 已知限制，3 去掉，额度按你的建议」.
1. **#563:** accept the gap. The 40-character window and the interpreter pattern weren't reviewed (classifier blocks). The scan is a heuristic, so this is a known limit, with no Astra paste. #563 goes to Ready and merge.
2. **#604 F3, cross-host redirects for remote MCP:** a stated limit, as mainstream clients have it. #604's body and #584's text are aligned, so neither says the other handles it. Recorded in [CAP-capabilities.md](CAP-capabilities.md), "Stated limits recorded on 2026-11-01".
3. **#604 KEEP_FOR:** removed. A keep holds until the entry changes again, with no 30-day expiry. ⑤CAP drops it and its card line; ⓪Plan re-checks.
4. **Quota pacing** (the weekly quota went from 7% to 35% overnight):
   - effort=max only for security-surface reviews;
   - all other reviews and lane work at high;
   - only lanes with unblocked work stay active.

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
