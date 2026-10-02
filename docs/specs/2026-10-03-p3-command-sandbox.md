# P3 — commands run in a sandbox (2026-10-03)

From the kernel upgrade plan (`docs/plans/2026-10-01-kernel-upgrade-plan.md`, branch `claude/kernel-bakeoff-plan`), P3:
"`run_command` runs in a macOS sandbox by default — writable: the working folder and temp; unreadable: `~/.ssh`,
the keychain, Arslan's own keys and database; leaving it takes a card only you can click."

Today (D5) the text rules in `terminal_policy` decide whether to ask, but an allowed command runs with all of the
user's permissions. Commands that just run without a card (most of them) are exactly the ones nobody looked at.

## Mainstream reference

- **Codex CLI** (`workspace-write`): seatbelt on macOS; writes only to the working folder and temp; reads anywhere;
  a command that fails in the sandbox can be re-run outside it after approval ("on-failure"); the model can also
  ask up front with a justification; approvals can cover the rest of the session.
- **Claude Code** (sandboxed bash): writes limited to the working folder; anything else asks.
- **Hermes / OpenClaw**: no OS sandbox by default; pattern-based approval only (Arslan's current state).

Arslan follows Codex's shape, with the network left on (Arslan reads the web with curl; the seatbelt cannot
restrict a connection to one host anyway, so no promise is made about the network).

## Design

**The profile** (`server/services/command_sandbox.py`, pure, unit-tested). It starts from `(allow default)`
(reading, running programs and the network stay as they are), then:
1. `(deny file-write* (subpath "/"))`
2. allows writes to the working folder, the per-user temp folder (the parent of `$TMPDIR`), `/private/tmp`,
   `/private/var/tmp`, `/dev`, and the tool caches `~/Library/Caches`, `~/.cache`, `~/.npm`;
3. last, `(deny file-read* file-write* …)` on `~/.ssh`, `~/Library/Keychains`, Arslan's data folder (database,
   secrets, api token), `~/.arslan`, `~/.arslan-updater.key`, `~/arslan-signing-backup`.

Seatbelt applies the last matching rule (measured 2026-10-03), so step 3 holds even inside an allowed folder.
Paths are resolved first (seatbelt matches real paths) and JSON-quoted. Wrap-up (offline) mode adds
`(deny network*)` to the same profile.

**Who decides.** The model never chooses whether a command is sandboxed. `terminal_exec.OUTSIDE_SANDBOX` is a
context variable that only the tool loop sets, in three cases, each after a click:
- **Asked up front:** `run_command {command, outside_sandbox: true, why}`, for a command the model knows writes
  elsewhere (moving files out of Downloads, `brew install`). It always shows a card, even for a command that
  would otherwise just run. If the command also needs its usual card, one card covers both.
- **Stopped by the sandbox:** the run failed and its output says "Operation not permitted" (EPERM, which is what
  seatbelt returns). The card says the sandbox stopped it and that running it again starts it from the
  beginning. "Run outside the sandbox" re-runs the same command once.
- **For the rest of this conversation:** the checkbox on either card. From then on, commands in this
  conversation run outside the sandbox. This is kept in memory only (`command_sandbox.grant`), never saved.
  The usual cards for deleting, sending or installing still appear.

Without a window to click in (scheduled tasks), a stopped command stays stopped and the model is told why.
Background jobs ask through their cards, as they do today.

**Switch.** Settings → Advanced → "Run commands in a sandbox" (`terminal_sandbox_enabled`, on by default). Off
means the 0.1.50 behaviour.

**Where seatbelt is missing or cannot start** (not macOS, or Arslan itself already inside a sandbox, so it cannot
nest): commands run as in 0.1.50, the result says `sandbox: "unavailable"`, and the model is told. This is
deliberately not fail-closed: the app ships only on macOS, where the probe succeeds, and refusing would break
development on Linux and the nested bench without protecting a user. The availability probe runs once per process.

**What the model is told.** The tool description says where commands may write, what they cannot read, and how
to ask. A stopped result carries `sandbox_denied: true` and a note that names the writable folders.

## Rest of P3

- **Data vs instructions** (P3 item 2): web pages, files and tool output are already wrapped as untrusted data
  (`wrap_external`, `GUARD_NOTE`). Open question for the user: should `remember` in a turn that has read external
  content become a proposal (accepted in the proposal box) instead of a direct write? Recommended: yes for facts,
  no for notes, because the book's warning (persistent memory amplifies an injection) applies to facts that
  steer later turns. Not built until decided.
- **Irreversible outward actions** (item 3): already preview → click → run. Exact repeats are refused by the task
  journal (`task_action_already_completed` / `task_reconciliation_required`), and tool calls are never retried
  automatically. No change.

## Tests

- Pure: the profile's rule order, quoting, offline variant, the denial detector, mode selection.
- macOS only (marker + CI count): writing outside the folder is refused and flagged; writing in the folder and
  temp works; a protected folder cannot be read even when it sits inside a writable one; `~/Library/Keychains`
  cannot be listed; offline plus workspace blocks the network and still writes; a nested `sandbox-exec` is
  detected as a stop.
- Loop: up-front request → card → run outside; stopped → retry card → re-run outside / declined → stopped result
  with note; no window → no card; checkbox → later commands in that conversation run outside, other
  conversations do not; switch off → never sandboxed.
- Paid acceptance (T1–T6 × 3 against Hermes, plus counting cards so interruptions do not rise noticeably) needs a
  budget nod. Not run in this step.
