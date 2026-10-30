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
  - **Task** (`TaskTab.tsx`): what is running, with a stop button (`:45-57`; its job poll is `:31-41`), shows "Nothing running" most of the time (`:47`); the conversation's files (`:58-71`); its project (`:72-76`); its working folder with "Reveal in Finder" (`:78-87`, `filesApi.reveal` at `:84-85`).
  - **Files** (`FilesTab.tsx`): browses the conversation's folder; files this conversation made carry a dot.
  - **Browser**: `WorkDock`, embedded (`Workbench.tsx:103`). **It is the user's own URL reader, not Hands** (⑥Helper's review of #489): its tabs are added only by "New browser" in its empty state (`WorkDock.tsx:73-77`, `:101-102`), `BrowserReader` is a URL field (`BrowserReader.tsx:70-71`), the title bar's Globe button always opens it (`App.tsx:719-728`), and its tabs persist in localStorage (`lib/workDock.ts:22-31`). The tab count lives in WorkDock's own state (`WorkDock.tsx:15`), which isn't mounted while another tab is selected.
- **Two buttons open "task":** the title bar's background-jobs chip (`App.tsx:697`) and a reply's "more files" (`ReplyArtifacts.tsx:39`). The store's default tab is "task" (`workbenchStore.ts:43`).
- **Task's project link** dispatches `OPEN_PROJECT_EVENT` (`TaskTab.tsx:17`, `:75`), which App listens for (`App.tsx:45`, `:434-441`). The project also opens from the conversation's header row (`App.tsx:667-670`, `ConversationControls`).
- **Repeated:** the conversation's files and its working folder are in both Task and Files.
- **"Task"** doesn't say what is in it.
- **The resize handle** (`Workbench.tsx:85-86`) is a `tabIndex=0` strip with `hover:bg-primary/25 focus:bg-primary/25`: on hover or focus the whole strip turns orange. A pointer-down focuses it, so after a drag it stays lit until blur (the code confirms ④参谋's reading of the screenshot). The user: 「很丑，要 Apple 风格」.
- **Section headings** are `text-[11px] font-semibold uppercase tracking-wider` (`TaskTab.tsx:14`).
- **Kept as is:** the reader slides over the tabs (`Workbench.tsx:106-107`). The panel opens only on a click (`workbenchStore.ts:22`, the 0.1.42 rule). Width is remembered (`:8`, `:55`).

## What to build

The panel holds only things that sit next to the conversation, the way Claude desktop does it. **A tab appears only when it has something in it.**

1. **Files (always there, and the default tab):** this conversation's files on top, the folder browser below, and the working folder in the tab's header row with today's "Reveal in Finder" (moved from `TaskTab.tsx:84-85`). Task and Files merge into this one tab.
2. **Progress (only while this conversation has a background job or a sub-session running):** one "doing what" line each, with a stop button (today's Task "working" list, `TaskTab.tsx:45-57`). SUB's sub-session tree goes here (SUB card). The job poll (`TaskTab.tsx:31-41`) moves up to the Workbench, so the tab can appear while Files is selected.
3. **Browser (only while the user has a browser tab open):** shown when saved dock tabs exist, or after the title-bar Globe button opens it with today's empty state and "New browser"; it goes when its last tab closes, and an empty Browser opened by the Globe button goes when the user picks another tab without adding a page. **This differs from the relayed wording ("when Hands has a page open"):** this browser is the user's URL reader, and nothing on the Hands side opens pages here (⑥Helper's review); the rule "a tab appears only when it has content" is kept. To know the count while another tab is selected, it is read outside WorkDock (`restoreDock`, or a store field).
4. **Side chat 1, 2, … (per the SIDE card).**
5. **The Task tab goes.** The project already shows in the sidebar and opens from the conversation's header row (`App.tsx:667-670`), so it isn't repeated here. The two buttons that open "task" are redirected: the background-jobs chip (`App.tsx:697`) to Progress, a reply's "more files" (`ReplyArtifacts.tsx:39`) to Files. The store's default becomes "files" (`workbenchStore.ts:4`, `:43`). `OPEN_PROJECT_EVENT`, its import (`App.tsx:45`) and its listener (`:434-441`) go in the same PR (§11).
6. **Unchanged:** the reader on top; the panel closed by default, opened only by a click; the width remembered.
7. **When a tab disappears while selected** (a job ends, the user closes the last browser tab): the panel falls back to Files and does not close. The mock shows it.
8. **Apple-style look**, copying the references, not adding decoration (the iPhone build 22 lesson):
   - **Divider:** a 1 px light grey line. Hover changes only the cursor, and at most darkens the line slightly. No coloured block. Use `focus-visible:` for the keyboard ring, so the arrow-key resize (`Workbench.tsx:87`) stays reachable and a mouse drag never lights it. The hit area may stay wider than the line.
   - **Panel:** the sidebar's soft background, no heavy border. Tabs keep today's segmented control.
   - **Section headings:** small, grey, sentence case. No all-caps with letter spacing.
   - References: Finder, Notes, Xcode's inspector, Claude desktop.

## Four lines (`docs/sessions.md` §6)

1. **References:** Claude desktop's right-hand panel: artifacts and files beside the chat, with tabs shown when there is something to show (https://claude.ai). Finder's and Notes' split-view dividers, and Xcode's inspector pane: a thin line and a resize cursor, no colour (Apple's Human Interface Guidelines, "Split views", https://developer.apple.com/design/human-interface-guidelines/split-views). The author looks at each first-hand before the mock and notes in the PR what it does. **Extras listed for the user, not built:** a keyboard shortcut to show or hide the panel; a badge on the Progress tab when something finishes while it is hidden.
2. **Raw material:** the code at `file:line` above, and the user's screenshot of the lit divider (kept by ④参谋; nothing from it goes in the repo). The divider staying lit is confirmed by the code; the author still notes the real-Mac look in the PR.
3. **Method:**
   - vitest first, red on main: Files is always present and the default; Progress appears with a running job (while Files is selected) and goes when it ends; Browser appears with a saved or opened dock tab and goes with its last tab; Task is gone; the jobs chip opens Progress and "more files" opens Files; "Reveal in Finder" is in the Files header; a selected tab that disappears falls back to Files; the reader still covers the tabs; the width is still remembered.
   - The divider has no `bg-primary` in any state and no non-visible `focus:` background (a test on the class list).
   - A mutation check on the "tab has content" rule.
   - `git grep` that `workbench.task`, `TaskTab` and `OPEN_PROJECT_EVENT` are gone, or carry a `DELETE-BY` if a locale key must stay for one release; `workbench-0158.test.tsx` (`:39`, `:67`, `:164`, `:184`) is updated, not deleted.
4. **External evidence:** CI run ids; the visibility tests going red when the rule is removed; the user's real-Mac smoke (the divider after a drag, a job starting and ending, opening and closing a browser tab), added to `SMOKE.md`.

## PRs

- **WB1-0 = SIDE-0, one mock:** the panel structure, when tabs appear, where side chats sit, the divider and the look. Static HTML, not product code. The user OKs it before anything else starts. SIDE's mock items (selection bar, quote in the input, "Bring back to main") are in the same file.
- **WB1-1 tabs and look** (web only, about +250/−200 lines plus tests): merge Task into Files, the content-driven tab list, the divider, the headings. **§11:** `TaskTab.tsx` is deleted in the same PR; its running list moves into the Progress tab.
- SIDE-2 and SUB's progress tree then add their tabs through WB1's tab list.

## Browser decisions (user, 2026-10-30, in ⑥Helper's chat)

- **In WB1-1:** the address field also takes words. Words go to Bing (`https://www.bing.com/search?q=…`), and an address without a scheme gets `https://` added. Today the field accepts only full `https://` addresses (`web/src/components/BrowserReader.tsx:70`, `type=url pattern="https://.*"`). A Bing search is a plain GET, so it fits the reader's no-forms rule. Test: words become a Bing URL; `example.com` becomes `https://example.com`; `http://` and other schemes are still refused.
- **Next round, candidates:**
  - **BRW1:** a real browser instead of the screenshot reader, where the user can click on the page and sign in;
  - **BRW2:** the user and the agent see the same browser, as Claude desktop's pane does. Hands' pages show in the workbench, and the user can take over.

  Both are on the security surface: each needs its own card, and the user merges. They are recorded in the v0.1.64 README §3.13.
- **Pending the user's OK:** a single view menu in the panel header instead of a row of tabs (the mock's "Tabs: One menu / A row"). If they pick it, the menu shows the current view with a chevron and lists Files, Progress, Browser, the side chats and "New side chat"; ⌘1…⌘9 pick a view; a blue dot marks a view that appeared while the user was elsewhere.

## Not here

- SUB's sub-session tree itself (SUB card) and the side chat itself (SIDE card); WB1 only gives them the slot.
- Any server or Bridge change.
