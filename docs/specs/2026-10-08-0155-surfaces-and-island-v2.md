# 0.1.55 — One surface kit for everything that interrupts, Island v2, and four small fixes

Status: spec, for review. Renumbered 2026-10-08: 0.1.54 is the security/Bridge batch already on main (#111–#118);
this is 0.1.55. Then 0.1.56 = output rules, the folded work timeline, the reading panel; 0.1.57 = the right-hand
workbench and clickable paths (task book `Arslan-输出与交付面-任务书-2026-10-04.md` §3–§8). Mock: https://claude.ai/artifact/Y7bbsGqK21DxeX2h3BrzH3 (the user approved its look,
2026-10-05, and widened the scope on 2026-10-06 to "every pop-up inside Arslan").
Inventory: 2026-10-06, four angles (components, i18n keys, backend card frames, native shell), file:line facts
in §9.

## 0. What is wrong today (measured, not taste)

- **Six approval cards, five looks of buttons.** Run/Cancel, Allow/Don't allow, Allow/Not now, Remember it/Not
  now, Connect/Cancel; the decline button is ghost in three and unstyled in two; every button is monospace,
  bold, 11 px, UPPERCASE (`index.css:2080-2090`) on an orange fill.
- **Cards overlap.** All six render in the same absolute slot (`App.tsx:708-822`, `index.css:1342`); two pending
  at once sit on top of each other. The slot is still named after a removed component (`suggest-create-card`).
- **A card cannot be answered where you are.** The island only says "Open to approve"; over a full-screen app
  the island is not shown at all (I1 open item).
- **Six ways to confirm a delete**, two of them the native `window.confirm` the code itself says not to use
  (`NoteEditor.tsx:290`, `RunReplay.tsx:153`); seven destructive actions confirm nothing (provider Delete,
  Reset token, Forget key, SSH Forget, phone Remove, practice Delete, saved candidate Delete).
- **Seven modal implementations** (z-index 20…150, one without `role=dialog`), **three toast systems**, about
  sixty one-off inline alert lines.
- **Five UIs for memory/learning proposals.**
- Orphans: four card frames the store handles and nothing renders (`suggest_create`, `suggest_update`,
  `propose_invite`, `propose_staffing`), their CSS, and five classes used with no CSS.
- Hard-coded English in `ScheduleGrantCard` (`humanCadence`), raw `amber-500` in `TaskPanel.tsx:176`.

## 1. Look (both themes)

Arslan's default is **light**; every surface follows the app's theme and palette. The mock's dark boards are
the dark theme; light boards are added to the mock before building.

- Ground: `--surface` panels on a dimmed backdrop; radius 16 (cards, dialogs), 10 (inner boxes, buttons),
  capsules for chips; one hairline border; one soft shadow. No left-border cards, no gradient washes.
- Type: the system sans for everything a person reads; **monospace only for code, paths, commands and
  numbers** (timers, counts, sizes). No uppercase labels.
- Colour carries meaning, never decoration:
  - amber = something waits for you (the asking header, the countdown, the island "needs you");
  - red = destroys or stops (destructive confirm, Stop);
  - blue = working (progress ring, the mascot's signals);
  - green = done; yellow = not done (existing `--unfinished`).
  The palette's `--primary` (orange by default) stays for brand accents, **not** for buttons.
- Buttons: primary = label colour (black on light, white on dark), secondary = neutral fill, destructive = red
  text on a faint red fill. Keyboard hint chips inside buttons.
- The mascot keeps the Island rule (2026-10-03): the head never moves; the mouth constellation and the halo show
  state; no badges on the head, no sounds.

## 2. The kit (one component per family)

| Component | Replaces | Notes |
| --- | --- | --- |
| `AskCard` | RunCommandCard (5 variants), ActionApprovalCard (6 kinds), WorkspaceWriteCard, ScheduleGrantCard, EnrollNodeCard, ConnectMcpCard, phone pairing request | One layout: asking header (mascot "!", who asks, countdown ring), one plain sentence, "Arslan 说：" summary when the model wrote one, a **code-derived risk line**, a folded detail box (code, command, path, fingerprint, credentials form for MCP), context lines (which job, scope, what still asks), options (the existing "don't ask again" checkboxes), buttons, "see the whole context" link. |
| `AskQueue` | the shared absolute slot | Several pending asks show as one card with "1 / 3" and arrows; answering moves to the next. |
| `ConfirmSheet` | 6 delete confirms, both `window.confirm` | Sentence, what is lost, "Cancel" + red action. Added to the seven actions that confirm nothing — or, where the action is reversible, replaced by an Undo toast instead (§5). |
| `Dialog` | CompanionDialog (9 call sites), BrowserPanel `<dialog>`, RunReplay overlay, HTML preview lightbox, narrow WorkDock, FirstRun | One portal, one z-index, `role=dialog aria-modal`, focus trap, Esc, a real close button. |
| `Toast` | App toast, Brain status toast, UpdatePill | One stack bottom-centre; optional action (Undo, Update). |
| `Notice` | chat error banner, escalation banner, NoModelHint, ToolTransportWarning, CryptoHealthNotice, RunReplay error, the ~60 inline alert lines | Tone (info / warn / error), one sentence, optional action. Inline, never blocking. |
| `ChoiceCard` | ClarifyOptionsCard | Same surface as `AskCard` without the asking header. |
| `ProposalRow` | LearnedLine, "noticed earlier" banner, ReviewProposal, BrainProposalInbox rows, LearnedPractices rows | One row look for "Arslan wants to remember …" everywhere; behaviour and APIs unchanged. |

## 3. The four decisions (user, 2026-10-05)

1. **Script summary.** What the model says a script does is prefixed "Arslan 说："; a separate amber line is
   derived from the code itself when the script deletes, moves, sends, runs a shell command or writes
   (AppleScript: `delete`, `move`, `send`, `do shell script`, `set … to` on documents, `make new`, `save`,
   `quit`; shell: the existing command classifier). The code decides; the summary never does. Unrecognised
   code is shown as "Arslan could not tell what this changes — read it".
2. **Keys.** ⌘⏎ allows, Esc declines. Plain ⏎ never answers a card (it would while typing).
3. **Island approvals.** Every ask can be answered in the island **except** risky ones (delete, send, pay, buy,
   transfer, submit — the existing `desktop_risky` / `risky` classification); those show "Open in Arslan".
4. **Full screen.** When another app is full screen and an ask waits, a small black tab stays at the top centre
   (mascot "!", "需要你", countdown), still — no flashing; hover expands it to the asking card; it leaves when
   answered or expired.

## 4. Island v2

- Compact: hugging the notch; left the mascot (state), right the job's criteria ring ("2/3") — no badges on
  the head.
- Expanded (hover): job title, elapsed time (mono), the criteria list with checks, the current step as a chip
  ("Notes · read back"), Stop and Open Arslan.
- Needs you: the `AskCard` compact variant (decision 3), with the queue ("1 / 3").
- Full screen: decision 4. Requires a non-activating `NSPanel` that joins all Spaces and full-screen Spaces
  (`collectionBehavior` canJoinAllSpaces + fullScreenAuxiliary, a level above full-screen windows) — the open
  I1 item; measured on the user's Mac before it is called done.
- Answering from the island goes through the same `approvals.answer` path as the chat card; the card closes
  everywhere (`card_resolved`, already used by the phone).

## 5. Behaviour fixed on the way

- Seven destructive actions without a confirm: provider Delete, Reset token, Forget SSH key, Forget node,
  phone Remove get `ConfirmSheet` (not undoable); practice Delete and saved candidate Delete become Undo toasts
  (soft delete for 5 s).
- Orphaned frames and their CSS removed; the backend stops emitting `suggest_create`; five missing CSS classes
  either styled by the kit or dropped.
- `humanCadence` moves to i18n (six languages); raw colours replaced by tokens.

## 6. Not changed

- Native macOS dialogs (update check, install, recovery, file pickers) and notifications keep the system look;
  only their wording is aligned (one sentence, what to do).
- No permission rule changes: what asks, how often, and the 300 s expiry stay as they are; the island and
  keyboard are new places to answer, not new ways to skip asking.

## 7. Phases (one PR each, behind no flags; each with tests and a real-Mac look)

- S1 kit: tokens, `AskCard`, `AskQueue`, `ConfirmSheet`, `Dialog`, `Toast`, `Notice` + Storybook-less visual
  tests (rendered in both themes, screenshotted by the web test harness).
- S2 approvals: the seven ask sources moved to `AskCard`; keys; risk line (classifier + tests with real
  scripts, including false positives/negatives listed in the test).
- S3 everything else: confirms, dialogs, toasts, notices, choice card, proposal rows; orphans removed.
- S4 Island v2 + answering from the island; full-screen panel (real-Mac acceptance: a full-screen app, an ask,
  answered from the tab).
- S5 FirstRun restyle and the remaining inline alerts.

## 8. Acceptance

- Every surface in §9 maps to one kit component (a test enumerates the card kinds the protocol can send and
  fails on one with no renderer).
- Both themes and every palette: contrast ≥ 4.5:1 for text, primary buttons distinguishable without colour.
- Real Mac: an ask answered with ⌘⏎ while typing in the composer does not answer on plain ⏎; two asks queue;
  an ask answered in the island closes in the chat; full-screen tab shows and answers.

## 9. Inventory (2026-10-06)

Approval surfaces 14 (RunCommandCard ×5 variants, ActionApprovalCard ×6 kinds, WorkspaceWriteCard,
ScheduleGrantCard, EnrollNodeCard, ConnectMcpCard, LearnedLine, noticed-earlier banner, ReviewProposal,
BrainProposalInbox, LearnedPractices rows, phone pairing, ProactiveInbox card, TaskPanel decisions); choice 3;
confirm dialogs 9; modals/overlays/drawers 13 (+ ~7 plain menus); toasts/banners/notices 19 (+ ~60 inline);
island 5 expanded views + compact + peek; native: 7 notifications, 12 message boxes, tray menu, recovery
window, splash. Sources: `App.tsx:708-822`, `arslanStore.ts:686-984`, `server/ws/protocol.py:229-340`,
`index.css:1342-2099`, `companion/CompanionDialog.tsx`, `island/IslandApp.tsx`, `desktop/src-tauri/src/{lib,
recovery_ui,resident}.rs`, `native_messages.json`.

## 10. Four small fixes in the same release (task book 2026-10-04 §2, and a real-Mac finding)

Checked on main `6c0f42c9` (2026-10-08).

- **D1 A saved fact looks like Arslan's reply.** `web/src/api/adapters.ts:406` turns `kind === "fact"` into an
  ordinary Arslan message (`sender: "arslan"`, avatar, text). It becomes a `ProposalRow`-style quiet line
  "记住了：…" with Undo, one line per turn for several facts, worded to the user ("你关注…"). Near-duplicates:
  `server/orchestrator/memory.py:218 save_facts` gets a near-duplicate check (two almost identical facts within
  minutes were seen), with tests.
- **D2 Arslan does not know its version.** `server/config.py:69` `app_version = "0.1.0"`; nothing in the system
  prompt; `docs/releases` has v0.1.47, v0.1.48, v0.1.53 only. The packaged build injects its real version
  (`/api/v1/health` reports it), the prompt says "You are Arslan vX.Y.Z", and the last three releases' notes ship
  in the app behind a read-only tool for "what changed". v0.1.49–v0.1.52 notes are added from their GitHub
  release bodies. Acceptance: the packaged app answers "what version / what's new" as the release page says.
- **D3 Tool cards under the answer.** Seen in a screenshot, not yet in code: reproduce first; the card must sit
  where the step happened. (The full fold-into-one-line timeline is 0.1.56; this is only the order.)
- **L1 A plain request learned as a correction, and backwards (real Mac, 2026-10-05).** "在访达里把 … 改名" was
  the conversation's first message; the turn renamed the file with `mv` (correct, by design); `server/services/
  lessons.py` still saved, active at once, "需要对文件做重命名等访达层面的操作时 → 在访达里完成，而不是用命令行"
  (`source == "user_correction"` takes effect immediately, `:236`, `:253`). Fix: a correction must answer
  something Arslan did earlier in the conversation (a first request is never one); and a lesson that contradicts
  the route that worked in the same turn is at most a proposal. Tests use that exact exchange (and its mirror: a
  real correction after a wrong route still takes effect at once). The pending proposal "PERM_DENIED → use
  osascript" seen on the same Mac is checked against the same rule.
