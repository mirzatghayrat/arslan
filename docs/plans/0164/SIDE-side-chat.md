# SIDE: side chat (ask a one-off question beside the main conversation)

> ⓪Plan, 2026-10-28. The user put side chat into v0.1.64 that day (relayed by ④参谋): side chat goes into v0.1.64, done the way Claude does it now, which the user finds convenient. This settles item 7 of `docs/plans/0164/README.md` §2 ("still unconfirmed").

| Item | Content |
|---|---|
| Lane | ⑥Helper (after STY), unless ②Main wants it with SUB. Backend parts touch SUB's data; agree with ②Main before SIDE-1. |
| Version | v0.1.64 |
| Tier | Must (user, 2026-10-28) |
| Depends on | SUB's base: SUB2 (child conversations with a parent id, only-inherited settings, hidden from the list) and the shared `kind` column from Q1's migration 0071 (`kind=side`). A clickable demo mock approved by the user before any product code (user, 2026-10-28). |
| Merge position | After SUB2. Not in the strict security chain, but SIDE-1 is on the security surface (permissions inherited, outside-content mark), so it is written and reviewed at effort=max plus Codex GPT-6 Astra. |
| Branches | `claude/0164-side-0-mock`, `claude/0164-side-1-backend`, `claude/0164-side-2-web` |
| Migration | The branch point needs a column: a branch message id on the side conversation. If Q1's migration 0071 has not opened yet, add the column there (Q1 + SUB + SIDE share it); otherwise SIDE-1 asks ②Main for the next free number and logs it in the plan's §6. `kind=side` and the parent id come from 0071. **SIDE-1 (⓪Plan, 2026-11-14):** 0101 (renumbered from 0093 and then from 0099, both released; 0100 is SUB7's) adds `branch_message_id` and `outside_at_start` only; the quote the user selected is the side chat's first message. ⓪Plan adds the §6 row. |

## What the user wants (the shape of Claude desktop's side chat)

- Select text in any reply: a small floating bar appears with "Start a side chat" and "Reply".
- The side chat opens in a right-hand panel with tabs ("Side chat 1", "Side chat 2", …), an expand button, a close button, and "+" for a blank side chat. The selected text appears as a quote in the side chat's input.
- It reads the main conversation **up to that point**. It never writes back into the main conversation.
- Mainstream reference: Claude Code's `/btw` answers from the current context and does not enter the conversation's history.

## Rules (④参谋's additions; the user said a better plan is welcome if there is one; ⓪Plan adopts them)

1. **Bring back to main** is the only way anything moves to the main conversation. It is an action on a side-chat reply: it puts the reply into the main input box as a quote, and the user decides whether to send. Nothing is sent automatically.
2. **Permissions inherit from the main conversation and are never broader.** By default only read-only tools (read files, search). Mechanism: SIDE-1 extends SUB2's `effective_settings` and its 422 `sub_session_inherits` (specified for `kind="sub"`) to `kind="side"`, and forces `no_memory` and `no_learning` there. The permission mode is global today (`server/services/permissions.py:575`), so "inherited" in practice means the read-only tool set, which the global mode can only narrow. No commands, file writes, memory or lesson writes, schedules or outward actions. (A later version may allow more, only by the user's explicit choice per side chat.) **Corrections (2026-11-14):** `_mode` is at `permissions.py:649`. On main, `sub_sessions._chain` and `effective_settings` walked only `kind == "sub"`; SIDE-1 extends them to `side`, stores `no_memory` and `no_learning` on the side row (**ruling, 2026-11-14:** `no_learning` only, forced for any side chat in `effective_settings`: a side chat reads memory and never writes it), and refuses its settings and model (422 `side_chat_inherits`) and a pin (404). The tools are an allowlist (`read_file`, `list_dir`, `search_files`, `web_search`, `web_extract`; ⓪Plan: reads are open, defences on writes and the network) kept where each tool's traits say it reads: 23 tools say so, `start_sub_session`'s door, the shared browser and Hands among them.
3. **Outside-content mark:** the mark is not stored per turn today (it is a per-turn context variable, `server/orchestrator/untrusted.py:74`; only `Job.outside_seen` and scheduled tasks persist it), so "did the turns up to the branch point read outside content" cannot be looked up later. Rule: **the side chat starts marked (`untrusted.carried(True)`) unless SIDE-1 can show those turns were clean; unknown counts as marked**, the same default as SUB's rule 1 and `background_jobs.py:168`. If INB2's per-run `runs.read_outside` (migration 0072) has landed, SIDE-1 may use it: every run of the parent up to the branch point `false` means clean; any `NULL` or `true` means marked. **Corrections (2026-11-14):** 0072 is on main and `untrusted.carried` exists (`untrusted.py:384`). SIDE-1 starts a side chat clean only if every parent run up to the branch recorded `false` and nothing it reads of the parent is framed as outside content; it works this out once, when the side chat is made, and stores it (`outside_at_start`), and every turn of one that started marked starts marked.
4. **No memory:** side chats write no memories or lessons, the same as temporary conversations.
5. **Kept and deletable:** side chats are stored under their parent conversation so they can be reopened; each can be deleted on its own; deleting the parent deletes them. Like SUB's rule 8 for `sub`, `side` is hidden from every conversation list, `/phone/live` included (test). **Correction (2026-11-14):** since SUB5d the window's list (GET /conversations) returns sub-sessions, so side chats are left out by a filter of their own (`phone_ids.in_list`). A closed side chat comes back from Overview's "Side chats" list (the user, 2026-11-11).
6. **Model:** the main conversation's model. Mac first; iPhone later (no Bridge frame change in v0.1.64).

## PR split

| PR | What | Size (product lines, approx.) |
|---|---|---|
| SIDE-0 | Clickable demo mock (static, not product code) for the user to approve: selection bar, right panel with tabs, quote in the input, "Bring back to main". **One mock with WB1** (user, 2026-10-29): the side-chat tabs sit in WB1's content-driven tab list, and SIDE-2 adds them through it after WB1-1 lands (`WB1-workbench.md`) | — |
| SIDE-1 | Backend: create a side conversation (`kind=side`, parent id, branch message id); context = parent messages up to the branch point; read-only tool set; inherited permissions; outside-content mark carried; memory and lessons off; list under the parent; delete | +250 |
| SIDE-2 | Web: selection bar, side panel with tabs / expand / close / "+", quote in input, "Bring back to main" into the main input box | +500 |

## Acceptance

- Tests (SIDE-1): the side chat's context ends at the branch point; a side chat cannot run a command, write a file, write memory or a lesson, or schedule anything (each refused or not offered); it starts marked when the parent's turns up to the branch read outside content, and clean otherwise; deleting the parent deletes its side chats; nothing from a side chat appears in the parent's history.
- Tests (SIDE-2): selecting text shows the bar; "Start a side chat" opens a tab with the quote; "Bring back to main" fills the main input and sends nothing.
- The user tries it on the Mac (smoke list).

## Not in scope

- iPhone side chat (later; Bridge frames need the user's OK).
- Writing from a side chat into the main conversation other than "Bring back to main".
- Side chats with tools beyond read-only.
