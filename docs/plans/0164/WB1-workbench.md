# WB1: the right-hand workbench, tidied

⓪Plan, 2026-10-29. The user approved this via ④参谋 on 2026-10-29 (「可以 转给 ⓪Plan」). It is in v0.1.64. Interface work, so **one clickable mock, shared with SIDE-0, goes to the user before any UI code** (user, 2026-10-28). Web only, not the security surface. **Merging:** the user's approval says 「纯前端，不碰安全面，另一个会话 OK 后由作者会话开自动合并」 (front end only, not the security surface; after another session's OK the author session turns on auto-merge). So WB1's PRs auto-merge after another session's OK on the current head and green checks, an exception the user made to `docs/sessions.md` §5.

| | |
|---|---|
| Lane | ⑥Helper (it also writes SIDE); ②Main reviews |
| Order | Mock first, together with SIDE-0. Then WB1. SIDE's tabs and SUB's progress tab are built on WB1, so the panel gets one tab model, not five or six hand-made tabs |
| Migration | None |
| Branches | `claude/0164-wb1-side0-mock`, `claude/0164-wb1-tabs` |

## What is there today (⓪Plan read main `5fcb4c17`; ④参谋 read main too)

- The workbench came from 0.1.58 §3 item 7: `web/src/components/workbench/`, state in `web/src/stores/workbenchStore.ts`.
- **Three fixed tabs**, always shown (`Workbench.tsx:16`, `TABS = ["task", "files", "browser"]`; `workbenchStore.ts:4`):
  - **Task** (`TaskTab.tsx`): what is running, with a stop button (`:45-57`), shows "Nothing running" most of the time (`:47`); the conversation's files (`:32-33`); its project (`:72-76`); its working folder (`:79`).
  - **Files** (`FilesTab.tsx`): browses the conversation's folder; files this conversation made carry a dot.
  - **Browser**: Hands' `WorkDock`, embedded (`Workbench.tsx:103`). Empty unless Hands opened a page.
- **Repeated:** the conversation's files and its working folder are in both Task and Files.
- **"Task"** doesn't say what is in it.
- **The resize handle** (`Workbench.tsx:85-86`) is `w-2 … hover:bg-primary/25 focus:bg-primary/25`: on hover or focus the whole strip turns orange. After a drag it keeps focus, so it stays lit. That last part is ④参谋's inference from a screenshot, not clicked on a real Mac. The user: 「很丑，要 Apple 风格」.
- **Section headings** are `text-[11px] font-semibold uppercase tracking-wider` (`TaskTab.tsx:14`).
- **Kept as is:** the reader slides over the tabs (`Workbench.tsx:106-107`). The panel opens only on a click (`workbenchStore.ts:22`, the 0.1.42 rule). Width is remembered (`:8`, `:55`).

## What to build

The panel holds only things that sit next to the conversation, the way Claude desktop does it. **A tab appears only when it has something in it.**

1. **Files (always there):** this conversation's files on top, the folder browser below, and the working folder in the tab's header row. Task and Files merge into this one tab.
2. **Progress (only while this conversation has a background job or a sub-session running):** one "doing what" line each, with a stop button (today's Task "working" list, `TaskTab.tsx:45-57`). SUB's sub-session tree goes here (SUB card).
3. **Browser (only when Hands has a page open).**
4. **Side chat 1, 2, … (per the SIDE card).**
5. **The Task tab goes.** The project is already shown in the sidebar and the conversation title, so it isn't repeated here.
6. **Unchanged:** the reader on top; the panel closed by default, opened only by a click; the width remembered.
7. **When a tab disappears while selected** (a job ends, Hands closes the page): the panel falls back to Files and does not close. The mock shows it.
8. **Apple-style look**, copying the references, not adding decoration (the iPhone build 22 lesson):
   - **Divider:** a 1 px light grey line. Hover changes only the cursor, and at most darkens the line slightly. No coloured block, and it returns to normal as soon as a drag ends. The hit area may stay wider than the line.
   - **Panel:** the sidebar's soft background, no heavy border. Tabs keep today's segmented control.
   - **Section headings:** small, grey, sentence case. No all-caps with letter spacing.
   - References: Finder, Notes, Xcode's inspector, Claude desktop.

## Four lines (`docs/sessions.md` §6)

1. **References:** Claude desktop's right-hand panel: artifacts and files beside the chat, with tabs shown when there is something to show (https://claude.ai). Finder's and Notes' split-view dividers, and Xcode's inspector pane: a thin line and a resize cursor, no colour (Apple's Human Interface Guidelines, "Split views", https://developer.apple.com/design/human-interface-guidelines/split-views). The author looks at each first-hand before the mock and notes in the PR what it does. **Extras listed for the user, not built:** a keyboard shortcut to show or hide the panel; "reveal in Finder" on the working folder; a badge on the Progress tab when something finishes while it is hidden.
2. **Raw material:** the code at `file:line` above, and the user's screenshot of the lit divider (kept by ④参谋; nothing from it goes in the repo). Before the mock, the author confirms on a real Mac build whether the divider stays lit after a drag, and says in the PR what was seen.
3. **Method:**
   - vitest first, red on main: Files is always present; Progress appears with a running job and goes when it ends; Browser appears only with a Hands page; Task is gone; a selected tab that disappears falls back to Files; the reader still covers the tabs; the width is still remembered.
   - The divider has no `bg-primary` in any state, and loses focus after a pointer-up (a test on the class list, plus a pointer-event test).
   - A mutation check on the "tab has content" rule.
   - `git grep` that `workbench.task` and `TaskTab` are gone, or carry a `DELETE-BY` if a locale key must stay for one release.
4. **External evidence:** CI run ids; the visibility tests going red when the rule is removed; the user's real-Mac smoke (the divider after a drag, a job starting and ending, Hands opening a page), added to `SMOKE.md`.

## PRs

- **WB1-0 = SIDE-0, one mock:** the panel structure, when tabs appear, where side chats sit, the divider and the look. Static HTML, not product code. The user OKs it before anything else starts. SIDE's mock items (selection bar, quote in the input, "Bring back to main") are in the same file.
- **WB1-1 tabs and look** (web only, about +250/−200 lines plus tests): merge Task into Files, the content-driven tab list, the divider, the headings. **§11:** `TaskTab.tsx` is deleted in the same PR; its running list moves into the Progress tab.
- SIDE-2 and SUB's progress tree then add their tabs through WB1's tab list.

## Not here

- SUB's sub-session tree itself (SUB card) and the side chat itself (SIDE card); WB1 only gives them the slot.
- Any server or Bridge change.
