# ASK1: the default goes back to asking only when a command is risky, and scheduled runs get commands back

| | |
|---|---|
| Decided | The user, 2026-11-04 and 2026-11-07, relayed by ④参谋: after the reset, closing the sandbox and command-card chain comes first, so the default returns to asking only when a command is risky. Both gaps below get cards and go to ③Hands. |
| Version | v0.1.64 (must: it closes the chain) |
| Lane | ③Hands |
| Review | effort=max for both PRs (command policy, the sandbox path and a settings migration, `docs/sessions.md` §5) |
| Order | ASK1-a after S2a-3 and SBX-8. ASK1-b after ASK1-a and HR's e rule. |
| Size | Two PRs, about +150 product lines in all, plus tests. One migration each (numbers from ②Main; main ends at 0086). |

## The two gaps

1. **Nothing owns the flip.** The plan says "ask only when risky" comes back (README §4's chart; SBX card, "Measure on a real Mac"). No card does it:
   - SBX-8 "does not change Settings or the default";
   - no SBX PR changes `shell_confirm_policy`'s default (SBX card, B-1 in Acceptance);
   - S2a-3's rebase and S5a only re-offer the setting without the known-issue sheet.
2. **S2a-3's PR4 has no owner.** README's S2a-3 row calls it unclaimed. Scheduled runs have had no commands since S64-0.

## Where it stands today

- **The setting:** `settings_service.shell_confirm_policy` reads `ask_all` unless the stored value is exactly `ask_risky`. `tool_loop.py` asks for every command when it reads `ask_all` (`_asks_for_everything`, `:1168`, used at `:1674`).
- **The layer-③ no-card branch** is reached only under `ask_risky`. Audit B-1 keeps it off until SBX-M has measured the profile on a Mac, and SBX-8 is the measurement allowed to reopen it (SBX card).
- **Migration 0070** moved a stored `ask_risky` to `ask_all`, once, and left `shell_policy_switch_notice = pending` for existing installs. Its docstring and the known-issue sheet (`web/src/components/settings/AdvancedSection.tsx:377`) both say `DELETE-BY: v0.1.64, when S2a-3 and #406 land`.
- **Scheduled runs:**
  - every fire starts as having read outside content: `untrusted.carried(True)` at `server/services/scheduler.py:433`, marked `DELETE-BY: v0.1.64, with S2a-3 PR4`;
  - a step that needs an OK is refused and the model is told (`permissions._UNATTENDED`, `permissions.py:104`);
  - under `ask_all` that is every command;
  - the runs' "could not ask" entries wait on the user (INB5a, migration 0084).

## ASK1-a: the default

- An unset `shell_confirm_policy` reads as `ask_risky`. Unknown spellings still read as `ask_all`: anything unreadable stays strict.
- **A stored `ask_all` stays.** ⓪Plan's recommendation, for the user to confirm at the PR: the store can't tell a choice from 0070's move. 0070 moved toward strict when in doubt, and moving away from strict when in doubt is the opposite call. Existing installs with a stored `ask_all` get one note saying what changed and where to switch.
- **Delete, with their `DELETE-BY` lines:** the known-issue sheet, `shell_policy_switch_notice` and its text. Old "pending" rows are cleared in the migration.
- **Keep the migration file `_0070`:** it stays in the chain. Only its notice block and its `DELETE-BY` line go.
- **Gate:**
  - SBX-8's report is on main and doesn't argue against this, and S2a-3 is on main. If SBX-8 argues against it, stop and take it to the user.
  - **The known issue is closed, not just its sheet.** The sheet warns about a real gap: #406 closed unmerged on 2026-10-24, and it covered `cd` plus `rm` of a relative name running with no card. Before the sheet goes, the PR body names what closes that gap (S2a-3, or #686 for Trash and protected targets) with a test, or #406 is reopened.
- **Markers this PR clears:** `_0070:21`, `settings_service.py:26`, `ShellPolicySwitchNotice.tsx:13`, `AdvancedSection.tsx:377`, and the locale strings they use. They name "S2a-3 and #406" today.

## ASK1-b: scheduled runs

- **Replace `carried(True)`.** `scheduled_tasks.outside_seen` records whether the turn that wrote or last changed the prompt had read outside content (the user's decision of 2026-10-28, README's S2a-3 row). It is sticky: an edit can set it, never clear it. Existing rows migrate to true, because nobody knows. A fire starts from the column.
- **What a run may do.** README's row says read-only commands. ④参谋 recommends going further, and this is ⓪Plan's reading of it:
  - a scheduled run runs what would run without a card under `ask_risky`, inside the sandbox;
  - anything that would ask is refused and listed (`_UNATTENDED`, INB5a's entries);
  - with `outside_seen`, S2a-1's rule holds: offline, under the outside floor.
- **Why this needs HR's e rule first.** A run that can write can leave a file that runs later: a git hook, an editor task file, `.envrc`. An unattended write is exactly that case. Without HR's e rule on main, ASK1-b stops at read-only, as README's row says.
- **The effort=max review decides this.** If it doesn't support going past read-only, ship read-only, and ⓪Plan takes it back to the user.
- **A stored `ask_all` is honoured in a scheduled run too:** every command would ask, so every command is refused and listed. The refusal says where to switch. The user chose to see every command; a schedule doesn't override that.
- **Delete** `carried(True)` and every marker that says "scheduled runs get commands back with PR4", and the code each one holds up: `arslan.py:762,1568,1588`, `tool_loop.py:1271,1485`, `schedule_tools.py:12`, `heartbeat.py:7`, `scheduler.py:396,429`, `test_scheduled_run_no_command.py:7`, `locale-parity.test.ts:76`, `schedule-card-no-commands.test.ts:13`, `ScheduleGrantCard.tsx:78`, and the locale strings they use.

## References

- Claude Code runs sandboxed commands without a prompt in its auto-allow mode: [sandboxing](https://code.claude.com/docs/en/sandboxing).
- Codex's default runs inside its workspace sandbox and asks when a command needs to leave it: [security](https://developers.openai.com/codex/security).
- Beyond what was asked, listed for the user to decide and not built: a per-schedule "may run commands" switch.

## Raw material

The `file:line`s above, and the SBX card's B-1 and SBX-8 sections. SBX-8's card counts per task on the merged stack are the numbers this card has to live with.

## Method

- **Red tests first:**
  - unset reads `ask_risky`; a stored `ask_all` and unknown spellings read `ask_all`;
  - the migration on a fresh install, on stored `ask_all`, on stored `ask_risky`, on a pending notice, run twice;
  - `outside_seen`: recorded, sticky, migrated to true, read at fire;
  - a scheduled run under each policy, with and without `outside_seen`: runs, refuses and lists, offline.
- **Mutants** on every branch of the above.
- **Keep both real-seatbelt suites green.** A scheduled command that runs does so inside the sandbox (a test, not a read of the code).

## External evidence

- CI run ids on both heads.
- SBX-8's report before ASK1-a.
- The STY2 and M64 benches don't regress with the new default.
- **The user's real Mac, before the tag:**
  - a new install asks only for risky commands;
  - an existing `ask_all` install keeps it and shows the note once;
  - a scheduled task runs a command, and one that would ask shows up in the list.

## Not covered

- Other agents' scheduling models are not compared command by command.
- Commands started by a background job are unchanged; they follow the same policy read.
