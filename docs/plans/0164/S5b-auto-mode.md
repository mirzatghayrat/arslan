# S5b: "auto" mode, the classifier wired into `_ask`

| | |
|---|---|
| Decided | The user decided (2026-11-15, relayed by ⓪Plan): option (c), auto widened to what mainstream auto modes answer, only once the classifier passes on real cards; with the conditions in "Hard requirements" below. Q2-Q9 decided the same day (see "Decisions"). |
| Version | v0.1.64 (must), **subject to step 0**: if auto could answer under 30% of the cards the user actually saw, S5b becomes option (b) and leaves v0.1.64. |
| Lane | ⑤CAP; the measurement is ③Hands' (CLS runner owner). |
| Order | After CLS (#892, #937 on main), S5a, and CAP11a step a. Step 0 before any building. |
| PRs | Step 0 plus eight slices (below), each ≤ about 800 product lines. Every slice merges dark. |
| Review | effort=max for slices 1-6 (permissions, hard rules, classifier, a migration); high for 7 and 8; step 0's script reviewed by ⓪Plan. Codex only for what a max review can't cover (README §1.3). |

## Hard requirements (user, 2026-11-15)

1. **The never list is code, and it runs before the model:** a deterministic pre-gate (`hard_rules.reviewer_may_answer`
   and `classifier.pregate`). Nothing on it ever reaches a model.
2. **Hard-rule cards are never answered by auto**, above all the network card after outside content.
3. **MCP annotations are the server's own words and are not trusted alone;** an MCP call that sends anything outward
   is a send and stays the user's. Arslan can't decide that reliably today, so **MCP stays out of auto in v0.1.64**.
4. **git push** only to a remote that existed before this turn (same name, same push URL; none added or re-pointed in
   the turn), only to a branch that is not the remote's default, and never a force push.
5. **Step 0:** a read-only count of the cards the user actually saw on their Mac, before building. The lower bound
   decides: 30% or more → build; under 30% with the upper bound at 30% or more → the user decides; both under 30% →
   option (b), dropped from v0.1.64.
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
| `outside` | outside-sandbox card | Its rules, read as outside, are empty or only the moved rules above with their conditions; no run-later write; **the run read no outside content**; the outside floor can start; S3's checkpoint exists; named write targets inside the work folder or the run's TMPDIR. |
| `mcp_tool` | MCP call | **Not in v0.1.64** (row present, disabled). |

## The never list (stays the user's)

- **Ask rules:** `send-mail`, `send-message`, `upload`, `publish`, `remote-shell`, `secret-write`, `keychain-write`,
  `login-items`, `system-settings`, `protected-write`, `shortcuts`, `apple-events`, `screen-clipboard`,
  `delete-outside`, `outside-reach`, `unreadable`; and `git-push` / `open-app` whenever their condition fails.
- **Every forbid rule** and **money**.
- **Never-auto kinds:** `money`, `app_risky`, `capability`, `other_agent`, `system`, `opaque`, `remote`, `takeover`,
  `run_later`, `git_refused`, `app_data`, `network`, `send`, `site`, `shortcut`, `git_config`, `git_include`; and
  `outside` whenever its condition fails.
- **Kept out by the pre-gate:** `schedule` (its writes persist), `mcp_tool` and `destructive` (MCP), `app`, `screen`,
  `folder` (no effect class).
- **Gate a:** a run without the user's own words (model-started jobs, scheduled and resumed runs) is never reviewed.
- A meta-test places every ask key and every kind in exactly one of the table or the never sets.

**`never_auto` stays the single list.** Its answers don't change; every mode, grant and the Island keep reading it.
`reviewer_may_answer(request, facts)` is `not never_auto(request)`, or a table row matching with the rest of the request
still passing `never_auto`'s own reading. An AST test pins its callers to `_ask`'s review branch, the classifier and
the runner, so it can't loosen what a mode answers.

## The gates

- **a, the user's own words:** the turn's own message (window or phone), captured at turn start with the remote
  snapshot; a background job keeps its starting turn's words; a phone job's typed goal; model-started → no review.
- **b, the reviewer's yes:** `by="reviewer"`, this time only, no rule or grant row, never satisfying a check that
  needs `by == "user"` (the network click, the run-later lift, a bare run). A second identical request reviews again.
- **d, rewritten:** auto widens in MODES order (`plan`, `ask`, `ask_risky`, `auto`, `full_access`) and answers only
  the table above: a command in the sandbox, or the outside card under its condition. The pre-gate gains
  `not_reviewable`, `outside_after_content` and `mcp_out`; `no_sandbox` passes only a sandboxed command or an outside
  card whose floor can start. `CLASSIFIER_REVISION` becomes `cls-2`, turning every measured model off until measured.
- **Outside and the network:** the reviewer answers an outside card only in a run with no outside content, where
  S2a-1's cut doesn't apply, so a clean-run install works. After outside content it isn't asked: the user gets the
  outside card and its network card, as today.
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
| Migration | 0102: `conversation_contexts.auto_since` (nullable, add-only). |

## Slices

| # | PR | Lines | Review |
|---|---|---|---|
| 0 | Step 0: a read-only count of the cards the user saw (the last 42 days of `approval_events`, rows decided by the user, expired or away), bucketed with Arslan's real `hard_rules` / `terminal_policy` tables. A user-run script outside the repo, reviewed by ⓪Plan; it opens the database read-only and prints counts only. The lower bound decides, as in the decision above. Not a repo PR. | 0 (user-run script) | ⓪Plan review |
| 1 | Auto in MODES; fallbacks, including `auto_off` and `auto_unmeasured`; `offered()`; the agreement key; PUT 409s; migration 0102. No review call. | ~250 | max |
| 2 | The hard_rules table: `REVIEWER_MAY_AUTO`, `reviewer_may_answer`, the git-push form and target readers, the open-app form reader, meta-tests, the AST caller pin. | ~350 | max |
| 3 | Gate d rewritten in `classifier.pregate`; `cls-2`. Lands with ③Hands' runner schema PR. | ~250 | max |
| 4 | Gate a source: the turn's words and the remote snapshot, `Job.user_words`, `job_kind`, canary and AST tests. | ~220 | max |
| 5 | The wiring in `_ask`: `Request.review`, the command and outside card opt-in, gate b, the fail-closed ledger row, the D7 `try/except`, the dead reviewer-denial branch removed. The only slice that edits `_ask`. | ~400 | max |
| 6 | Breaker: `auto_breaker.py`, counts from the ledger, the hook contract (HOOK-3 writes the same marker). | ~200 | max |
| 7 | Ledger read API. | ~120 | high |
| 8 | Web: the status-strip item and one-tap on, the agreement sheet, the off switch, the ledger view, the unmeasured line, six locales. | ~600 | high; **a clickable mock first** |

**Order:** CAP11a step a → 0 → (30% or more) → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Slice 2 may be written beside 1; 4 and 7
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
5. The user approves slice 8's mock and agrees in the sheet.

**Measurement scope (③Hands, told 2026-11-15):** `action.card` from the per-tool set of kinds the gate can build
(run_command → {command, outside}, mcp_tool → {mcp_tool}, plus the never-auto kinds a file tool raises);
`context.git {default_branch, current_branch}` with a scratch repository so the real reader resolves a bare push;
`context.remotes_at_turn_start`; `action.mcp {server, name, destructive}` with "destructive" from the gate's own
annotation read. Covered: git-push (each condition both ways), open-app (each form), force-kill, outside (with and
without outside content, targets in and out of scope), MCP (all expected "ask").

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
  link, a script, a work-folder bundle and an installed bundle); `never_auto` unchanged over its whole existing test
  table; a table-driven test over every kind × each ask rule × sandboxed or outside × outside content seen or not, with
  a reviewer spy count of 0 outside the table; gate b (no rule or grant rows, `by == "user"` checks stay false); a
  model "ask", error and time-out each show the ordinary card; the breaker's counts across a restart.
- **Mutants:** `--force-with-lease` accepted; the default branch read from the local `HEAD`; the remote snapshot taken at
  push time; `_widened` calling `reviewer_may_answer`; a never key moved into the table; `outside_seen` defaulting to
  false; `no_sandbox` passing any kind; `reviewable` defaulting to true; the review placed before `_standing`; an
  exception turned into an allow. Each turns a named test red.
- **Probe:** step 0's count is run by the user in their own Terminal (it refuses a Claude session's shell), opens the database with SQLite `mode=ro`, and prints counts only. Its git-push and MCP buckets are upper bounds: whether a remote existed before the turn, or whether an MCP call sent anything outward, can't be read back from the ledger. Its lower bound also slightly overcounts open-app and the outside card, whose narrower conditions above aren't all recorded in the ledger.

## External evidence

- Step 0's counts (total cards shown; upper and lower bound auto could answer), reported before slice 1 starts.
- CI run ids on each slice's head; the mutants' red tests named in each PR.
- ③Hands' real-card measurement record and the MEASURED PR, with the pass lines the user set before it.
- The user's Mac after slice 8: auto on with one tap, a clean-run install answered by the reviewer, a push to `main`
  and a mail send still asking, the ledger showing each review, and one click turning it off.
