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

The panel holds only things that sit next to the conversation, the way Claude desktop does it. **Decided by the user on 2026-10-30:** a fixed row of Files, Progress and Browser, then any side chats. Anything added later opens from "+" (「面板页签保持一排，浏览器 也放到默认的一排里吧 这样默认就是 file progress 和 browser 以后再多加什么功能加到从面板的『+』打开」). This replaces the earlier "a tab appears only when it has content" for Progress and Browser.

1. **Files (always there):** this conversation's files on top, the folder browser below, and the working folder in the tab's header row with today's "Reveal in Finder" (moved from `TaskTab.tsx:84-85`). Task and Files merge into this one tab.
2. **Progress (always in the row):** one "doing what" line per background job or sub-session, with a stop button (today's Task "working" list, `TaskTab.tsx:45-57`). The tab shows a count while jobs run, and "Nothing is running in the background." when none are. SUB's sub-session tree goes here (SUB card). The job poll (`TaskTab.tsx:31-41`) moves up to the Workbench, so the count updates while another tab is selected.
3. **Browser (always in the row):** the user's URL reader, not Hands (⑥Helper's review). It starts with today's empty state and "New browser tab". The title bar's globe button goes (see "Browser decisions").
4. **Side chat 1, 2, … (per the SIDE card)** come after the three fixed tabs and can be closed. **"+"** starts a side chat directly; it becomes a menu once there is a second kind of thing to open.
5. **The Task tab goes.** The project already shows in the sidebar and opens from the conversation's header row (`App.tsx:667-670`), so it isn't repeated here. The two buttons that open "task" are redirected: the background-jobs chip (`App.tsx:697`) to Progress, a reply's "more files" (`ReplyArtifacts.tsx:39`) to Files. The store's default becomes "files" (`workbenchStore.ts:4`, `:43`). `OPEN_PROJECT_EVENT`, its import (`App.tsx:45`) and its listener (`:434-441`) go in the same PR (§11).
6. **Unchanged:** the reader on top; the panel closed by default, opened only by a click; the width remembered.
7. **When a side chat is closed while selected:** the panel falls back to Overview (WB1-2) and stays open; until WB1-2 lands, Files. The fixed tabs never disappear.
8. **Apple-style look**, copying the references, not adding decoration (the iPhone build 22 lesson):
   - **Divider:** a 1 px light grey line. Hover changes only the cursor, and at most darkens the line slightly. No coloured block. Use `focus-visible:` for the keyboard ring, so the arrow-key resize (`Workbench.tsx:87`) stays reachable and a mouse drag never lights it. The hit area may stay wider than the line.
   - **Panel:** the sidebar's soft background, no heavy border. Tabs keep today's segmented control.
   - **Section headings:** small, grey, sentence case. No all-caps with letter spacing.
   - References: Finder, Notes, Xcode's inspector, Claude desktop.

## Four lines (`docs/sessions.md` §6)

1. **References:** Claude desktop's right-hand panel: artifacts and files beside the chat, with tabs shown when there is something to show (https://claude.ai). Finder's and Notes' split-view dividers, and Xcode's inspector pane: a thin line and a resize cursor, no colour (Apple's Human Interface Guidelines, "Split views", https://developer.apple.com/design/human-interface-guidelines/split-views). The author looks at each first-hand before the mock and notes in the PR what it does. **Extras listed for the user, not built:** a keyboard shortcut to show or hide the panel; a badge on the Progress tab when something finishes while it is hidden.
2. **Raw material:** the code at `file:line` above, and the user's screenshot of the lit divider (kept by ④参谋; nothing from it goes in the repo). The divider staying lit is confirmed by the code; the author still notes the real-Mac look in the PR.
3. **Method:**
   - vitest first, red on main: the row is Files, Progress, Browser in that order, with Files the default; Progress shows the running count and the empty sentence; Browser starts empty with "New browser tab"; Task is gone; the jobs chip opens Progress and "more files" opens Files; "Reveal in Finder" is in the Files header; "+" starts a side chat; closing a selected side chat falls back to Files; the reader still covers the tabs; the width is still remembered; the title bar has one button.
   - The divider has no `bg-primary` in any state and no non-visible `focus:` background (a test on the class list).
   - A mutation check on the row order and the side-chat fallback.
   - `git grep` that `workbench.task`, `TaskTab` and `OPEN_PROJECT_EVENT` are gone, or carry a `DELETE-BY` if a locale key must stay for one release; `workbench-0158.test.tsx` (`:39`, `:67`, `:164`, `:184`) is updated, not deleted.
4. **External evidence:** CI run ids; the row-order and fallback tests going red under the mutation; the user's real-Mac smoke (the divider after a drag, the Progress count and empty sentence as a job starts and ends; the browser's empty state), added to `SMOKE.md`.

## PRs

- **WB1-0 = SIDE-0, one mock:** the panel structure, when tabs appear, where side chats sit, the divider and the look. Static HTML, not product code. The user OKs it before anything else starts. SIDE's mock items (selection bar, quote in the input, "Bring back to main") are in the same file.
- **WB1-1 tabs and look** (web only, about +250/−200 lines plus tests): merge Task into Files, the fixed row, the divider, the headings. **§11:** `TaskTab.tsx` is deleted in the same PR; its running list moves into the Progress tab.
- SIDE-2 and SUB's progress tree then add their tabs through WB1's tab list.

## WB1-2: Overview tab and icon tabs (user, 2026-10-30, in ⑥Helper's chat; chosen on the mock as "Go with it")

The user asked for Claude desktop's side rail: 「我还想要Claude 的这个 session rail」, 「这个概览可以是默认，不过这样以来 那个一排就太挤了」.
1. **A new fixed tab, Overview, comes first and is the default.** It replaces Files as the default and as the fallback when a selected side chat closes. The row is Overview, Files, Progress, Browser, then side chats; later additions still come from "+".
2. **The four fixed tabs are icons**, each with a tooltip and an aria-label, like Claude desktop's pane icons. Progress carries its count as a small badge. Side chats stay as words, since four words plus side chats overflow the row.
3. **Overview has four parts, all built from data the app already has, and a fifth (Changes, WB1-3) that needs one read-only endpoint.** The first four need no new endpoint (⓪Plan checked main):
   - **Environment:**
     - the conversation's model, with today's picker as "Change";
     - the project folder, with "Show in Finder";
     - the iPhone remote (Bridge) on or off: `phone_bridge_enabled` in the settings (`web/src/api/adapters.ts:123`).
   - **Deliverables**, right after Environment. The user said 「概览里 再加一个 output 我觉得很有用」, and when asked, chose 「产出的东西（交付物）」. It lists the files this conversation produced, newest first: the same list as the top of the Files tab. Clicking one opens it in the reader, and "All in Files" switches to the Files tab. The heading reuses the existing string `validation.artifacts` ("Deliverables").
   - **Context:** "Context N% used" with used/window, a bar, and five rows using the ring's existing strings (`models.partSystem`, `partTools`, `partContext`, `partHistory`, `partTurn`) and the `contextEstimated` note (`web/src/locales/models.ts:25-27`). It reuses `ringRows()` from `ConversationModelChip.tsx`, the K4b breakdown.
   - **Connectors:** only the MCP servers that need something: "Needs sign-in" with "Sign in", and "Can't connect" with "Retry". Then "The other N are connected" with "Manage", which opens Capabilities.
     - The data is `GET /mcp/servers` (`web/src/api/mcp.ts:7`). It already returns `state` and `shown` (`server/services/mcp_service.py`, `_to_dict`), with `needs_auth`, `failed` and `parked` among the states (`server/mcp/supervisor.py:78-79`).
     - The web type `McpServer` (`web/src/api/client.types.ts:990`) still lacks `state` and `shown`, so WB1-2 adds them to the type.

   Background jobs aren't repeated here, because they are in Progress.
   - **Changes (WB1-3)**, right after Deliverables, shown only when a turn in this conversation changed something. The user asked 「然后 changes 那？」 and picked "Add it" on the mock.
     - Per turn, newest first, it lists what the turn did in the user's folders. Each path is tagged "Made", "Edited" or "Deleted".
     - Each turn row carries today's `process.undoTurn` ("Undo this turn…"), which opens the existing UndoTurnSheet for that run. A turn already undone shows no undo.
     - **Data: not readable today (⓪Plan checked main).** `GET /runs/{run_id}/checkpoint` (`server/api/runs.py:567`) returns `checkpoints.summary()` (`server/services/checkpoints.py:634`) plus `turn_undo.preview()`. That gives counts only, `changed` and `created`: no path list, no deleted-versus-edited split, and nothing per conversation.
     - So WB1-3 adds one read-only endpoint that lists, for a conversation's runs, each changed path with its kind. The kind comes from the checkpoint manifest's finished entries: saved copy `None` means the run made the file, and a `None` state at finish means deleted. Sub-runs and quick turns follow the conversation's existing run filter.
     - This makes WB1-3 server plus web, so it is **its own PR after WB1-2**. ②Main reviews the endpoint. It is ordinary product code, not front end only, so **the user merges it**: the user's auto-merge word for WB1 covered front-end work only.
     - **Only turns that can still be undone** (⓪Plan's call, on ⑥Helper's suggestion). Checkpoint copies expire after `KEEP_S`, and the quota sweep removes older runs (`checkpoints.py:625-631`). Once a run's manifest is gone, its paths can't be listed. So the section covers only turns whose checkpoint still exists, which is exactly the set the undo works for, and says so in a line under the heading. Keeping a path list apart from the copies would add storage for little gain.
     - New strings: chH ("Changes"), made, edited, deleted, and the coverage line.
     - Tests:
       - the rows equal the manifest's paths and kinds per turn;
       - a turn with no changes isn't listed;
       - a turn's undo opens the sheet for its run;
       - an undone turn shows no undo;
       - the endpoint returns 404 for an unknown conversation and never lists another conversation's runs;
       - an expired or swept run isn't listed.
4. **New strings, in all six languages:** overview, envH, ctxH, conH, change, bridge, needsSignIn, signIn, cantConnect, retry, othersOk, manage, allFiles.
5. **Tests:**
   - Overview is the default and comes first;
   - the four icons have labels;
   - the Context rows equal `ringRows()` for the same input;
   - Deliverables equals the conversation's files, newest first, and clicking one opens the reader;
   - Connectors lists only servers that aren't OK, and its count of the rest is right;
   - closing a selected side chat falls back to Overview.

   A mutation check on the default tab and the Connectors filter.
6. **PR:** its own small PR after WB1-1, web only. It is not the security surface, so the author auto-merges after another session's OK (the user's word for WB1, above).

## Browser decisions (user, 2026-10-30, in ⑥Helper's chat)

- **In WB1-1:** the address field also takes words. Words go to Bing (`https://www.bing.com/search?q=…`), and an address without a scheme gets `https://` added. Today the field accepts only full `https://` addresses (`web/src/components/BrowserReader.tsx:70`, `type=url pattern="https://.*"`). A Bing search is a plain GET, so it fits the reader's no-forms rule. Test: words become a Bing URL; `example.com` becomes `https://example.com`; `http://` and other schemes are still refused.
- **Next round, candidates:**
  - **BRW1:** a real browser instead of the screenshot reader, where the user can click on the page and sign in;
  - **BRW2:** the user and the agent see the same browser, as Claude desktop's pane does. Hands' pages show in the workbench, and the user can take over.

  Both are on the security surface: each needs its own card, and the user merges. They are recorded in the v0.1.64 README §3.13.
- **Not taken:** a single view menu in place of the row of tabs. The user said 「左上角只放一个 这个不对 这里还是变回原来的」, so the panel keeps its row of tabs.
- **Title bar: one button** (user, 2026-10-30: 「标题栏只留一个按钮」). Only the panel button stays, and the globe goes. The blue Background chip still shows while a job runs.
  - **Pending:** its icon. ⑥Helper recommends keeping the mirrored pair, as Xcode does for its navigator and inspector: the sidebar's collapse button at the top left with the line on the left (lucide `PanelLeft`), and the panel's at the top right with the line on the right (`PanelRight`, as today).
- **Not taken:** marking up a page or screenshot and sending it, as in Claude desktop's annotation bar (user: 「2在页面上画标记再发给我 我用的不多 可以不做」). The /btw-style side question is SIDE, and the shared browser is BRW2.

## Not here

- SUB's sub-session tree itself (SUB card) and the side chat itself (SIDE card); WB1 only gives them the slot.
- Any server or Bridge change.
