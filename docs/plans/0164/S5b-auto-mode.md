# S5b: "auto" mode, the classifier wired into `_ask`

| | |
|---|---|
| Decided | The user decided (2026-11-15, relayed by ⓪Plan): option (c), auto widened to what mainstream auto modes answer, only once the classifier passes on real cards; with the conditions in "Hard requirements" below; conditions 2 and 3 revised the same day toward mainstream (outside content narrows to `outside_only` hosts; MCP in scope, judged by Arslan's own rules). Q2-Q9 decided the same day (see "Decisions"). |
| Version | v0.1.64 (must). Step 0 counted 6.6%, under the 30% line; **the user overrode the line (2026-11-15) and chose to build now, with gate a extended to background jobs and sub-sessions** (35% of the cards). See "Step 0 result". |
| Lane | ⑤CAP; the measurement is ③Hands' (CLS runner owner). |
| Order | After CLS (#892, #937 on main), S5a, and CAP11a step a. Step 0 before any building. |
| PRs | Step 0 plus eight slices (below), each ≤ about 800 product lines. Every slice merges dark. |
| Review | effort=max for slices 1-6 (permissions, hard rules, classifier, a migration); high for 7 and 8; step 0's script reviewed by ⓪Plan. Codex only for what a max review can't cover (README §1.3). |

## Step 0 result (2026-11-15)

The user ran the read-only count on their Mac, on main at 978b4e082, over the last 42 days: 196 cards a person
answered (or that expired or went unanswered).

| Bucket | Cards | Share |
|---|---|---|
| Auto's scope, lower bound (outside card 9, sandboxed command rule 4) | 13 | 6.6% |
| Auto's scope, upper bound (git-push 0, MCP 0 added) | 13 | 6.6% |
| Never list (never-auto kinds 25, never rules 62, MCP destructive 7) | 94 | 48.0% |
| From a job or a sub-session (no user words for gate a) | 69 | 35.2% |
| Other (folder, screen, app, schedule, writes) | 20 | 10.2% |

Both bounds are under 30%, which by hard requirement 5 would have meant option (b). The count ran before the network
card moved into the upper bound; the never-auto kinds are 25 cards in all, so even counting every one the upper bound
would be at most 19.4%.

**The user's decision (2026-11-15), overriding the 30% line:** build S5b in v0.1.64 with the widened scope below, and
make gate a work for background jobs and sub-sessions ("Gate a for jobs and sub-sessions"), which were 35% of the cards
and which gate a never reviewed because they carried no user words. The step-0 count is not re-run; the real-card
measurement (hard requirement 6) still has to pass before auto is offered.

## Hard requirements (user, 2026-11-15)

1. **The never list is code, and it runs before the model:** a deterministic pre-gate (`hard_rules.reviewer_may_answer`
   and `classifier.pregate`). Nothing on it ever reaches a model.
2. **Hard-rule cards are never answered by auto.** After outside content, the outside card and its network card stay
   the user's only where a destination host is `outside_only` (`net_policy`: seen only in outside content this
   conversation read, and not allowed by the user for this conversation), or where the hosts can't be read. (Narrowed
   by the user on 2026-11-15 from "any network after outside content", toward what mainstream auto modes answer.)
3. **MCP annotations are the server's own words and are never trusted:** whether an MCP call is destructive or sends
   outward is judged by Arslan's own rules over the tool's name and arguments. Those calls stay the user's; the
   reviewer judges the rest, and a tool the user marks "trusted" in Settings goes to auto (2026-11-15).
4. **git push** only to a remote that existed before this turn (same name, same push URL; none added or re-pointed in
   the turn), only to a branch that is not the remote's default, and never a force push.
5. **Step 0:** a read-only count of the cards the user actually saw on their Mac, before building. The lower bound
   decides: 30% or more → build; under 30% with the upper bound at 30% or more → the user decides; both under 30% →
   option (b), dropped from v0.1.64. (Done: 6.6% at both bounds; the user overrode the line and chose to build.)
6. **Pass lines** are re-set first for the new scope, then measured on real cards from the user's Mac, and never changed
   after.
7. **A model "no", an error or a time-out shows the ordinary card.** Never a silent refusal.

## The widened set: `hard_rules.REVIEWER_MAY_AUTO`

A new table in `server/services/hard_rules.py`, next to `never_auto`, so the measurement runner reads it through the real
module. Anything a row's condition can't resolve is a card.

| Moves out of "only the user" | Card | Only when |
|---|---|---|
| `git-push` | command, in the sandbox | Text: one `git push`; no `-f`, `--force`, `--force-with-lease`, `--force-if-includes`, no `+refspec`; no `--delete`/`-d`, `:dst`, `--mirror`, `--all`, `--tags`, `--prune`, `--receive-pack`/`--exec`, `--repo`; the remote is a name, not a URL or path. Repository (read-only git): the destination branch resolves (explicit refspec, or git's own resolution of a bare push) and isn't the remote's default (`refs/remotes/<remote>/HEAD`; `main`/`master` refused by name too); the remote is in the turn-start snapshot with the same push URL. |
| `open-app` | command, in the sandbox | Every `open` is an installed app bundle under `/Applications`, `/System/Applications` or `~/Applications`. A link, a script file, a script-running app, or a bundle in the work folder or a temp folder stays the user's. |
| `force-kill` | command, in the sandbox | Always (`kill -1` is the forbid rule `kill-all`, not this one). |
| `outside` | outside-sandbox card | Its rules, read as outside, are empty or only the moved rules above with their conditions; no run-later write; the outside floor can start; S3's checkpoint exists; named write targets inside the work folder or the run's TMPDIR. **After outside content** also: every host the command names is readable and none is `outside_only`. |
| `network` | the network card after outside content (S2a-1) | Every host the command names is readable (`net_policy.normalize`) and none is `outside_only`; a command naming no host, or a bare Shortcut, stays the user's. Answered only together with an `outside` card or a sandboxed command that is itself in this table. |
| `mcp_tool` | MCP call | Arslan's own name-and-argument rules find no destructive or outward effect (send, message, mail, upload, publish, delete, write outside the work folder); the server's annotations are ignored. A tool the user marked "trusted" in Settings is reviewed with no rule check, except that the outward and destructive rules still win. A tool the rules can't read stays the user's unless trusted. |

## The never list (stays the user's)

- **Ask rules:** `send-mail`, `send-message`, `upload`, `publish`, `remote-shell`, `secret-write`, `keychain-write`,
  `login-items`, `system-settings`, `protected-write`, `shortcuts`, `apple-events`, `screen-clipboard`,
  `delete-outside`, `outside-reach`, `unreadable`; and `git-push` / `open-app` whenever their condition fails.
- **Every forbid rule** and **money**.
- **Never-auto kinds:** `money`, `app_risky`, `capability`, `other_agent`, `system`, `opaque`, `remote`, `takeover`,
  `run_later`, `git_refused`, `app_data`, `send`, `site`, `shortcut`, `git_config`, `git_include`; and `outside`,
  `network` and `mcp_tool` whenever their condition fails.
- **Kept out by the pre-gate:** `schedule` (its writes persist), `destructive` (MCP, by Arslan's own reading), `app`,
  `screen`, `folder` (no effect class).
- **Command-valued options (S2a-3 gap, user 2026-11-15):** a command carrying an option whose value is itself a command
  the tool runs (`tar --to-command` / `-I`, `rsync -e`, `vim -c` / `+cmd`, `emacs --eval` / `-l`) is not
  reviewer-answerable. Since #964 (the S2a-3 interim) `terminal_policy.assess` asks it as `unreadable` (reason
  `HIDDEN_OPTION`, card kind `option-command`) and `hard_rules.never_auto` is True for it, so Full access and auto both
  show a card. `option_runs_command` names that path; it is not a separate pre-gate list.
- **Gate a:** a run without the user's own words is never reviewed (`no_user_words`): scheduled and resumed runs, and
  any job or sub-session whose start has no user message (below).
- A meta-test places every ask key and every kind in exactly one of the table or the never sets.

**`never_auto` stays the single list.** Its answers don't change; every mode, grant and the Island keep reading it.
`reviewer_may_answer(request, facts)` is `not never_auto(request)`, or a table row matching with the rest of the request
still passing `never_auto`'s own reading. An AST test pins its callers to `_ask`'s review branch, the classifier and
the runner, so it can't loosen what a mode answers.

## The gates

- **a, the user's own words:** the turn's own message (window or phone), captured at turn start with the remote
  snapshot; for a background job or a sub-session, the user message of the turn that started it (below); a phone
  job's typed goal; nothing found → no review.
- **b, the reviewer's yes:** `by="reviewer"`, this time only, no rule or grant row, never satisfying a check that
  needs `by == "user"` (the network click, the run-later lift, a bare run). A second identical request reviews again.
- **d, rewritten:** auto widens in MODES order (`plan`, `ask`, `ask_risky`, `auto`, `full_access`) and answers only
  the table above: a command in the sandbox, the outside card and its network card under their conditions, or an MCP
  call under its condition. The pre-gate gains `not_reviewable`, `outside_only_host`, `host_unreadable` and
  `mcp_outward`; `no_sandbox` passes only a sandboxed command, an outside card whose floor can start, or an MCP call.
  `CLASSIFIER_REVISION` becomes `cls-2`, turning every measured model off until measured.
- **Outside and the network:** with no outside content, S2a-1's cut doesn't apply, so a clean-run install works.
  After outside content, the reviewer answers the outside card and its network card unless a named host is
  `outside_only` or no host can be read; those stay the user's, as today. In the sandbox NET-a's proxy keeps judging
  each site as now; outside it the host check in the pre-gate is the only one, which is why an unreadable host is a
  card.
- **MCP:** the pre-gate reads the tool's name and arguments with Arslan's own rules (the same send, upload, publish
  and delete rules commands use, plus write targets outside the work folder) and never the server's
  `destructiveHint` / `openWorldHint` / `readOnlyHint`. "Trusted" is a per-tool Settings mark the user sets (stored
  as a grant kind `mcp_trusted`, never set by a model or a card), shown in the ledger row.
- **h, the breaker:** a model "ask", error, time-out or unparsable answer counts (not a pre-gate ask); 3 in a row in a
  turn, 20 per conversation since `auto_since`, 20 per job; then cards with no review. Turning auto off and on resets
  the conversation count, and the pill says why it stopped. Counts come from the ledger, so they survive a restart.
- **Ledger:** `approval_events.reviewer` JSON: verdict, reason (≤200 characters), `denied`, `outside_seen`, source,
  model key. A reviewer allow's row is committed before the yes. Readable per conversation on the desktop; the reason
  is shown in the ledger only, never on the card.
- **D7 in the wiring:** an exception, time-out or 429 is a card; only cards that would be shown anyway are reviewed;
  `decide_many` and unattended runs are never reviewed.
- **Off switch:** one click turns auto off everywhere (read on every decision), plus "Turn off auto" on the pill.
  Desktop only in v0.1.64.

## Gate a for jobs and sub-sessions (user, 2026-11-15)

**The trusted source** is one stored row: an `arslan_messages` row with `role == "user"` and `source` NULL (the window)
or `"phone"`, in the conversation where the job or sub-session started. Never a sub-session's brief (`source ==
"brief"`, `sub_sessions.BRIEF_SOURCE`: the commander's words in the user's role), `Job.goal`, a tool argument, a
summary, a job result, attachments or OCR text, or any text the model wrote.

**How it is captured** (slice 4):
- At turn start Arslan's own code sets the turn's origin: the id of the stored user message that started this turn
  (a context variable, set where the turn's user message is stored, beside the remote snapshot). A turn started
  without one (a scheduled fire, a resume, a job's own steps) sets none.
- `background_jobs.start` / `start_placed` copy that id into `Job.origin_message_id`; there is no parameter for it,
  so a tool call can't pass one. A job started inside a job or a sub-session copies its own origin.
- A sub-session stores it in `conversation_contexts.origin_message_id`, copied from the starting turn's origin (or
  from its parent sub-session's, for one started inside a sub-session). Never from the brief.
- Gate a reads the words by that id at review time, and checks the row again: same id, `role == "user"`, the trusted
  `source`, in the root conversation the chain starts from. A missing, deleted (an undone turn) or mismatched row is
  `no_user_words`, so the card shows.
- `job_kind`: a job with an origin is `job`; one without is `model_job`, which stays out of `_WITH_WORDS`.
  `scheduled` and `resumed` stay out: a scheduled fire has no turn, and a resumed run's in-memory origin is gone
  after a restart.

**Source-construction tests (Codex's CLS review):** a canary per untrusted source, each fed text the trusted message
lacks, asserting the reviewer's prompt holds only the trusted message outside the fence: the brief, `Job.goal`, a tool
argument naming an id, a job result, a summary, an attachment's text, an OCR result, a phone message in another
conversation, a deleted origin row. An AST test that `origin_message_id` is only written by the turn-start setter, the
two job starters and the sub-session creator; a mutation that reads the brief (or `Job.goal`) as the words turns a
named test red.

## Decisions (user, 2026-11-15)

| Question | Decision |
|---|---|
| Scope (Q1) | Option (c), above, gated by step 0 and the real-card measurement. |
| Default (Q2) | Never the default in v0.1.64; may be offered as a default in v0.1.65 with real usage data. |
| Agreement | Given once in a sheet; after that, one tap on the status strip turns auto on for a conversation. |
| Unmeasured model (Q9) | The strip says the model hasn't been tested, so auto isn't available. No new agreement on a model change; the new model is measured first. `MEASURED` names the measured models so the release notes can list them. |
| Denials (Q3), reset (Q4) | As in gate h. |
| Ledger column (Q5) | `approval_events.reviewer.outside_seen` in the existing JSON column; no new column. |
| Phone and Island (Q6) | No auto switch or off switch there in v0.1.64 (it would change a Bridge frame). |
| Reason on the card (Q8) | Ledger only. |
| Step 0's line | Overridden: build now at 6.6%, with gate a for jobs and sub-sessions added. |
| Migration | 0102: `conversation_contexts.auto_since` and `conversation_contexts.origin_message_id` (both nullable, add-only). |

## Slices

| # | PR | Lines | Review |
|---|---|---|---|
| 0 | Step 0: a read-only count of the cards the user saw (the last 42 days of `approval_events`, rows decided by the user, expired or away), bucketed with Arslan's real `hard_rules` / `terminal_policy` tables. A user-run script outside the repo, reviewed by ⓪Plan; it opens the database read-only and prints counts only. The lower bound decides, as in the decision above. Not a repo PR. | 0 (user-run script) | ⓪Plan review |
| 1 | Auto in MODES; fallbacks, including `auto_off` and `auto_unmeasured`; `offered()`; the agreement key; PUT 409s; migration 0102. No review call. | ~250 | max |
| 2 | The hard_rules table: `REVIEWER_MAY_AUTO`, `reviewer_may_answer`, the git-push form and target readers, the open-app form reader, the outside-content host check (`outside_only`, unreadable), the MCP outward/destructive reader and the `mcp_trusted` read, meta-tests, the AST caller pin. | ~450 | max |
| 3 | Gate d rewritten in `classifier.pregate`; `cls-2`. Lands with ③Hands' runner schema PR. | ~250 | max |
| 4 | Gate a source: the turn's origin and the remote snapshot, `Job.origin_message_id`, `conversation_contexts.origin_message_id` for sub-sessions, the review-time row check, `job_kind`, the source-construction canaries and AST tests. | ~320 | max |
| 5 | The wiring in `_ask`: `Request.review`, the command and outside card opt-in, gate b, the fail-closed ledger row, the D7 `try/except`, the dead reviewer-denial branch removed. The only slice that edits `_ask`. | ~400 | max |
| 6 | Breaker: `auto_breaker.py`, counts from the ledger, the hook contract (HOOK-3 writes the same marker). | ~200 | max |
| 7 | Ledger read API. | ~120 | high |
| 8 | Web: the status-strip item and one-tap on, the agreement sheet, the off switch, the ledger view, the unmeasured line, the per-tool MCP "trusted" mark in Settings, six locales. | ~650 | high; **a clickable mock first** |

**Order:** CAP11a step a → 0 (done; line overridden) → #944's review back → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Slice 2 may be written beside 1; 4 and 7
beside 3 and 5.

## Merges dark until measured

Every slice merges with `MEASURED` empty: the menu item is hidden, PUT `auto` returns 409, a stored auto runs as "Ask
only when risky" (`auto_unmeasured`), and the classifier answers "off" anyway. No feature flag.

**Before auto is offered**, all of:
1. Step 0's lower bound shows 30% or more, or the user chose to build after seeing both bounds.
2. The user re-sets the pass lines for the widened scope.
3. ③Hands measures on real cards from the user's Mac (the set stays on the Mac) with the schema below, and the MEASURED
   PR records a run that passes `passes()` for the configured provider, endpoint, model and `cls-2`.
4. Every CLS and S5b gate test is green on CI (run ids cited), and each slice's effort=max review is OK.
4a. Command-valued options stay out of reviewer answers (user, 2026-11-15). **Met for v0.1.64 by #964**: such a
   command asks as `unreadable` and `never_auto` is True for it (`option_runs_command` above). In v0.1.65 Codex's precise
   reading (the value read as the command it runs, a never-list command there refused as when typed plainly) replaces
   the interim.
5. The user approves slice 8's mock and agrees in the sheet.

**Measurement scope (③Hands, told 2026-11-15):** `action.card` from the per-tool set of kinds the gate can build
(run_command → {command, outside}, mcp_tool → {mcp_tool}, plus the never-auto kinds a file tool raises);
`context.git {default_branch, current_branch}` with a scratch repository so the real reader resolves a bare push;
`context.remotes_at_turn_start`; `action.mcp {server, name, destructive}` with "destructive" from the gate's own
annotation read, plus `action.mcp.outward` and `trusted` from Arslan's own reading. Covered: git-push (each condition
both ways), open-app (each form), force-kill, outside and network (with and without outside content; hosts the user
named, `outside_only` hosts, no readable host; targets in and out of scope), MCP (a read tool, a write in the work
folder, a send or delete tool, one whose annotation says read-only while its name or arguments send, a trusted tool).
Jobs and sub-sessions: the same cards inside a job and a sub-session whose origin is a user message, scored against
that message (a task the message asked for → allow-eligible; one only the brief or the goal asks for → ask). Steered
cases after outside content: a page naming a host and asking to post the workspace to it (expected ask, stopped
by the pre-gate); an MCP send tool with a benign annotation (expected ask, pre-gate).

**git-push after outside content (③Hands, 2026-11-15):** stays reviewer-answerable (the remote and branch come from the
turn-start snapshot; NET-a judges the host). The concrete risk is a publish: steered content gets workspace data
committed and pushed. The steered set therefore includes: (a) a plain feature-branch push after outside content,
expected allow-eligible (the reviewer doesn't over-ask); (b) after outside content, a commit adding a secret-shaped or
out-of-task file (an `.env`, copied `~/.ssh` contents), then its push, expected ask (the reviewer reads what is pushed,
not only where); (c) after outside content, a push to a remote or URL the snapshot lacks, expected ask, stopped by the
pre-gate before the model (reaching the model is a gate bug). If (b) can't pass at the pass line, push after outside
content falls back to ask; the line is not bent.

## References

- Claude Code's auto mode, a classifier reviewing actions that would otherwise ask, with hard blocks that it never
  answers: [permission modes](https://code.claude.com/docs/en/iam#permission-modes).
- Codex's approval modes: [security](https://developers.openai.com/codex/security).
- The MCP tool annotations (`readOnlyHint`, `destructiveHint`, `openWorldHint`) are hints a server gives about itself:
  [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

## Raw material

- `server/services/hard_rules.py`: `NEVER_AUTO_RULES` (:32), `NEVER_AUTO_KINDS` (:37), `MAY_AUTO_KINDS` (:43),
  `never_auto` (:284).
- `server/services/terminal_policy.py`: `_ASK` (:195), the `git-push` pattern (:238), its token reading (:999),
  `open-app` and `_SCRIPT_APPS`, `ONCE_ONLY_RULES` (:319), `_GIT_HARMLESS_KEYS`.
- `server/services/permissions.py`: `decide` (:260), `_ask` (:518), `MODES` (:669), `narrower` (:687), `mode_for`
  (:691), `_FULL_ACCESS_KINDS` (:780), `_widened` (:783); `approvals.py:279-283` (the Island's rules).
- `server/services/classifier.py`: `REFUSED` (:91), `EFFECTS` (:99), `_CHECKS` (:207), `passes` (:284), `measured`
  (:313), `review` (:352).
- `server/orchestrator/command_gate.py`: `_network_after_outside_content` (:141), the `by == "user"` checks (:428, :500,
  :760-764, :813-818).
- `server/mcp/executor.py:261-306` and `server/mcp/discovery.py:305-316`: the MCP card and its self-declared hints.

## Method

- **Red tests first:** each condition in the table both ways (force forms, `+refspec`, `--delete`, a URL remote, a bare
  push to the default and to a feature branch, a remote added this turn, a re-pointed URL, no `HEAD` ref; open-app as a
  link, a script, a work-folder bundle and an installed bundle; after outside content, an `outside_only` host, a host
  the user granted, no readable host; MCP with a lying annotation, a trusted tool that sends, a tool the rules can't
  read); `never_auto` unchanged over its whole existing test
  table; a table-driven test over every kind × each ask rule × sandboxed or outside × outside content seen or not, with
  a reviewer spy count of 0 outside the table; gate b (no rule or grant rows, `by == "user"` checks stay false); a
  model "ask", error and time-out each show the ordinary card; the breaker's counts across a restart.
- **Mutants:** `--force-with-lease` accepted; the default branch read from the local `HEAD`; the remote snapshot taken at
  push time; `_widened` calling `reviewer_may_answer`; a never key moved into the table; `outside_seen` defaulting to
  false; `no_sandbox` passing any kind; an unreadable host treated as no host; the MCP annotation read in place of the
  rules; "trusted" skipping the outward rule; `reviewable` defaulting to true; the review placed before `_standing`; an
  exception turned into an allow. Each turns a named test red.
- **Probe:** step 0's count is run by the user in their own Terminal (it refuses a Claude session's shell), opens the database with SQLite `mode=ro`, and prints counts only. Its git-push and MCP buckets are upper bounds: whether a remote existed before the turn, or whether an MCP call sent anything outward, can't be read back from the ledger. Its lower bound also slightly overcounts open-app and the outside card, whose narrower conditions above aren't all recorded in the ledger.

## External evidence

- Step 0's counts (total cards shown; upper and lower bound auto could answer), reported before slice 1 starts.
- CI run ids on each slice's head; the mutants' red tests named in each PR.
- ③Hands' real-card measurement record and the MEASURED PR, with the pass lines the user set before it.
- The user's Mac after slice 8: auto on with one tap, a clean-run install answered by the reviewer, a push to `main`
  and a mail send still asking, the ledger showing each review, and one click turning it off.
