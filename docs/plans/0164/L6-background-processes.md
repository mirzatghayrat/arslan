# L6: background processes and process tools

| | |
|---|---|
| Status | **Design. Not started.** Card first (STATUS, 2026-11-11 "should" items). No product or UI code in this PR. The open questions are open, awaiting the user; the reviewer's and ⓪Plan's recommendation is at the end. |
| Version, tier | v0.1.64, should (README §1.1 and the row at README:100). A new safety surface, built only after the SBX chain (README:257). |
| Lane | ②Main builds (README:299). Each PR from main, not stacked, about 400 product lines. Review effort per PR in "Slices": max for any PR that touches the gate, the sandbox launch, or what kills processes. |
| Depends on | SBX-3, SBX-6, SBX-7 merged (the commands profile, the run's TMPDIR and its `.groups` record, the proxy, the denial count). The SBX-8 sitting recorded before L6-3. HR-1 (#813) merged first: it edits `command_gate.py`, `tool_execute.py`, `terminal_exec.py`, `command_sandbox.py` and `sandbox_profile.py`, the same files. S2a-3 (#375, #378, #396) and the SBX-2 adapter deletion (`command_sandbox.py:213`) land first too; L6 rebases on them, not they on L6. |
| Bridge | **No new frame and no new field.** What the phone sees is listed under "Mac and phone". |
| Migration | One table. The number comes from ②Main, after #836's 0092. |

## What it is

A **background process** is a shell command the model started with `run_command(background: true)`. It runs after the call returns, its output goes to a bounded buffer and a log file, and the model and the user can list it, read it, wait for it and stop it. It is the same command, through the same gate, in the same sandbox profile, as a foreground command; only its lifetime is longer, and that lifetime is bounded, recorded and visible.

Today nothing like it exists on purpose, but one exists by accident: `cmd > log 2>&1 &` (or `nohup`, or a dev server) returns at once and leaves its process running, unlisted, unstopped by Stop, by quit or by restart. `run_temp.py:9-13` names this case. L6 replaces the accident with a designed path and then closes the accident (L6-2b).

## Reference (mainstream agents, pinned)

| Agent | Start | List / read / input / stop | Lifetime | Sandbox |
|---|---|---|---|---|
| Codex | `exec_command` returns a session id after a yield of 250 ms–30 s ([mod.rs:68-77](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/unified_exec/mod.rs#L68-L77)) | `write_stdin` reads and writes; 1 MiB head and tail buffer (same lines). Input to a live terminal is reviewed against its launch permissions; a policy change never alters a running process's sandbox, and drift needs a fresh approval or a new terminal ([stdin_approval.rs:1-5](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/unified_exec/stdin_approval.rs#L1-L5), [:120-149](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/unified_exec/stdin_approval.rs#L120-L149)) | Per session: survives an interrupt, closed by an explicit op and at shutdown ([handlers.rs:62-67](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/session/handlers.rs#L62-L67), [:315-346](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/session/handlers.rs#L315-L346)). Cap 64, LRU prune that spares the 8 newest ([process_manager.rs:1764-1790](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/core/src/unified_exec/process_manager.rs#L1764-L1790)) | Same seatbelt as foreground. Local listening is opt-in ([seatbelt.rs:320-323](https://github.com/openai/codex/blob/9018f3a3b021082ef186ddd6503c0b4fd7a26260/codex-rs/sandboxing/src/seatbelt.rs#L320-L323)) |
| Claude Code (closed source; [docs](https://code.claude.com/docs/en/tools-reference#background-commands)) | `run_in_background` on Bash; a foreground command that hits its timeout moves to the background | `/tasks` lists, `Read` the output file, `TaskStop` stops, `Monitor` streams lines | Outlives the reply; unattended sessions cap at 30 min default, 2 h max | Same sandbox as foreground; listening is opt-in (`network.allowLocalBinding`, [sandboxing docs](https://code.claude.com/docs/en/sandboxing)) |
| OpenClaw | `exec` with `background` or `yieldMs` (10 s) ([doc:20-33](https://github.com/openclaw/openclaw/blob/85e9a2f2071e185ba94cc88cbc8d805e20715a53/docs/gateway/background-process.md?plain=1#L20-L33)) | `process` poll / log / write / kill; 200,000-char cap; finished sessions kept under a TTL, 50 at most ([:42-43](https://github.com/openclaw/openclaw/blob/85e9a2f2071e185ba94cc88cbc8d805e20715a53/docs/gateway/background-process.md?plain=1#L42-L43), [:69-71](https://github.com/openclaw/openclaw/blob/85e9a2f2071e185ba94cc88cbc8d805e20715a53/docs/gateway/background-process.md?plain=1#L69-L71)) | Stop cancels the request's yielded commands; exit wakes one turn, with current permissions able to tighten the captured ones ([:47-55](https://github.com/openclaw/openclaw/blob/85e9a2f2071e185ba94cc88cbc8d805e20715a53/docs/gateway/background-process.md?plain=1#L47-L55)). Ends with the gateway unless opt-in `durable` (Linux systemd) | Per-command proxy access, revoked on exit, kill or shutdown ([:40](https://github.com/openclaw/openclaw/blob/85e9a2f2071e185ba94cc88cbc8d805e20715a53/docs/gateway/background-process.md?plain=1#L40)) |
| Hermes | `terminal(background=true)` | poll / log / wait / kill, 200 KB rolling buffer, cap 64 ([process_registry.py:1-4, 60-65](https://github.com/NousResearch/hermes-agent/blob/9373dc1e315a68446f9767afd7acd15d4c0642b8/tools/process_registry.py#L1-L65)) | JSON checkpoint with a PID-safe start-time check for crash recovery ([checkpoint.py:14](https://github.com/NousResearch/hermes-agent/blob/9373dc1e315a68446f9767afd7acd15d4c0642b8/tools/process_registry_checkpoint.py#L14)) | Host unless a sandboxed backend |
| OpenHands | One tmux session; `is_input` sends text or keys to the running command ([definition.py:102-113](https://github.com/OpenHands/software-agent-sdk/blob/5ff99f1b6ca28f7d16870b69f57a31351e59bcd0/openhands-tools/openhands/tools/terminal/definition.py#L102-L113)) | Read by sending an empty command | The container's | The container is the sandbox |
| Roo / Cline | Terminals keep running after a task closes ([TerminalRegistry.ts:211-263](https://github.com/RooCodeInc/Roo-Code/blob/b867ec9145750d0ae1ff7f02d35406e9bf2a0b16/src/integrations/terminal/TerminalRegistry.ts#L211-L263)); Cline has a cancel for its background command ([cancelBackgroundCommand.ts:4](https://github.com/cline/cline/blob/c5df41f937c496ce8c8e689ba58776593c703dfa/apps/vscode/src/core/controller/task/cancelBackgroundCommand.ts#L4)) | Unretrieved output | Editor's | None |
| Goose | No background: killed at its timeout, output capped at 50,000 bytes ([shell.rs:161-199](https://github.com/block/goose/blob/721edae7284910176fb5d32d6c332aabcb1f738a/crates/goose/src/agents/platform_extensions/developer/shell.rs#L161-L199)) | — | — | — |

**Taken:** a flag on the existing tool (all of them); one process tool with actions (OpenClaw, Hermes); head-and-tail buffer and a log on disk (Codex, Hermes); the launch sandbox fixed for life and drift handled by a new start, not by widening (Codex); a recorded identity with start time so a reused pid is never killed (Hermes); exit wakes one turn (OpenClaw, Hermes); unattended caps of 30 min and 2 h (Claude Code); local listening off unless opted in (Codex, Claude Code).
**Rejected:** silent LRU pruning of a live process (Codex): a process the user approved is never killed to make room; the start is refused instead. Durable processes across restarts (OpenClaw): nothing survives Arslan. Free stdin (OpenHands): see Q2. Auto-move at timeout (Claude Code, OpenClaw): see Q1.
**Listed for the user, not built:** per-process proxy accounting and revocation (OpenClaw) (Q7).

## Raw material (re-pinned on main `c8163075`)

Every `file:line` below was re-read at `c81630750d3b`. Between the first pin (`3b8168f0d`) and it, of the files cited only `shell_grammar.py` and `terminal_policy.py` changed, and the cited lines did not move.

- `server/services/terminal_exec.py`: limits 5–600 s, default 120 (`:39-41`); output read while it runs, 8 MB per stream, head and tail (`:47`, `_Capped :89-122`); stdin is `/dev/null` and the command gets its own process group (`:213-216`); the group is killed on cancel (`:226-231`) and on the time limit (`:232-236`), **but not when the shell exits normally**, so a `&` child lives on. `DRAIN_AFTER_KILL_S` (`:48-50`) already notes a child that left the group.
- `server/services/run_temp.py:9-13, :71, :86, :121`: each command's process group is recorded next to the run's TMPDIR; boot's `sweep()` (`server/main.py:405`) removes folders whose groups are gone. It kills nothing.
- `server/main.py:548-591`: shutdown stops the scheduler, MCP, the browser and the proxy (`:587`); no command process is stopped.
- `server/services/sandbox_profile.py:173`: signals go only to the same sandbox. `:196-209`: online, TCP out only to loopback and the proxy port; `network-bind` and `network-inbound` are denied, so a sandboxed dev server cannot listen today.
- `server/orchestrator/command_gate.py:216` `check`: forbid before any card (`:242-246`), the conversation's outside grant (`:275`), an unread command runs offline (`:329-332`), the network after outside content (`:375-378`). `CommandPlan :199-211`.
- `server/orchestrator/tool_execute.py:47-63`: the outside grant is read again at execute, because it may have been taken back while a card waited. A process that runs for an hour needs the same idea for its whole life.
- `server/registry/tool_defs/terminal.py:8-54`: `run_command`, offered when `offer.shell and not offer.nobody_to_ask` (`:51`), `gate=command_gate.check`, `Traits(effect="external_write", parallel=False, outside=False, replay_safe=False, saves=False)` (`:54`). `server/registry/tool.py:85-120`: `Traits`, `Tool.gate`.
- `server/services/background_jobs.py`: jobs are agent runs, not processes (3 slots, `:28`); a job's task grants are forgotten when it ends (`:323`); jobs never survive a restart and each conversation is told once (`:515-555`). L6 copies that boot pattern.
- `server/services/terminal_policy.py:94` forbids the classic fork bomb by text only. `server/services/shell_grammar.py:107-111`: `nohup` is a plain wrapper; `setsid`, `tmux`, `screen` are launchers. `disown` is in neither set: it is only in `_OTHER_BUILTINS` (`:88-91`), which makes a command not understood (`:698-699`), never a detaching form.
- `server/services/hard_rules.py:95-97, :166-169`: `RUN_LATER` is empty until HR-1 (#813) fills it with the kernel deny in the commands profile.
- `server/api/phone.py:297-316`: the phone's status lists running jobs as `job_update` bodies; nothing about processes. `web/src/components/reply/ProcessList.tsx` draws a reply's steps, not OS processes: the new panel must not take its name.

## Design

**Start.** `run_command` gains `background: boolean` (default false). No new start tool: the one gate, card and sandbox stay the only way a command runs. The call returns after at most 2 s with `{"process": "p3", "state": "running" | "exited", "output": <first lines>, "log": <path>}`; a command that fails at once reads like a failed foreground command. `timeout_s` with `background` means the process's life: default 1,800 s, max 7,200 s (a separate range in the schema).

**One process tool,** `process(action, id?, until?, wait_s?)`, in a new family `tool_defs/processes.py`:
- `list`: this conversation's processes: id, the card's summary of the command, state, started, time left, sandbox and online or offline, exit code.
- `read`: new output since this conversation's last read (a cursor), at most 30,000 characters (`MAX_OUTPUT_CHARS`), repeats folded; more than that says how much was skipped and points at the log for `read_file`.
- `wait`: blocks up to `wait_s` (max 30 s, as Codex) until the process exits or plain text `until` appears (no regex). Counts against the turn's budget.
- `stop`: SIGTERM to the group, 3 s, SIGKILL; recorded as stopped by the model.
- **No input.** stdin stays `/dev/null` (Q2).

**Registry fit (LOOP1).** `process` is one `Tool` with `gate=tool_gates.process_gate` (the id must belong to this conversation; anything else reads as "no such process"; refused in a replay). Offered exactly when `run_command` is, plus `not offer.scheduled`; no new `Offer` field. Traits: `effect="local_write"` with `task_service.effect_of` grading `list`, `read`, `wait` as reads by action (as `run_command` is graded by its command); `parallel=False` (the read cursor is shared state); `outside=False` with `untrusted.counts_as_external` judging per call: `read` and `wait` of a process that started online count as outside content (as `run_command` does at `untrusted.py:93-98`); `replay_safe=False`; `saves=False`. The table dump (`test_loop1_tool_table.py`) changes on purpose in L6-3 and the PR gives both hashes. Successful `list`, `read`, `wait` are not reply steps (like `run_process.JOB_TOOLS`); `stop` is.

**Lifetime: per conversation, bounded, never across a restart.**
| Event | What happens |
|---|---|
| Exit | State, exit code and time recorded at once; an exit note posted (see "Exit") |
| `process stop`, the user's Stop on its row | Group stopped, recorded with who stopped it |
| The turn that started it is stopped | Its processes stop with it (OpenClaw). Earlier turns' processes keep running |
| A background job or sub-session ends | Its processes stop when its task grants are forgotten (`background_jobs.py:323`) |
| Conversation deleted or archived | Its processes stop |
| Life limit (default 30 min, max 2 h) | Stopped, recorded as `time_limit`, the model told why |
| A profile input changes (below) | Stopped, recorded as `settings_changed` |
| App quits | All stopped before the proxy shuts down; recorded as `app_quit` |
| Arslan crashes or is killed | The keeper (below) stops the group when the server is gone; the boot pass records `app_restarted` and tells each conversation once |

**State is recorded when it happens.** A row in a new `background_process` table: conversation, run, task or job, turn, command, card summary, sandbox mode, network, the profile fingerprint, log path, then pid, group and the process start time written right after spawn, then the end state. **The start-time guard is new code:** nothing on main records a process's start time, and `run_temp._alive` (`:86`) keeps a reused group id rather than telling it apart. Boot reads rows and acts; it never infers state from logs or the transcript. Restart matrix, one test each: crash before spawn (row `starting`, no pid: marked `never_started`); after spawn, before the pid is written (the keeper stops the group; boot marks it `app_restarted`); while running (the keeper stops it; boot finds the group gone, or alive with the same start time and stops it, never a group whose start time differs); after exit before the row update (boot marks `ended_unknown`).

**The keeper.** Each background process is launched under a small stdlib-only keeper that Arslan starts (outside the sandbox, like the server; the command under it inside its profile as today). The keeper holds the read end of a pipe whose write end only the server holds: end of file means the server is gone, by quit or crash, and the keeper stops the group. This closes the window between spawn and record, and a quit where shutdown hooks never ran.

**Limits.** 4 running per conversation, 8 for the app; a start over the cap is refused with the list, never by pruning. Output: 1 MiB head and tail in memory per process; the log on disk capped at 64 MiB, head and tail kept beyond it. Time: as above. CPU: background processes run at `nice 10`. Process count: a watchdog every 2 s counts each tracked group and stops one above 256 processes (`fork_limit`).

## Safety model

**Same sandbox, fixed at launch.** A background command runs under exactly the commands profile its foreground twin would get for the same inputs (L6-2 tests the bytes are equal): writes only in the working folder, the run's TMPDIR and caches; Arslan's data, keys and HR-1's run-later files denied by the kernel; network only through the proxy, or none. No listening (`sandbox_profile.py:209`; deferring Q3 is recommended, not decided). The profile cannot be tightened on a live process, so anything that would build a different profile now stops it instead (Codex's rule): the fingerprint of the profile's inputs (working folder, folder access, project folders, sandbox on or off, system certificates, trusted devices, shell on or off) is recorded at start and checked on each such settings write and every 10 s as a backstop.

**The seatbelt profile is the containment boundary, not process-group tracking.** Writes are confined to the profile's roots, bind and inbound are denied, the network goes only through the proxy, and signals reach only the same sandbox (`sandbox_profile.py:173`). Group tracking only decides how long a process lives, and what L6 lists and stops. A child that leaves the process group (it calls `setsid` itself, or double-forks) keeps running sandboxed until it exits by itself: Arslan no longer lists it, stops it or times it. **That is a liveness gap, disclosed, not a containment gap.** It is no worse than today's `cmd &` (`run_temp.py:9-13`).

**The gate decides at start, unchanged.** `command_gate.check` runs as for any command: forbid refuses, `ask` shows the card, `run` runs, `unreadable` runs offline in the sandbox, offline after outside content. The card's existing text says "keeps running in the background until stopped, at most 30 min" (in the server-built summary, LOOP1 d1 #817, or the purpose line before it): no new field. Then the background rules, in `command_gate` after the verdict:
- **Outside the sandbox:** always the outside card, even with the conversation's grant, and that answer is this time only (it joins `hard_rules.NEVER_AUTO`). An outside background process is stopped when that conversation's outside grant is forgotten too.
- **Nobody to ask** (a scheduled run, the heartbeat): never; not offered and refused. Also refused during a job's wrap-up (`terminal_exec.OFFLINE` set by the loop).
- **Detaching words** at the top level (`&` at the end, `nohup`, `setsid`, `disown`, `tmux`, `screen`): refused with "use background: true instead", so the process stays in the group L6 tracks. **Planned grammar work (L6-3):** a named detaching set in `shell_grammar`. Today `disown` only makes a command not understood (`:88-91`, `:698-699`), and `&` is not named at all.
- **Caps** over the limit: refused with the list.
**Later tool calls** don't run a command, so nothing is re-judged by the command policy; `process_gate` checks ownership, and the fingerprint check runs first, so a stale process is stopped rather than read. With no input there is no second command to judge (Q2).

**Run-later (HR-1).** A background process keeps the commands profile for its whole life, so HR-1's kernel deny on hooks, CI and agent settings holds the whole time, not only at start. Outside the sandbox it keeps the minimal profile and HR-3's rules. A background process never restarts itself or anything else: no launch agents, no durable mode.

**Unattended.** Scheduled runs never start one. A background job may, and its processes end with the job. An exit-woken turn (below) is an ordinary turn: its cards wait for the user, and nothing is approved automatically.

**Threat cases.**
| Case | What holds |
|---|---|
| A long-lived listener | The kernel denies bind and inbound in the commands profile; outside the sandbox it needs the this-time outside card that says it keeps running; the life limit ends it. Loopback listening (Q3, L6-7) is open; deferring it is recommended |
| Exfiltration over time | The network is decided once at start by the same gate (offline after outside content or when unread); no stdin, so a model that later reads outside content cannot steer a running process; online or offline is shown on its row; the proxy's site rules apply all its life; the life limit ends it. Residual: an online process can send through the proxy until stopped (Q7) |
| Fork bomb | The text form is forbidden (`terminal_policy.py:94`); the group watchdog stops a group above 256; `nice 10`. Residual: a fast bomb can load the Mac for up to 2 s, as a foreground command can today for its whole time limit |
| Outlives a revoked grant | Outside: no grant ever starts one, and forgetting the grant stops it. Job end stops the job's. Any profile input change stops all affected. Shell switched off stops all |
| Escapes tracking (`setsid`, a double fork) | Contained by the profile, as above. Detaching words refused at start; L6-2b stops a foreground command's group when it returns. Residual liveness gap: a program that calls `setsid` itself leaves the group and runs sandboxed until it exits. It may lose the network when the proxy stops at quit (unverified, below) |

## Exit

On exit the row is updated, then one note is posted in the conversation: the command's summary, exit code, duration, and the last 5 lines framed as outside content (the S64-0b pattern). The Mac gets the existing `desktop_status.push` notice. If the process was started by a chat turn and no turn is running there, the exit **wakes one ordinary turn** in that conversation with the note as its input (Q4); a process started by a job does not wake anything (the job waits on it itself).

## Mac and phone

**Mac: a new panel, so the mock comes first, then the user approves; ⑥Helper or ②Main builds.** The `run_command` step in a reply shows "running in the background" with a Stop button. A running-process chip in the conversation header opens **the Running panel (name set by the mock)**: summary, started, time left, sandbox and network, last line, Stop, Stop all. Its component name must not clash with `web/src/components/reply/ProcessList.tsx`, which draws a reply's steps. Quitting the app stops everything without asking. Nothing new on the island or in Settings.

**Phone, with no frame change:** the start appears as the reply's step through the run-step reads the phone already has (`phone_details`, `phone_reads`); a card for a background start is the existing card with the extra sentence; the exit note is a conversation message and its push is the existing one; the user stops a process by asking Arslan in the conversation. A process list or a Stop button on the phone is a frame change the user merges, so it is not in this card (Q6).

## Method

- **Red first, every PR.** L6-0 (tests only) pins today's leak as strict expected failures with `raises=AssertionError` (`xfail(strict=True)`, the SBX convention): a foreground `sleep 600 >/dev/null 2>&1 &` leaves a live group after the call; Stop does not end it; shutdown does not end it. L6-1 and L6-2b flip them.
- **Tests per PR:** the restart matrix (four moments, a fake server death through the keeper's pipe); the gate table for a background start under each verdict (forbid, ask, run, unreadable, outside with and without a grant, nobody to ask, wrap-up, detaching words, caps); profile bytes equal to the foreground twin with `cmp`; a settings change stops the process within 10 s; read is incremental and bounded; wait returns at `until`; a reused pid with a different start time is never killed.
- **Mutants (each PR lists which went red):** background skips `command_gate`; an outside start rides the grant; the keeper ignores end of file; the fingerprint check removed; the cap pruned instead of refused; the cursor not advanced; the boot pass kills without the start-time check.
- **Probes** through `scripts/dev/probe.sh`, on a real Mac: start a 5-minute build in the background, quit from the menu, then `pgrep` finds nothing; kill the server with SIGKILL and the keeper stops the group. Real-seatbelt denial for background starts reuses the existing commands-base p tests by parameter, no new probe kind. If L6-7 is built (Q3 is open), its loopback tests are new probes: Codex writes them, Astra reviews (SBX "Who writes what").

## External evidence

Each PR: the CI run id with all five checks, the macOS job's counts (0 skipped, 0 xfail once flipped), the mutants. L6-3: the table dump's old and new hashes. Bench: the lead roadmap's proof task (a 5-minute build, chat meanwhile, the turn continues when it ends) added to ⓪Plan's M64 run; SMART-5 and STY2 no worse. The user's real-Mac smoke: quit with a process running, and the phone shows the exit note.

## Slices (each from main, about 400 product lines)

| | What | Review |
|---|---|---|
| L6-0 | The leak pinned as strict xfails; the restart matrix as tests against a fake | high |
| L6-1 | The table and records, the keeper, the boot pass with the new start-time guard, stop on quit (before the proxy). No model surface | max |
| L6-2 | The background launch in `terminal_exec`: same wrapper, own group, `nice`, buffer, log, caps, group watchdog | max |
| L6-2b | A foreground command's group is stopped when it returns (Q5) | max |
| L6-3 | `background` on `run_command`, `CommandPlan.background`, the gate's background rules, the grammar's detaching set (with `disown`), the `process` tool and traits, a `process` arm in `untrusted.counts_as_external` (`untrusted.py:93-98`: `read` and `wait` of a process that started online), prompt words, SECURITY.md lines. After the SBX-8 sitting | max |
| L6-4 | Lifetime rules: the fingerprint, turn stop, job and sub-session end, conversation delete, life limit | max |
| L6-5 | Exit note, push and the woken turn | max (it starts a turn) |
| L6-6 | The Running panel (name set by the mock) and its chip, after the mock is approved | high |
| L6-7 | **Only if Q3 says so; deferring is recommended.** Loopback listening for background processes. If built: Codex writes the p tests, Astra reviews, the user merges | max + Astra |

No fallback switch is planned, so no `DELETE-BY:`. If L6-2b ships one, it carries `DELETE-BY: v0.1.65`.

## Not verified (read, not run)

- Whether the proxy binds a new port on each start, so an escaped sandboxed process stays offline after a restart (`sandbox_proxy`'s port choice was not read).
- The keeper's cost on a real Mac (one extra Python process per background command).

## Open questions for the user

1. **Move a foreground command to the background when it hits its limit** (Claude Code, OpenClaw)? Recommended: **no**. Only `background: true`, so the card the user answered said what really runs.
2. **Send input to a running process?** Recommended: **no** in v0.1.64; stdin stays empty. If wanted, each send is a this-time-only card showing the text (Codex re-reviews input).
3. **Let sandboxed background processes listen on this Mac only (dev servers)?** Recommended: **yes**, loopback only, background only, as L6-7 with Codex's tests. Without it a dev server needs the outside card.
4. **Wake one turn when a process ends?** Recommended: **yes**, for chat-started processes, one turn per exit, cards asked as usual.
5. **Stop what a foreground command left running when it returns** (`cmd &` today)? Recommended: **yes** (L6-2b); the model is told to use `background`.
6. **Process list and Stop on the phone** (a Bridge frame you merge)? Recommended: **not now**; the phone sees steps, cards and exit notes, and can ask Arslan to stop one.
7. **Per-process network accounting and cut-off at the proxy** (OpenClaw)? Recommended: **not built**; listed for v0.1.65 talk. Limits stay 4 per conversation, 8 in all, 30 min default, 2 h max unless you say otherwise.

## Recommended (reviewer and ⓪Plan); awaiting the user

None of these is decided. The reviewer and ⓪Plan recommend the card's answers to all seven, except that for Q3 they recommend deferring:
- Q1: no auto-move at the time limit.
- Q2: no input; stdin stays empty.
- Q3: **defer.** L6-7 would not be built now, and a dev server would need the outside card.
- Q4: one woken turn per exit, for chat-started processes (L6-5).
- Q5: a foreground command's leftover group is stopped when it returns (L6-2b).
- Q6: no process list or Stop on the phone; no Bridge frame.
- Q7: no per-process proxy accounting. The limits as proposed: 4 per conversation, 8 in all, 30 min default, 2 h max.
