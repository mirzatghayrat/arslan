# S6 "Remembered answers" page, with S4a's two follow-ups

| Item | Value |
|---|---|
| Lane | ②Main (the app rows: ③Hands reviews) |
| Version | v0.1.64 (README:112; S4a follow-ups in 0162/README:262 and STATUS:57) |
| Depends on | Nothing still open. S4b (allowed folders) is not built, so S4b adds its own section later |
| Branch / migration | `claude/0164-s6-remembered-answers`; migration 0092 (data only) |
| Old card | [0162/S6-remembered-answers-page.md](../0162/S6-remembered-answers-page.md) (Chinese, kept as written) |

This card was refreshed on 2026-11-11 against `main`; the PR re-checks every reference on its own base.

## Decisions (the user, 2026-11-11, with the approved mock)

1. **The old command rules are deleted, not listed.** Migration 0092 removes every `legacy_rule` row and the
   `terminal_always_allow` settings list they were copied from. In the same PR, nothing can write one again: the
   Inbox's "Always allow" refuses a recorded set that names one (`permissions.always_from`), and no card may store
   one (`permissions._STORED_ONLY` is empty, so `_check` raises). `terminal_policy.always_allowed`, `forget`,
   `_RETIRED`, `/settings/terminal-rules` and `TerminalRulesPanel` go.
2. **No "Always" comes back** for sites, Shortcuts or MCP tools. `permissions._NEVER_ALWAYS` is unchanged (only its
   comment).
3. **The entry point** is the last group of Settings › What Arslan may do, not a new nav section. A deep link
   (`openSection('settings', 'remembered')`, `sectionRegistry.SECTION_ANCHORS`) opens the page, scrolls the group to
   the top and highlights it briefly. The Terminal group has a one-line pointer to it.

Settled by the reviewer:

- **S4a follow-up 1 is a wording change only.** The ledger is unchanged (a never-opened card stays `away`,
  `expired`). Wherever an unanswered card shows, it reads as expired, not as "while you were away".
- **Apps are listed both in Settings › Hands and here** (the same rows).
- **Grants that do nothing right now are listed** with an "only when…" note (`text:` outside "ask before every
  command", `unsandboxed:*` with the sandbox on, the network after outside content).
- **Conversation titles** are the sidebar's generated title, falling back to the user's first message.

## What is remembered, and where it is listed now

| Kind | Stored as | Listed |
|---|---|---|
| App "Always" | `permission_rules` `app`/bundle id | 「始终允许」, and Settings › Hands |
| Outside the sandbox | grant `outside`/`*` | 「本对话内」 (it was `SandboxGrantsPanel`) |
| No sandbox at all | grant `command`/`unsandboxed:*` | 「本对话内」 (S4a follow-up 2: listed nowhere before) |
| One command's text | grant `command`/`text:<command>` | 「本对话内」 |
| Network after outside content | grant `network`/`network:*` | 「本对话内」 |
| Working folder, schedule, MCP tool, app, site, Shortcut | grants of those kinds | 「本对话内」 |
| A sub-session's grants (SUB3) | the same table, under the sub-session's id | nested under its commander's block |
| Task grants | `task_id != ""`, ended with their task | not listed, by design |
| Old command rules | `legacy_rule` | deleted by 0092 |
| Grants no request reads | e.g. a 0.1.61–0.1.62 rule card's `command` / `rules:<rules>`; `permissions.grant_is_live` | deleted by 0092 (the user's decision after #836's review), never listed |

A deleted conversation's grants are deleted with it (#799); one left over, or one under a deleted commander, is not
listed (`sub_sessions.is_deleted` on each link of the chain).

## What S6 builds

- **Server** (`server/api/permissions.py`): `GET /permissions/grants` adds, per grant, `what` (the kind as the page
  words it), a readable `name` (the command, the folder's name, the tool, the app, the site, the Shortcut), the MCP
  `server` label with `server_gone`, and its block (`sub_session`, `parent_id`, `parent_title`: the commander's).
  `GET /permissions/rules` moves an app still in the old Hands setting first (`hands_service.migrate_always`).
  `GET /approvals/refused` adds `unopened` (the card never opened) so the list can word each expiry. Deletes of an
  unknown id are 404.
- **Web**: `RememberedAnswers.tsx` as the last group of the page. A permanent bar says what is never remembered;
  「始终允许」 lists apps (all conversations, when given, last used and count or 「还没用到」); 「本对话内」 lists
  grants by conversation, newest first, each block with its title, 「打开对话」 and 「收回这段对话的全部」, a
  sub-session's under 「子会话：<title>」 with 「只在这个子会话里」. Commands, sites and folders are code, cut to one
  line, whole on hover. The outside and no-sandbox rows have an amber edge. 「收回」 has no confirm: the row fades
  out; while it goes the button is grey; a failure keeps the row with a red line. States: all empty, a section
  empty (「没有」), a list that can't be read (「现在列不出来」). Six locales. It replaces `SandboxGrantsPanel` and
  `TerminalRulesPanel`.
- **S4a follow-up 1 (words)**: the conversation's list 「过期了、没做的（这个对话）」, the Scheduled page's
  「过期或没法问、没做的（只算这个任务的）」, the sidebar's 「有卡片过期了」, and per row 「30 分钟没人回应，过期了」 or
  「前一张卡没人回应，这张没弹出来就过期了」. The phone and the Bridge frames are unchanged.

## Not touched

- `_NEVER_ALWAYS`'s members, `phone_stats.ASKED`, `FIRST_CHOICE_ONLY`, `_WINDOW_SCOPE_ONLY`, the 90-day ledger,
  `turn_undo`, Bridge frames, Hands' own list and add.
- Nothing is added from the page: it lists and takes back.

## Tests and acceptance

- **Red first** (behaviour): the migration removes the old rows and leaves the rest; "Always allow" on an old row
  stores nothing; a card cannot store a command rule; taking a grant back makes the same command ask again through
  the real tool loop (`unsandboxed:*`, `text:`) and an MCP tool's next call ask again; a deleted conversation's
  grants, and a sub-session's under a deleted commander, are not listed; the page lists each kind with its sentence;
  revoke fades the row and a failure keeps it; the deep link scrolls and highlights; the expiry words.
- **Mutants**, each caught by a test, run through an import hook with an unmutated control first: `always_from`
  accepts `legacy_rule`; a card may store one; revoke does nothing; the tombstone filter dropped; the chain not
  checked; a sub-session under its direct parent; task grants listed; a task grant deleted here; the migration
  keeping the old list or deleting every rule; the rules list skipping the Hands move.
- **Manual (Mac)**: answer 「本对话内」 on a sandbox-off command card, see it on the page, take it back, and get
  asked again.
- **Reference:** this card, the old card, 0162/README:256-262, PR #352 "Known limits".
- **External evidence:** the CI run for the PR head; the manual Mac pass; none yet.
