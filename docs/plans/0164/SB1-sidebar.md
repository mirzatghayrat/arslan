# SB1: sidebar order, sections, pin and collapse

⓪Plan, 2026-10-29. The user approved this via ④参谋 on 2026-10-29 (「合理 按你的建议，转给 ⓪Plan」). It is in v0.1.64. Interface work, so **a clickable mock goes to the user before any UI code** (user, 2026-10-28). It does not touch the security surface: the author session turns on auto-merge after another session's OK (`docs/sessions.md` §5).

| | |
|---|---|
| Lane | ⑥Helper writes it; ②Main reviews the server half (migration, API) |
| Order | After the pocket deletion (Q1; `remoteFirst` goes with it) and INB4 (sidebar status dots), so that no two cards edit `web/src/components/Sidebar.tsx` at once |
| Migration | 0079 (pin flag on `conversation_contexts`; logged by ②Main in #483) |
| Branches | `claude/0164-sb1-mock`, `claude/0164-sb1-order`, `claude/0164-sb1-pin` |

## What is there today (⓪Plan read main `17f52a82`; ④参谋 read `5988cb4d`)

- **Order is set once:** the list is sorted by the server's last activity only when it is loaded (`web/src/lib/sessionPersistence.ts:237`); threads the server hasn't seen stay at the front (`:239-242`). After that a new conversation is appended at the end (`web/src/App.tsx:403`, `:495`, `:533`), and a conversation that just got a message does not move up.
- **Remote is pinned to the top** by `remoteFirst` (`web/src/lib/conversationMeta.ts:41-46`), and project conversations are pulled out into their project groups (`web/src/components/Sidebar.tsx`).
- **No time on a row:** the sidebar's `ArslanThread` has no time field (`Sidebar.tsx:14`); the server's last activity is used only for that one sort.
- **No date sections, no pin, no groups.**
- **Fixed width, cannot collapse:** `w-52 lg:w-60` (`Sidebar.tsx:127`).
- **Already there:** "Move to project…" and "Move out" in the row menu (`web/src/components/ThreadRowMenu.tsx:85-110`). A conversation's project is `conversation_contexts.project_id` (`server/db/companion_models.py:21`).

## What to build

1. **Order:** always by last activity. Sending or receiving a message moves that conversation to the top at once. A new conversation also goes to the top.
2. **Date sections:** Today / Yesterday / Previous 7 days / Previous 30 days / Older. The names match the iPhone app's (①iOS gives the exact strings).
3. **Time on each row:** small grey text at the right (14:32 / Yesterday / 10/21). **The mock shows two versions for the user to pick:** a time on every row, or section headings only (how Claude desktop and ChatGPT do it).
4. **Collapse:** a button at the top, a keyboard shortcut, and the open or collapsed state is remembered. The mock shows the shortcut; it must not clash with an existing one (`git grep` the key handlers and the native menu).
5. **Pin:** a "Pinned" section at the very top; unpinning returns the conversation to its place by time. The pin is stored on the server's conversation record (`conversation_contexts`, migration 0079), so a reinstall keeps it and the iPhone can read it later. No Bridge frame changes in this card.
6. **Drag into a project:** drag a conversation onto a project in the sidebar. This is a drag version of the existing "Move to project…", calling the same API.
7. **Projects and archive:** project groups stay at the top as today; archived conversations stay folded at the bottom.

## Four lines (`docs/sessions.md` §6)

1. **References:**
   - Claude desktop and claude.ai (https://claude.ai): recent chats in a collapsible sidebar, starred chats above them.
   - ChatGPT (https://chatgpt.com): chats under date headings (Today, Yesterday, Previous 7 Days, Previous 30 Days).
   - Per ④参谋's look, both show time only in the headings, not on rows; that is why the mock shows both versions. The author checks both products first-hand before the mock and notes in the PR what each does today: headings, pin or star, collapse shortcut.
   - **Extras listed for the user, not built:** search in the sidebar (one exists in the Capabilities pages, not here); multi-select to move or delete; rename inline; a count per section.
2. **Raw material:** the code at `file:line` above. The author reads the user's own database read-only (`mode=ro`) for counts only, before the mock, and puts the numbers in the PR: how many conversations, how many in projects, how many archived, and the spread of last activity across the five sections. Those numbers decide whether the "Older" section needs a "show more". No titles or content go anywhere.
3. **Method:**
   - Server: a failing test first for the pin (set, clear, survives a list reload, not listed for sub-sessions or quick asks), plus migration up/down and the migration-runner list.
   - Web: vitest for the order (a sent message, a received message, a new conversation, an unpin each land in the right place), the section boundaries at local midnight, DST and the 7/30-day edges (fake clock), and collapse state surviving a reload.
   - A mutation check on the sort key and the section boundary function.
4. **External evidence:**
   - CI run ids for both PRs.
   - The order test goes red when the "move to top on message" line is removed.
   - The user's real-Mac smoke: send in an old conversation and watch it jump to the top; pin, quit, reopen; collapse with the shortcut. This goes on `SMOKE.md`.

## PRs

- **SB1-0 mock:** a clickable HTML mock with both time-display versions. It goes to the user first; nothing else starts before the OK.
- **SB1-1 order, sections, time, collapse** (web only, about +250 lines plus tests).
- **SB1-2 pin and drag** (migration 0079, one API field, the web side; about +200 lines plus tests).

## Not here

- Project groups as "groups without a goal", and conversations in a project reading or messaging each other: v0.1.65, in the Projects decisions (SUB card, "Projects").
- Showing the pin on the iPhone: later, with a Bridge frame change the user approves first.

**§9 / §11:** `remoteFirst` and the Remote special cases are removed by the pocket-deletion PR, not here. If SB1 lands first by mistake, it must keep them with their existing `DELETE-BY`.
