# ASK1: the default goes back to asking only when a command is risky, and scheduled runs get commands back

| | |
|---|---|
| Decided | The user, 2026-11-04 and 2026-11-07, relayed by ④参谋: after the reset, closing the sandbox and command-card chain comes first, so the default returns to asking only when a command is risky. Both gaps below get cards and go to ③Hands. The user's calibration of 2026-11-07, relayed by ④参谋, answers the open points (existing installs, old scheduled tasks, sandbox first) and is folded in below. |
| Version | v0.1.64 (must: it closes the chain) |
| Lane | ③Hands |
| Review | effort=max for both PRs (command policy, the sandbox path and a settings migration, `docs/sessions.md` §5) |
| Order | ASK1-a after S2a-3 and SBX-8. ASK1-b after ASK1-a and HR's e rule. HR doesn't wait for ASK1. |
| Size | Two PRs, about +350 product lines in all (ASK1-b's wording runs through six locales), plus tests. One migration each, reserved by ②Main: 0087 (the notice flag only) and 0088 (`outside_seen`, and the settings key that tracks the scheduled-task note, set to `pending`). ASK1-a also carries the sandbox-first change below, so ③Hands re-estimates in its 10 lines to ⓪Plan before code (`docs/sessions.md` §5). |

## The two gaps

1. **Nothing owns the flip.** The plan says "ask only when risky" comes back (README §4's chart; SBX card, "Measure on a real Mac"). No card does it:
   - SBX-8 "does not change Settings or the default";
   - no SBX PR changes `shell_confirm_policy`'s default (SBX card, B-1 in Acceptance);
   - S2a-3's rebase and S5a only re-offer the setting without the known-issue sheet.
2. **S2a-3's PR4 has no owner.** README's S2a-3 row calls it unclaimed. Scheduled runs have had no commands since S64-0.

## Where it stands today

- **The setting:** `settings_service.shell_confirm_policy` reads `ask_all` unless the stored value is exactly `ask_risky`. `server/orchestrator/tool_loop.py` asks for every command when it reads `ask_all` (`_asks_for_everything`, `:1162`, used at `:1661`).
- **The layer-③ no-card branch** is reached only under `ask_risky`. Audit B-1 keeps it off until SBX-M has measured the profile on a Mac, and SBX-8 is the measurement allowed to reopen it (SBX card).
- **Migration 0070** moved a stored `ask_risky` to `ask_all`, once, and left `shell_policy_switch_notice = pending` for existing installs. Its docstring and the known-issue sheet (`web/src/components/settings/AdvancedSection.tsx:377`) both say `DELETE-BY: v0.1.64, when S2a-3 and #406 land`.
- **Scheduled runs have no commands at all,** whatever the policy says:
  - `tool_loop.py:1482-1488` refuses `run_command` when nobody can be asked, before any rule, grant or policy is read;
  - `arslan.py:1590-1591` doesn't offer the tool;
  - `SCHEDULED_NOTE` (`arslan.py:763`), `SCHEDULED_COMMAND_NOTE` (`tool_loop.py:1273`), the tool description at `arslan.py:1569`, `schedule_tools.py:11` and the grant card (`ScheduleGrantCard.tsx:78`, `schedgrant.unattended`) all say so;
  - every fire also starts as having read outside content: `untrusted.carried(True)` at `server/services/scheduler.py:433`;
  - other steps that need an OK are refused (`permissions._UNATTENDED`, `permissions.py:104`) and wait on the user as "could not ask" entries (INB5a, migration 0084).
- **`_nobody_to_ask`** (`tool_loop.py:1268`) isn't specific to schedules: it's any run with no card callback and no card surface. The heartbeat is one (`heartbeat.py`: an ordinary scheduled task with `target="arslan"`, whose prompt comes from Settings).

## ASK1-a: the default

- **New installs:** an unset `shell_confirm_policy` reads as `ask_risky`. Unknown spellings still read as `ask_all`: anything unreadable stays strict.
- **Existing installs (the user, 2026-11-07, relayed by ④参谋):** a stored `ask_all` stays. An unset policy moves to `ask_risky`. Both get one note saying how to switch. **An install that already stores `ask_risky`** (chosen again after migration 0070) sees no change, so it gets no note: the migration sets the notice only where the stored policy isn't `ask_risky` (⓪Plan, from #720's review; the max review checks it). The migration (0087) writes nothing to the policy: it only sets the notice, for existing installs (`runner.EXISTED_BEFORE_THIS_BOOT`, as 0070 does), and the window picks the note's text from what the policy reads.
- **One note, tracked by the same key.** `shell_policy_switch_notice` stays as the mechanism, with new text: the migration sets it to `pending` on existing installs (a pending old notice is replaced, not shown twice), and the window writes `seen`. Its `DELETE-BY` moves to v0.1.65.
- **Delete, with their `DELETE-BY` lines:** the known-issue sheet (this card owns its removal, not S2a-3's rebase) and 0070's notice text.
- **Keep the migration file `_0070`:** it stays in the chain. Only its notice block and its `DELETE-BY` line go.
- **Gate:**
  - SBX-8's report is on main and doesn't argue against this, and S2a-3 is on main. If SBX-8 argues against it, stop and take it to the user.
  - **The known issue is closed, not just its sheet.** The sheet warns about a real gap: #406 closed unmerged on 2026-10-24, and it covered `cd` plus `rm` of a relative name running with no card. Before the sheet goes, the PR body names what closes that gap (S2a-3, or #686 for Trash and protected targets) with a test, or #406 is reopened.
- **Markers this PR clears or moves:** `_0070:21`, `settings_service.py:26`, `ShellPolicySwitchNotice.tsx:13`, `AdvancedSection.tsx:377`, and the locale strings they use. They name "S2a-3 and #406" today.

## Sandbox first: what `ask_risky` means (the user, 2026-11-07, relayed by ④参谋)

This is what ASK1-a turns on by default, but it lands earlier, with ③Hands' S2a-3 work (design OK'd by ⓪Plan, 2026-11-07). The denial change loosens nothing and can land at any time. The rest takes effect only after SBX-6a and SBX-4a are on main, in S2a-3's wire step.

- Inside the sandbox a command that isn't dangerous runs without a card. A card appears only for leaving the sandbox, a real danger, or an explicit rule.
- A sandbox denial goes back to the model as a tool result, so it can find another way. No card is made from it; the automatic re-run card goes.
- Asking to leave the sandbox is a deliberate request from the model, with a reason: `outside_sandbox` plus a required `why` on the command tool. Without `why` the model gets an error, not a card. The card shows the reason.
- **The command reader decides the network, not whether a command runs.** With no named rule, a command the reader can't understand runs in the sandbox with no card and offline, with a note saying why. If it needs the network, the model passes `network: true`, which shows the existing network card. Commands the reader understands keep the proxy.
- **Kept:** forbid, named layer ② rules (including on unreadable text), a card when there's no sandbox, S2a-1, and a stored `ask_all`.
- **Exception:** when the working folder is home or contains it, unreadable text still gets a card, because the sandbox doesn't hold there.
- CLS and S5b keep the breakers already on their cards (3 denials in a row in a turn, 20 in total per conversation and per job, then back to cards). The classifier doesn't see tool output, so a denial's text never reaches it. **Those breakers count the classifier's denials in auto mode. They don't cover sandbox stops under `ask_risky`,** so nothing yet bounds a model that keeps hitting the sandbox here. **Open for ⓪Plan before ASK1-a:** either a bound of the same shape on sandbox denials, or a stated reason none is needed (the denial count from SBX-7 is the measure).
- `ask_all` is unchanged: every command still asks.
- References: Codex's `exec_policy.rs` and Claude Code's sandboxing docs (below).

## ASK1-b: scheduled runs

- **Which runs get commands back: only a scheduled task's own fire.** `_nobody_to_ask` is too wide to be the switch. The scheduler's fire sets an explicit signal, and the gate reads that. Every other run with nobody to ask keeps today's refusal, and a test pins it.
- **The heartbeat doesn't get commands back.** ⓪Plan's call, for the max review to check: it brings the user a message and "proposes; the user decides" (`heartbeat.py`), so it has no need for them, and its prompt comes from Settings, not from a turn, so `outside_seen` has nothing to record. Its marker becomes a plain statement with no `DELETE-BY`, and a test pins it.
- **Existing tasks get commands too (the user, 2026-11-07, relayed by ④参谋), with one note.** There is no per-task column and no clearing of standing grants. The note says that scheduled tasks may now run commands inside the sandbox and that anything that would ask is refused and listed. It is shown once on the Scheduled page and tracked the way ASK1-a's note is (a settings key that 0088 sets to `pending` and the window writes `seen`).
- **The grant card says what a run may do.** `schedgrant.unattended`, in six locales: it runs commands that wouldn't need your OK, inside the sandbox; anything that would is refused and listed. `SCHEDULED_NOTE`, `SCHEDULED_COMMAND_NOTE`, the tool description at `arslan.py:1569` and `schedule_tools.py:11` change with it, and the tool is offered to these runs.
- **Replace `carried(True)`.** `scheduled_tasks.outside_seen` records whether the turn that wrote or last changed the prompt had read outside content (the user's decision of 2026-10-28, README's S2a-3 row). It is sticky: an edit can set it, never clear it. Existing rows migrate to true, because nobody knows, so existing tasks run sandboxed and offline; anything that would ask is refused and listed. A fire starts from the column.
- **What a run may do.** README's row says read-only commands. ④参谋 recommends going further, and this is ⓪Plan's reading of it:
  - a scheduled run runs what would run without a card under `ask_risky`, inside the sandbox;
  - anything that would ask is refused and listed (`_UNATTENDED`, INB5a's entries);
  - with `outside_seen`, S2a-1's rule holds: offline, under the outside floor.
- **Why this needs HR's e rule first.** A run that can write can leave a file that runs later: a git hook, an editor task file, `.envrc`. An unattended write is exactly that case. Without HR's e rule on main, ASK1-b stops at read-only, as README's row says.
- **The effort=max review decides this.** If it doesn't support going past read-only, ship read-only, and ⓪Plan takes it back to the user.
- **A stored `ask_all` is honoured in a scheduled run too:** every command would ask, so every command is refused and listed. The refusal says where to switch. The user chose to see every command; a schedule doesn't override that.
- **Delete** `carried(True)` and every marker that says "scheduled runs get commands back with PR4", and the code each one holds up: `arslan.py:762,1568,1588`, `tool_loop.py:1271,1485`, `schedule_tools.py:12`, `scheduler.py:396,429`, `locale-parity.test.ts:76`, `ScheduleGrantCard.tsx:78`, and the locale strings they use. `test_scheduled_run_no_command.py` and `schedule-card-no-commands.test.ts` lose their subject for scheduled tasks; what they pin moves to the runs that keep the refusal.

## References

- Claude Code runs sandboxed commands without a prompt in its auto-allow mode: [sandboxing](https://code.claude.com/docs/en/sandboxing).
- Codex's default runs inside its workspace sandbox and asks when a command needs to leave it: [security](https://developers.openai.com/codex/security).
- Codex decides per command in [`exec_policy.rs`](https://github.com/openai/codex/blob/86b2eca691445e69d0d88c539ea3d41b515e181a/codex-rs/core/src/exec_policy.rs) whether it is forbidden, needs approval or may skip it, and a command leaves the sandbox only when it asks to (`sandbox_permissions`).
- Beyond what was asked, listed for the user to decide and not built: a per-schedule "may run commands" switch.

## Raw material

The `file:line`s above, and the SBX card's B-1 and SBX-8 sections. SBX-8's card counts per task on the merged stack are the numbers this card has to live with.

## Method

- **Red tests first:**
  - an unset policy reads `ask_risky`, on a new install and on an existing one; a stored `ask_all` (kept) and unknown spellings read `ask_all`;
  - the migration on a fresh install, on an upgrade with the policy unset, on stored `ask_all`, on stored `ask_risky`, each with and without a pending notice, run twice: it sets the notice and writes no policy;
  - sandbox first: inside the sandbox a command that isn't dangerous runs with no card; a denial comes back as a tool result and makes no card; leaving needs the model's request with a reason; under `ask_all` every command asks;
  - `outside_seen`: recorded, sticky, migrated to true, read at fire;
  - a scheduled run under each policy, with and without `outside_seen`: runs, refuses and lists, offline;
  - a task from before the migration runs a command sandboxed and offline, one that would ask is refused and listed, and the note shows once;
  - the heartbeat and any other run with nobody to ask: refused.
- **Mutants** on every branch of the above.
- **Keep both real-seatbelt suites green.** A scheduled command that runs does so inside the sandbox (a test, not a read of the code).

## External evidence

- CI run ids on both heads.
- SBX-8's report before ASK1-a.
- The STY2 and M64 benches don't regress with the new default.
- **The user's real Mac, before the tag:**
  - a new install asks only for risky commands;
  - an existing install keeps a stored `ask_all` or moves from unset to `ask_risky`, and shows the note once;
  - a scheduled task runs a command, and one that would ask shows up in the list.

## Not covered

- Other agents' scheduling models are not compared command by command.
- Commands started by a background job are unchanged; they follow the same policy read.
