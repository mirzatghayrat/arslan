# v0.1.64 status (one page)

Kept by ⓪Plan; updated after each merge. The plan and cards are in [README](README.md). The v0.1.63 page is [`docs/plans/0162/STATUS.md`](../0162/STATUS.md); its "Codex 待审" section (which Codex model, the prompt to paste, the queue) still applies.

**Updated:** 2026-10-30, late night (after the CAP rechecks).

## Merged for v0.1.64 (newest first)

| PR | What | Merge commit |
|---|---|---|
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

## Ready for the user to merge

Only PRs with an independent effort=max OK **at the current head** and green CI are listed here. All of them are on the security surface, so the user merges each one.

The user is out; these wait for their return.

In any order unless noted. Every verdict below is posted on its PR with the sha.

1. **#537** (LOAD2 part 2) at `4352ee1b`: ⑤CAP's OK, CI green. Product code.
2. **#542** (ci.yml: a strict xfail counts as ran; every xfail pins `raises=`) at `8e67f6b6`: ③Hands' effort=max OK, CI green. Touches `.github`; before SBX-3p's first push.
3. **#547** (NAME1: provider-safe tool names) at `0b59f0be`: ⓪Plan's effort=max OK, re-OKs through `0b59f0be`; CI green (its macOS job re-ran after the SBX-2 finding below, which is unrelated).
4. **#548** (TITLE1) at `97627182`: ⓪Plan's effort=max OK, re-OK at this head.
5. **#526** (UNI1a, migration 0082) at `e2f155b6`: ⓪Plan's effort=max recheck OK, CI green. **#526 and #548 together:** they merge cleanly, but `test_title1_model_title.py:85` then fails; the second to merge updates it (③Hands or ⑤CAP).
6. **#536** (SEC1, server half, migration 0081) at `dfdd1e5a`: ⓪Plan's effort=max recheck OK, CI green.
7. **#545** (WB1-3: Overview's Changes) at `1ca9f05e`: ②Main's endpoint OK; ④参谋's web review "merge" at this head; CI green.
8. **#553** (DIFF1 server half: the line-diff endpoint) at `85135033`: ②Main's effort=max re-review OK. Stacked on #545, so after it.
9. **#555** (EXC1a: silent broad `pass` handlers get a reason or a log) at `d984b12d`: ②Main's OK. It touches hot files by a line or two; it merges after #547, #519, #452 and #375, or ⑥Helper rebases it.
10. **#519** (SKF1 for D2) at `0de987d2`: ⓪Plan's effort=max OK after three rechecks. **Only after #539's F1/F3/F4 are on main.**

**Under review or on hold (don't merge these):**

- **#519** (SKF1, reworked for D2) at `b8ef5881`: changes requested (posted). The code matches D2, but the skill install card still tells the user a skill is "Read like a web page"; under D2 that card is the guard, so it must say Arslan follows the skill's text. Two test gaps close two surviving mutants. **Merge order (④参谋's review of #539, adopted):** under D2 install time is the only guard for skills, so #519 merges only after #539's F1 (the scan level is computed after findings are cut to 20), F3 (the import panel installs with no scan; in #539 or a small CAP5 import-scan PR) and F4 (the frontmatter name and description aren't scanned) are on main. This doesn't change D2; it makes the install-time guard real before the read-time frame comes off.
- **#539** (CAP4a-1): F1–F9 fixed at `98f52a42`; ④参谋's recheck is "fix then merge (small)": F4's decoded frontmatter wasn't scanned, and the scan call sites had no tests. ⑤CAP has the fixes committed and is running the full suite.
- **#554** (Hands' DesktopAccess card: a fixed heading; the model's `why` on its own line) at `f0d7f6ff`: ⓪Plan's effort=max review is running. The card's heading text changes; the before and after are at the top of the PR body.
- **#525** (Q1 #4, retire the pocket): ②Main fixed F1–F4 in `71dbc0ce`; its full suite is running, then ⓪Plan's reviewer takes a glance. It also waits on the user's go after Q1c ships.
- **#527** (MCPOUT1): stacked on #519; ⑤CAP looks at what's left after D2.
- **#520, #531, #535, #538** (SBX-3a, 4a, 5a, 7, ③Hands): drafts, rebasing onto SBX-2; they don't merge before SBX-M. #538's early read is posted (the tripwire is text-only; approving a re-run erases the denial); ③Hands takes it after the rebases. 3a is rebased at `c596ed3d`. The wiring onto the default-deny base waits for SBX-M and the listening decision (card :255).

**Who merges (#467):** sessions auto-merge docs, plan cards, bench scripts, tests and deletion-only PRs outside the security surface, after another session's OK on the current head and green checks. The user merges the security surface and ordinary product code. For SB1 and WB1, the user's approval also lets the author auto-merge.

## In progress

| Lane | Work |
|---|---|
| ②Main | #525 after F1–F4 (pocket retirement); C7c-2 #450 |
| ③Hands | The four SBX drafts are on 3a and SBX-2 (3a `c596ed3d`, 4a `1e9dba8d`, 5a `d5853f85`, 7 `654ea062`, with #538's follow-ups in). DesktopAccess is #554. Next: whatever the port-deny investigation needs |
| ⑤CAP | #539's last two fixes; CAP4a-2 (option a) is built, and its PR opens after the full suite; CAP4a-3 (license at the version's commit, start-time source checks, the "download and run" scan rule, allowlist settings) next; MCPOUT1's small follow-up after #519 |
| ⑥Helper | DIFF1's server half is #553; its web half waits for the user's mock picks. EXC1a is #555; EXC1b (the `return`/`continue` handlers) is next, stacked on it. STY waits on its bench (below) |
| ①iOS | Q1c done (build 30 on TestFlight). After #525 merges, it copies the 42-example `messages.json` again |
| Codex (via ⑦Codex) | SBX-2 merged. SBX-3p waits on SBX-M, then the paste |
| ④参谋 | #539 reviewed (fix then merge) |
| ⓪Plan | #554's review; the SBX-2 port-deny investigation; this page |

## Waiting on the user

- **UNI1b and SEC1 mocks** (⑤CAP), sent as private links. UNI1b's mock also shows the markers for invisible characters on the save card (#526's review).
- **Skills from before CAP4's checks (D2's remaining half, ②Main's review of #540):** the old Discover page's `gh-` skills, Skill Forge's promoted ones and `create_skill` output written from outside text never passed an install card, a scan or a pinned sha, and under D2 they read unframed. Re-check them once (a one-time scan, or a prompt to review them in Capabilities), or leave them as they are? They keep their origin mark and can be deleted.
- **STY's bench (blocked by the classifier in ⑥Helper's session, "Create Unsafe Agents"; not routed to another session):** the 27-task K5-style run before and after STY, on DeepSeek through the proxy, about $4–5 (the proxy is at about $8 of $20). Two checkouts are ready in ⑥Helper's worktrees, before at `e8580458` and after at `4c20bb11`. Run it yourself, or allow ⑥Helper to run it. ⑥Helper has the command. #452 stays a draft until then.
- **A probe-rule slip in ⑤CAP's session (reported by ⑤CAP itself):** while editing #526, one bare `python -c "import server.services…"` ran outside probe.sh/pytest, without a scratch HOME. ⑤CAP says it opened no file on purpose. The rule exists because of #409 (a real-HOME import read the real key file). Whether anything more is needed, for example rotating a key, is your call; ⑤CAP notes the command in #526's PR body.
- **(Done: the load flakes below are LOAD4, #551.)** Earlier note: `test_mcp_discovery_v2.py:256` (two servers' writes didn't overlap under load) and `test_inb2_presence_entry_points.py:80` [phone-chat-send] (presence read before it was written). A third is `test_chat_liveness_0159.py:146` (`test_a_message_sent_right_after_the_answer_is_not_queued`): it starts a 4 s `threading.Timer` fallback before the first turn, so a slow pair of turns under load lets the fallback fire first (②Main; not the test #521 fixed). Not a decision; listed so they aren't lost.
- **SBX-2: a declared port deny let a connection through, now twice** (③Hands' Mac; GitHub's macOS runner, run 41043463120). Recorded on #507. SBX-2 isn't wired to anything, so users aren't exposed, and no SBX PR wires the base in until it's explained. A lead from sandbox-runtime's source: Seatbelt's `localhost` doesn't match an IPv4-mapped address, so in the any-declared mode a mapped connect could miss the deny and hit the `*:*` allow. ⓪Plan's effort=max investigation is testing that. SBX-M repeats it on your Mac.
- **CAP4a-2: ship the runtimes in the app, or fetch them on first need (⑤CAP):** shipping adds about 70 MB, and the lock still needs the network, so offline gains little. Fetching relies on the SHA-256 pinned in the repo; shipping is covered by Arslan's signature and notarization. Both need a release to move the pin. Recommended: keep fetching. Nothing waits on it.
- **DIFF1-0 mock (⑥Helper):** two picks: a unified or side-by-side diff, and whether files that were made or deleted also open. The web half waits on these.
- **UNI1b mock:** ⑤CAP's mock shows the invisible-character markers on the save card. Option B is recommended. Pick one, or ask for changes.
- **INB2 and skills under D2 (from #519's review):** INB2's allowlist (`untrusted.py:168`) still counts a skill read as "off the list", so after reading a skill, "about you" memories wait for the user instead of taking effect. D2 covered reading, not memory. Recommended: keep it as is, since memory writes are the stricter surface, and record it as a stated limit. The alternative is to treat a skill read as clean, like D2.
- **An SBX-2 deny that let a connection through once (③Hands, on macOS 26.6.2):** `test_sbx2_kernel.py::test_listener_refusal_and_arslan_port_exclusion[any-declared-default-deny]` connected to a denied port (errno 0) once in a 14-minute run, and passed 4 of 4 alone. It goes into SBX-M as a repeat loop (hundreds of runs, each errno recorded, and a check that the connecting process was the sandboxed one). What follows is your call once that's measured.
- **SB1 raw material:** a read-only count of conversations by section. ⑥Helper's query was blocked, so the user runs it or allows it.
- **SBX-M on your Mac:** SBX-2 is on main (`aace2b11`). SBX-M measures it on your Mac, then ⑦Codex's SBX-3p paste is ready.
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

## Spend

- M64 baseline round `r64-m64-base`: about $1.71 at DeepSeek peak prices.
- STY read test `sty1-ds`: two rounds of 20 prompts, small (within the proxy caps).
- DeepSeek proxy total since its last start: about $8.0 of its $20 cap.
