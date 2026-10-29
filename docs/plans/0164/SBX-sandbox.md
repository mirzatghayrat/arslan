# SBX: a default-deny sandbox, and one sandbox for everything

> Draft by ⓪Plan, 2026-10-28, for the v0.1.64 plan. Revised the same day after ②Main's and ③Hands' reviews on #447 (issuecomment-6465940944, issuecomment-6466034420); their additions are marked "(②Main)" or "(③Hands)". Plan row: `docs/plans/0164/README.md` §3.2, SBX. Code read on `origin/main`: `3759f57b` for the code (unchanged at `11f05434`, which only adds #432's text to `docs/plans/0162/README.md` and `STATUS.md`). Every `file:line` below was read for this card. The #432 text is cited at `11f05434` (`docs/plans/0162/README.md:326-370`), because it is not in `3759f57b`'s copy of that file. The user answered its seven questions the same day ("User decisions" at the end).

| Item | Content |
|---|---|
| Lane | **Changed 2026-10-29: see "Who writes what" below (SBX-2 and every deny-test half go to Codex).** **③Hands** (moved from ②Main on 2026-10-28, both agreeing; ③Hands also does the S2a-3 rebase on the same files). Written at **effort=max**. Reviewed by ②Main with an effort=max reviewer. Codex GPT-6 Astra only for parts that review cannot cover (user, 2026-10-28 evening; v0.1.64 README §1.3); when it is needed, SBX-1 + SBX-2 go together, then the rest one by one. SBX-1 shows the byte-for-byte check of all five profiles, old vs new, with `/usr/bin/diff` or `cmp` (not rtk's diff, which always exits 0). |
| Version | v0.1.64 |
| Tier | Must (user, 2026-10-22, lead roadmap §0.6 item 1; again 2026-10-28, `docs/plans/0164/README.md:43`) |
| Depends on | Nothing in the security chain comes before it. #432 is decided (`docs/plans/0164/README.md:41-43`). S64-0 (#438) is independent. SBX-M (the measurement on a Mac) needs the user at the Mac only to start it; it uses no keys. |
| Merge position | First in the security chain (`docs/plans/0164/README.md:158-164`). **All SBX code PRs merge before ③Hands rebases S2a-3** (#375 / #376 / #378 / #396). S5a comes after SBX and S3 undo. HR comes after SBX and S2a-3. CAP's untrusted-code parts (CAP5, CAP6a, CAP7b, CAP10) and SUB come after SBX; CAP6b is part of SBX. L6 comes after SBX. Any PR that touches `tool_loop.py` goes after the open K-line PRs (`docs/sessions.md` §3). The aim is for SBX not to touch `tool_loop.py` at all (see "Files to change"). Why S2a-3 waits, and which of its PRs really depend on SBX: "Order with S2a-3" below. |
| Gates it moves | Lead roadmap §0.6 item 1 (`docs/plans/2026-10-17-0162-lead-roadmap.md:83-85`). Row D "sandbox" (`lead-roadmap.md:249`). It is the precondition for "ask only when risky" coming back, for the classifier's baseline (CLS, S5b), for S5a, for HR, and for CAP's untrusted-code PRs. R64's security gate. |
| Branches | `claude/0164-sbx1-profile-builder`, `claude/0164-sbx2-deny-default-base`, `claude/0164-sbx3-commands`, `claude/0164-sbx4-python-mcp-checks`, `claude/0164-sbx5-cap6b-caches`, `claude/0164-sbx6-proxy-port` (only if the user picks option N-a in Q1), `claude/0164-sbx7-counts`, `docs/0164-sbx-measurement` (SBX-M and SBX-8 reports) |
| Migration | None expected. The ledger already has a JSON `extra` column (`server/db/models.py:493-517`, field `extra` at `:509`). The local denial count is derived from what is recorded (SBX-7). If SBX-7 finds it needs a column, it asks ②Main for the next free number, which comes after 0075 (0071 Q1, 0072 INB2, 0073 C7c-2, 0074 CAP1b, 0075 CAP1c; `docs/plans/0164/README.md` §6). |

## Who writes what (user, 2026-10-29: the cloud audit's split)

**This section overrides the Lane row, the PR split table's authorship and the Review list below wherever they differ.**

Why: a safety classifier stopped ③Hands' response as it started SBX-2, right after it read this card. Per "Risks and rollback", that is not worked around or reworded, and it is not moved to another Claude session or model. The user then asked the cloud audit (planning audit session, read at main `c83d7ed9`) to judge only how to split SBX-2 … SBX-8 and S2a-3. The user approved the split (relayed by ④参谋, 2026-10-29). Writing work that Claude cannot do because of safeguards goes to Codex (user, 2026-10-28).

| Block | Writer | Reviewed by | Merge rule |
|---|---|---|---|
| **SBX-2**, whole, not split. Which part was stopped is unknown, so giving any part of it to Claude would be a reworded retry | Codex | Astra (highest level), in a new Codex session, never the one that wrote it. Claude reviews only SBX-2's parts with no probe content (CI markers, harness plumbing) | The user merges |
| **SBX-3a, 4a, 5a, 6a**, the build half of each card. 3a: the profile text, wiring to each entry point, `available()`, the private TMPDIR (location, lifetime, boot sweep), tagged writable roots, `in_scope()`, the `deny_write_after_roots` parameter, denial detection beyond EPERM, the SECURITY.md sentences, golden texts, unit tests, and tests that what should run does run. 4a: `run_python`, artifact checks, MCP onto the shared base, deleting `_SEATBELT_PROFILE`, dropping MCP's wholesale `mach-lookup`. 5a: CAP6b's refusal at the `write_file` / `edit_file` layer, the MCP grant exclusion, cache redirection. 6a: the local proxy, and the profile that allows only the proxy port | Claude (③Hands) | ②Main plus an effort=max reviewer, checking that what was built is what the card says. "Is the deny strict enough" belongs to Astra and the p tests | The user merges, after that card's p is green in CI |
| **SBX-3p, 4p, 5p, 6p**, the real-seatbelt tests that what should be denied is denied, for each card's surface (3p the commands base; 4p MCP and Python; 5p links and shared caches; 6p the network surface) | Codex | Astra (highest level) | p may merge first; a waits for p to be green in CI |
| **The system-service allowlist**, including SBX-M's follow-up of ≤ 50 lines. No Claude PR touches it | Codex | Astra | The user merges |
| **SBX-M** | The user or ②Main runs Codex's corpus on the user's Mac. If ②Main runs it, ②Main reads the corpus before running it. Claude writes the report, ids and results only; if that is stopped, Codex writes it | A session other than the report's writer | Report PR |
| **SBX-7, SBX-8** | Claude (③Hands). SBX-7 after SBX-3; SBX-8 last | ②Main plus an effort=max reviewer | As before |

- **Harness:** a parameter table that already exists may gain a base name in a Claude PR. Any new kind of probe is Codex's. The audit suggests Codex makes the harness parameterised by base name, so that each entry point's deny tests are one set of parameters.
- **How "p first, then a" works (②Main's review of #493):**
  - Before Na lands, p's tests for a surface that isn't built yet are strict expected failures (`xfail(strict=True)`). They are keyed on the harness's parameter table of built base names.
  - Na's only change to p's files is adding its base name to that table.
  - The real gate is Na's own macOS CI run: every p test for that surface ran and passed, with 0 skipped and 0 xfail. Na's evidence gives the run id and those counts.
  - p's PRs give their macOS-job counts too. The Linux job has no seatbelt, and a skip there reads as green.
- **In parallel:** while Codex writes SBX-2, Claude may draft 3a, 4a, 5a and 7 on SBX-1's builder. They are rebased after SBX-2 merges, and **none of them merges before SBX-M**.
- **A Claude review stopped part-way** goes to Astra as it is, not reworded.
- **How Codex works (user, 2026-10-29; plan A):** Codex writes and commits locally and does not push; the user pushes its branch and opens the PR (commands in STATUS, "Codex to write"). Codex pushing by itself (plan B) waits until the release secrets are in an Environment that needs the user's approval. Codex never merges. Also never push tags (tagging is the user's, and a `v*` tag starts `release.yml`), and never change `.github/`: a pushed branch's workflow edit runs before anyone reviews it, so a task that needs a workflow change gets it from a Claude session in its own PR (②Main's review of #493; kept by the user on 2026-10-29). Codex branches start with `codex/`, its PRs carry the label `codex`, and each commit message and PR body says "Author: Codex" and names the reviewer. A Claude session that sees the `codex` label leaves "is the deny strict enough" to Astra. Each PR carries the four evidence items (`docs/sessions.md` §8) and its macOS CI run id. The task texts are in `docs/plans/0164/STATUS.md`, "Codex to write". They point to this section and to each card's own section, and nothing more. Codex designs the deny tests itself from the card.

## Goal

1. **One default-deny profile** shared by commands (`run_command`), `run_python`, installed MCP servers and artifact checks. It is one base with the same text everywhere. Each surface adds only its own parameters: writable roots, readable extras, and network mode.
2. **System services pass only through an allowlist** (mach services, unix-domain sockets, preferences, signals, POSIX IPC and shared memory, XPC, ptys, `/dev` entries). This is the layer that holds the daemon-mediated escape class (correction A).
3. **Network only to the local proxy port**, plus whatever S2a-1's rules allow, plus loopback for local dev servers (never Arslan's own port; listening on localhost only; §3). S2a-1's cut stays: after outside content, commands run offline unless the user's click says otherwise (`server/orchestrator/tool_loop.py:1245-1291`). Whether a proxy exists in v0.1.64 is Q1.
4. **Measure on a real Mac** before anything relies on it. Then bring back "ask only when risky" and measure the cards again. That number is the classifier's baseline, not a go/no-go (user, 2026-10-28, `docs/plans/0162/README.md:359` at `11f05434`).
5. **Record two numbers** from SBX onward:
   - the local count of sandbox denials (never uploaded);
   - the bench share of "re-run outside the sandbox" cards.

## What #432 binds this card to (user decision 2026-10-28; cloud audit 5.5 rerun; ②Main's recheck)

- **Correction A** (`docs/plans/0162/README.md:336` at `11f05434`): the daemon-mediated class (launch items, opening apps or links, Shortcuts, scheduled jobs, privacy, network and preference settings, all acting through system services outside the sandbox) is **held by SBX's default-deny profile plus the system-service allowlist, not by the parser**. The parser cannot see indirect calls (scripts, compiled programs, git hooks, package install scripts). **HR must not duplicate this class** (`docs/plans/0164/README.md:79`). The parser rules S2a-3 b adds for these programs (#378) stay as a first line until SBX-M, and as a hint after it. They are not the boundary.
- **Correction B** (`:337`): the floor outside the sandbox is default-allow (`server/services/command_sandbox.py:187-201`). SBX does **not** turn the outside floor into default-deny: "outside" is the user's click, and ssh, git push and gh need the user's secrets there (`command_sandbox.py:188-192`). SBX only adds the CAP6b write-denies to it. Keeping the classifier off outside actions is CLS / S5b's job.
- **Audit B-1** (user decision item 1, `:359`): **"run directly in the sandbox" stays off until SBX-M has measured the allowlisted profile on a Mac, and the parser's rules stay the first line until then.** On main this path is the layer-③ no-card branch (`tool_loop.py:1580-1587`), reached only when the policy is not "ask for every command". The policy reads as `ask_all` unless the stored value is exactly `ask_risky` (`server/services/settings_service.py:409-415`). Settings still offers `ask_risky` behind a known-issue sheet (`web/src/components/settings/AdvancedSection.tsx:353-355`). SBX does not change that default, and no SBX PR makes `ask_risky` easier to pick. SBX-8 (below) is the measurement that is allowed to reopen it.
- **Audit e** (files written now and run later) **goes to HR, not SBX** (③Hands' review of #444, relayed by ⓪Plan's coordinator on 2026-10-28). HR's list: git hooks and config; editor task files; `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`, `.cursor/`; `.envrc`; `.npmrc`, `.yarnrc.yml`, a workspace `pip.conf`, `uv.toml`; `.pre-commit-config.yaml`, `.husky/`; `.github/workflows/`. SBX does not own that rule. It only gives HR a parameter for it (§e).
- **The classifier's scope** (③Hands' review of #444): the writable roots that count as "inside the sandbox's writable area" for a classifier "yes" are **the work folder plus the run's private TMPDIR**. Nothing else is in scope, and shared caches in particular are not. SBX records this in the profile builder, so CLS reads the scope from one place (§1b).
- **The classifier and outside content:** the cloud audit (2026-10-28) no longer has the classifier switched off by outside content. Nothing in this card assumes it is. S2a-1's offline cut for **commands** after outside content is a separate kernel rule, and it stays.
- **Audit f** (keychain): in SBX-M's corpus, §M.
- **Item 8 of ②Main's recheck** (`:346`): denial reasons become a probe. SBX's counter (SBX-7) is local and per turn, per job and per conversation, so S5b's gate h can reuse it. SBX itself does not add a fallback limit.

## Verified current state (main)

### Five seatbelt profiles, not one

| Surface | Profile today | Where |
|---|---|---|
| `run_command` in the sandbox | `(allow default)` + `(deny appleevent-send)`; writes denied except the writable roots; protected paths denied for files and sockets; optional `(deny network*)` when offline | `server/services/command_sandbox.py:136-169`; `(allow default)` at `:146` (**confirmed: ②Main's citation is right**) |
| `run_command` outside (the user's click) | `(allow default)` + `(deny appleevent-send)` + optional offline + deny Arslan's own paths only | `command_sandbox.py:187-201` (**confirmed**); applied at `server/services/terminal_exec.py:176-178` |
| `run_python` | `(deny default)`; reads only the interpreter, its libs and a few system paths; workspace = a fresh tmpdir; no network, no mach-lookup at all | `server/services/code_sandbox.py:131-164`, `(deny default)` at `:145`; used at `:388-389` |
| Artifact checks | the same `computation_profile` | `server/services/artifact_validation.py:52` |
| Installed (one-click) MCP servers | `(deny default)` but `(allow mach-lookup)` wholesale (`:49`), shm IPC, `process-exec process-fork` anything; `(allow network* system-socket)` to any host when it declared network (`:56-57`) | `server/services/capability_sandbox.py:39-69`; wrapped at `server/mcp/session.py:343-348` |
| `ssh_run` (not in the plan's list) | `(allow default)` + `(deny network*)` + TCP port 22 out | `server/services/ssh_exec.py:89-94`, used at `:134` |

- A sixth text, `code_sandbox._SEATBELT_PROFILE` (`code_sandbox.py:46`, `(allow default)` + `(deny network*)`), is used only when no profile is passed (`code_sandbox.py:172`). Every product caller passes one (`code_sandbox.py:388-389`, `artifact_validation.py:52`, `ssh_exec.py:134`), so it is unreachable from product code. The S2a card says to keep it for `SeatbeltBackend.wrapper()` called without a profile (`docs/plans/0162/S2a-command-three-layers.md:47`), but no product caller does that.
- **MCP servers that are not one-click installs run with no sandbox:** `session.py:349-351` (no `sandbox` → plain `cwd`). Only `capability_install.install` sets `sandbox` (`server/services/capability_install.py:297-299`). Remote (http) servers have none by nature (`:297`). Manually added stdio servers have none (Q2).
- `available()` probes with `(version 1)(allow default)` (`command_sandbox.py:212-225`). A default-deny profile that fails to start (for example an operation name an older macOS does not know) would pass this probe and then fail every command.
- When seatbelt cannot start, an approved command still runs unwrapped (`terminal_exec.py:172-175`, `mode = "unavailable"`, note at `:243-244`). The layer-③ no-card branch needs `command_sandbox.available()` (`tool_loop.py:1581`).

### Writable and protected paths

- Writable roots: the working folder, the temp roots, `/dev` (all of it), `~/Library/Caches`, `~/.cache` and `~/.npm` (`command_sandbox.py:79-82`). The whole cache folders and the whole of `/dev` are writable.
- **"Temp" today is shared, not per run:**
  - `temp_roots()` (`command_sandbox.py:67-76`) takes the **parent** of `$TMPDIR`'s `T`, which is the per-user `/var/folders/…/` folder holding both `T` and the user cache `C` (docstring `:68-69`, code `:70-71`);
  - it adds macOS's own per-user folder (`:56-64`, `:73-75`), which is the same parent;
  - it adds `/private/tmp` and `/private/var/tmp` (`:76`).

  So every sandboxed command can write the shared `C` cache and the machine-wide temp folders. Commands also get the server process's own temp folder as `TMPDIR` (`terminal_exec.py:165-168`), the same one for every run and conversation.
- **S3's checkpoint does not cover temp:** it saves the working folder before a run's first write (`server/services/checkpoints.py:3-5`). Nothing a command writes to temp or to the caches can be undone.
- **Paths are resolved before they go into the profile** (`command_sandbox.py:10-13`, `_real` at `:49-50`, `_resolved` at `:85-91`), because seatbelt matches real paths.
- Protected (no read or write, files and sockets, last rule wins): Arslan's data, `~/Library/Application Support/Arslan`, `~/.arslan`, the updater key, the signing backup and Hands' folder (`command_sandbox.py:94-104`), plus the user's secrets: `.ssh`, `Library/Keychains`, cloud CLIs, `.netrc`, `.npmrc`, `.pypirc`, `.gnupg`, browser profiles, cookies (`:109-118`). Combined at `:121-124`.
- **What runs later is not in the kernel's list at all** (input for HR, which owns e). Shell startup files, `~/.gitconfig`, `Library/LaunchAgents`, and other agents' settings (`.claude/`, `.codex/` …) are guarded only by the parser's `protected-write` rule (`server/services/terminal_policy.py:121-133`, `:185-192`). In the kernel they are protected only by not being in a writable root. When the working folder is wide (for example `~`, which `server/registry/file_tools.py:407` mentions as possible), all of them are writable to a sandboxed command. Inside any working folder, the files on HR's list (git hooks and config, editor tasks, agent files, package-manager configs, CI workflows) are always writable.
- **Unix-domain sockets outside the protected roots are reachable** under `(allow default)`: only sockets under protected paths are closed (`command_sandbox.py:161-164`). Commands do not inherit `SSH_AUTH_SOCK` (`server/mcp/spawn_env.py:23-31`, not in `_AMBIENT_KEYS`), but with reads open an agent socket is easy to find (launchd's ssh-agent socket under `/private/tmp/com.apple.launchd.*/`, third-party agents under `~/Library/Group Containers/`, `gpg-agent`, Docker's socket). So a sandboxed command can use the user's ssh keys through the agent although `.ssh` itself is protected (inference, ②Main and ③Hands; not measured).
- **Loopback is open:** a sandboxed command can reach every local TCP service, including Arslan's own API port and a local database or Docker API (②Main). The API token is not in a command's environment (`spawn_env.py:26-31`) and its file is in the protected data folder. Listening is not limited to localhost either, so a sandboxed server can be reachable from the LAN (③Hands).
- **Commands inherit Arslan's TCC grants** (③Hands, inference). If the user gave Arslan Full Disk Access, open reads reach Mail, Messages, Safari and Photos data. Today only Desktop / Documents / Downloads can be closed, and only when the user turns them off (`server/registry/executors.py:792-799`, `command_sandbox.py:21-26`).
- Skill scripts live in the data folder (CAP card, citing `skill_import.py:281`), so `arslan_protected` covers them today. `~/.agents/skills` and a plugin folder do not exist yet (CAP6a / CAP7 create them).
- `write_file` / `edit_file` are confined to the working folder (`server/services/workspace_paths.py:52-99`). They do **not** consult `default_protected()`. Its only consumers are `attach_file` (`file_tools.py:408`), `capability_sandbox` (`:63`) and checkpoints (`server/services/checkpoints.py:194`).

### Network

- In the sandbox the network is open (`(allow default)`). After outside content, S2a-1 runs commands offline under the kernel rule, inside the sandbox and under the outside floor. A command that visibly reaches the network asks first (`tool_loop.py:1245-1291`). The text detector is `_NETWORK_COMMAND` (`server/orchestrator/untrusted.py:84-86`).
- **No local proxy exists for commands.** The proxy code in `server/` is the browser's CONNECT tunnel (`server/services/browser_proxy.py:1-25`, public destinations, port 443, chains through a system HTTP proxy) and MCP env proxy resolution (`server/mcp/proxy_resolve.py:1-7`).
- Seatbelt can confine a port but not a host. `(remote tcp "<ip>:22")` is rejected ("host must be * or localhost"), while `*:22` and `localhost:<port>` are accepted (`ssh_exec.py:9-23`, measured 2026-08-21). So "only the local proxy port" is expressible.
- **Measured by ③Hands on this Mac (macOS 26.6.2, build 25G83, arm64), 2026-10-28:** today's offline profile (`(allow default)(deny network*)`) **also blocks name resolution**. `dscacheutil -q host` returns no address and `nc`'s `getaddrinfo` fails; the control without the deny resolves and connects. So S2a-1's offline cut does not leak through the system resolver on macOS 26.6.2. Measured with `sandbox-exec` directly (`env -i`, scratch HOME), not through Arslan's wrapper; SBX-M repeats it on the new base in each network mode.

### The command layers and "ask"

- Layer ① forbid, layer ② this time only, layer ③ run (`terminal_policy.py:1-30`). Layer ③ runs with no card only when the policy is not ask-all and the sandbox can start (`tool_loop.py:1580-1587`). Otherwise a card (`:1588-1621`).
- Ask-all is the default since v0.1.63: `settings_service.py:409-415`, `tool_loop.py:1103-1110` (an unreadable setting counts as yes), `server/services/permissions.py:581-584`, migration `_0070_ask_every_command.py:3-5`.
- Approved plain osascript and `shortcuts run` run with **no wrapper** (U11; `terminal_exec.py:176-178` skips the outside floor when `unwrapped`). SBX does not change this. It is one of the two exceptions CAP6b names.

### Denials and the re-run card

- **A denial is detected by text:** "operation not permitted" in the output of a run with `sandbox == "workspace"` (`command_sandbox.py:44-46`, `:228-233`). The result then carries `sandbox_denied: True` and a note (`terminal_exec.py:237-239`). Under default-deny, many denials will not print EPERM (a refused mach lookup, a refused connection, a DNS failure, a certificate failure), so this heuristic will undercount.
- **Nothing counts denials.** `sandbox_denied` lives only on the tool result. Run steps keep `result_raw` cut to 2,000 characters (`server/services/run_recorder.py:24`, `:469-470`).
- **The re-run card cannot be told apart from the ask-up-front card.** Both are `kind="outside"`, `target="*"` (`server/services/command_confirm.py:84-94`). Only the WebSocket frame's `sandbox` field differs. The ledger row (`server/services/permissions.py:599-620`) gets no `extra` for it. The re-run card itself is raised at `tool_loop.py:1824-1838`.
- **The bench lumps them together:** the stand-in person counts every card with `frame["sandbox"]` set in one `sandbox_cards` number and declines it (`scripts/kernel_bench/arslan_driver.py:105`, `:202-205`, reported at `:287`). The local weekly report reads `approval_events` and `run_steps` read-only (`scripts/usage_report.py:1-17`, `:84-93`, `:125`, `:135`).
- Bench rounds that exercise Arslan's own sandbox need `BENCH_SANDBOX=none`, because seatbelt does not nest (`command_sandbox.py:212-214`; `arslan_driver.py:32-48`).

### What S2a-3 touches (relevant to the order)

The three S2a-3 branches on origin (`claude/0163-s2a3-understood`, `-runs-from-options`, `-two-tiers`) change `server/services/terminal_policy.py`, `terminal_exec.py` (the shell becomes `/bin/bash -p`, `TMPPREFIX` goes), `tool_loop.py` (`assess_async`), `server/registry/executors.py`, `task_service.py` and a new `shell_grammar.py`. **None of them touches `command_sandbox.py`.** Main today runs `zsh -c` (`terminal_exec.py:140-142`, `:184`).

## Files to change

| File | Which PR | What |
|---|---|---|
| `server/services/sandbox_profile.py` (new) | SBX-1, SBX-2 | The one SBPL builder: base (deny default, the system-service allowlist, system reads), per-surface parameters (writable roots, readable extras, protected, closed / reopened, network mode: none / proxy port / any-declared / port 22), JSON-quoted paths, last-rule-wins ordering, protected last |
| `server/services/command_sandbox.py` | SBX-1, SBX-3, SBX-5 | Becomes the commands' preset on the builder; `available()` probes the real profile; denial detection beyond EPERM; the private TMPDIR replaces `temp_roots()` (`:67-76`); the tagged writable-root list and the resolved `in_scope()` helper for CLS (§1b); the `deny_write_after_roots` parameter HR fills (§e); the narrowed `/dev` list; the closed app-data folders (§1); CAP6b paths |
| `server/services/code_sandbox.py`, `server/services/artifact_validation.py` | SBX-4 | `computation_profile` becomes the strictest preset on the same base (no network, no services beyond the base); delete `_SEATBELT_PROFILE` (§11: replaced, so removed) |
| `server/services/capability_sandbox.py` | SBX-4, SBX-5 | Drop `(allow mach-lookup)` (`:49`) for the shared allowlist; network = proxy port (or as today, per Q1); exclude the CAP6b folders even inside granted folders |
| `server/services/ssh_exec.py` | SBX-1 only | The same text produced by the builder, byte for byte (no behaviour change; Q7, decided yes) |
| `server/services/terminal_exec.py` | SBX-3, SBX-7 | `TMPDIR` = the run's private folder instead of the process temp (`:165-168`); denial code on the result; "unavailable" handling unchanged |
| `server/services/execution_context.py` (or wherever a Run's lifetime ends) | SBX-3 | Create and remove the run's private TMPDIR |
| `server/services/command_confirm.py` | SBX-7 | `Request.extra = {"sandbox": "retry" | "outside"}` so the ledger row says which card it was. `permissions.py` does not change: `_record_in` already writes `req.extra` into the row (`server/services/permissions.py:609-620`; ②Main) |
| `server/services/sandbox_proxy.py` (new) | SBX-6 (Q1 decided N-a) | A minimal local forward / CONNECT proxy on a loopback port, no site list (NET adds the list), chaining through the system proxy as `browser_proxy` does |
| `scripts/usage_report.py` | SBX-7 | Two rows: sandbox denials per week, re-run cards per week (counts only, as the file's rules say, `:10-17`) |
| `scripts/kernel_bench/arslan_driver.py`, `scripts/kernel_bench/report.py` | SBX-7 | Split `sandbox_cards` into `outside_cards` and `retry_cards`; report the retry share (overlaps: "File overlaps" below) |
| Cache redirection (in `terminal_exec.py`'s child environment and the MCP preset's env) | SBX-5 | Arslan-owned cache folders for sandboxed tools (§1c) |
| `tests/server/sbx/` (new, marker `macos` plus a new `sbx_mac` marker for the corpus) | SBX-2 … SBX-7 | Golden profile texts, real-seatbelt behaviour tests (macOS CI job, `.github/workflows/ci.yml:189-190`, `:307`), the SBX-M corpus |
| `docs/plans/0164/SBX-measurement.md` (new) | SBX-M, SBX-8 | The measurement report (exactly what was measured, on which macOS, which profile hash) |
| `SECURITY.md`, `docs/ARCHITECTURE.md` | SBX-3, SBX-4 | The sentences about the command sandbox and MCP sandbox, in the words of the code (#298b rewrites the command section later; SBX only stops the docs promising something false) |

## Must not touch

- `server/services/terminal_policy.py` (the parser; ③Hands' S2a-3 and HR). SBX changes no rule in it. Its docstring about layer ③ (`:17-19`) is updated by S2a-3's rebase or HR, not here, so the rebase stays small.
- `server/services/shell_grammar.py` and the S2a-3 branches (③Hands).
- `server/services/permissions.py` `_ask` (S5b is the only PR that wires the classifier into it, `docs/plans/0164/README.md:82`).
- `server/orchestrator/tool_loop.py`, unless unavoidable. Then the change is small and goes after the open K-line PRs.
- `server/orchestrator/arslan.py` (S64-0b's hot file).
- Hands (`desktop/hands/**`, `server/registry/hands_tools.py`, `server/services/hands_service.py`). Hands runs outside seatbelt by design (`scripts/hands_l3/start_instance.sh:5`).
- The U11 bare-run decision (`task_service.unwrapped_once`), the Bridge frame, `web/src/locales/*` (no new UI copy is planned; if the denial note's wording changes it is model-facing text, not UI).
- CAP's install flow (`capability_install.py`), except reading its `sandbox` dict shape.

## How (key points)

### 1. One base, presets per surface

- The base is `(deny default)` with:
  - `(allow file-read*)` broadly, minus protected and closed folders, exactly as today's reading;
  - `process-exec` and `process-fork` (commands run arbitrary programs);
  - `signal` to the same sandbox only;
  - `sysctl-read`;
  - the system-service allowlist (§2);
  - **IPC, named in the base, not left to `allow default`** (②Main, ③Hands): POSIX shared memory and semaphores (`ipc-posix-shm*`, `ipc-posix-sem*`; Python `multiprocessing`, node workers) only for names the run itself creates, by a per-run prefix where seatbelt can filter by name, never shared with other processes; XPC only to services on the allowlist; ptys (`pseudo-tty`, the `file-ioctl` they need) for tools that open one;
  - **`/dev` narrowed** (②Main, ③Hands): writable only `/dev/null`, `/dev/zero`, `/dev/tty`, the pty devices, `/dev/fd/*`, `/dev/stdout`, `/dev/stderr`, and `/dev/dtracehelper` if the corpus needs it; instead of all of `/dev` (`command_sandbox.py:81`). The list is written into §1b's `device` tag;
  - **unix-domain sockets by allowlist only** (§2);
  - **loopback by the rule in §3**;
  - writes only to the preset's writable roots.

  Protected paths are always the last rules. Reads stay open on purpose: default-deny reads would break most toolchains (Homebrew, pyenv, nvm, Xcode), and today's protection model is the protected list. Q3 asks the user to confirm.
- **Closed app data, whatever Arslan was granted** (③Hands; part of Q3): commands inherit Arslan's TCC grants, so with Full Disk Access open reads would reach other apps' private data. The commands preset closes Mail, Messages, Safari and Photos data folders to reads and writes, the same way the 0.1.59 Desktop / Documents / Downloads closure works (`command_sandbox.py:21-26`, `:152-160`), except that these are always closed, not only when a setting is off. The outside floor does not close them: outside is the user's click, as today. The exact folder list is fixed in SBX-3 and tested by path (Mail's, Messages', Safari's and the Photos library's locations under `~/Library`).
- Presets:
  - commands: working folder, the run's private TMPDIR (§1a), and Arslan-owned caches (§1c);
  - outside floor: unchanged plus CAP6b;
  - `run_python` / artifact checks: today's computation profile, with reads narrowed exactly as today;
  - MCP: its own root and the user's granted folders;
  - ssh: unchanged.
- **Same text for the same parameters:** a golden test per preset, plus a test that the base block is byte-identical across the four "one sandbox" presets.
- `available()` starts the real commands preset once per process. A failure there means "unavailable", as today.

### 1a. A private TMPDIR per run

- Each Run (`execution_context`) gets its own temp folder: created with `0700`, resolved, and handed to commands as `TMPDIR` (bash here-documents land there after S2a-3 a, which honours `TMPDIR`).
- **Location: outside every protected root** (③Hands). Arslan's data folder is protected and the last rule wins, so a TMPDIR under it would be denied. It goes under the per-user `T` folder, with only that sub-folder writable (not `T` itself).
- **Lifetime** (②Main, ③Hands): a run can hold several commands at once, and a command can leave a process running (`cmd &`, `nohup`, a dev server; L6's background processes later). Every command of the run shares the run's folder. It is removed only after the run's process groups are gone: SBX-3 removes it when the run ends and no process started in the run is left; otherwise it stays, and the next start of Arslan sweeps folders whose run is over and whose processes are gone. A process that outlives its temp folder is a compatibility issue, not a security one. Tested with a backgrounded child.
- The commands preset makes that folder writable **instead of** today's temp roots:
  - no shared per-user `/var/folders/…/` parent (so not the shared `C` cache);
  - no `/private/tmp`;
  - no `/private/var/tmp`.
- **Tools that ignore `TMPDIR`** (②Main, ③Hands), measured in SBX-M:
  - hardcoded `/tmp` in scripts and tools (`/tmp/foo` written directly): seatbelt cannot remap paths, so these fail once `/private/tmp` is not writable. **Expected to be the largest source of re-run cards** (Risks);
  - `mktemp` with and without `-t`, Python `tempfile` (should follow `TMPDIR`; checked);
  - Apple frameworks and `confstr(_CS_DARWIN_USER_TEMP_DIR)` users, which write to `T` itself;
  - tools that write the Darwin per-user cache `C` whatever `TMPDIR` says (`command_sandbox.py:56-59`: swift).

  If one of these is needed, only its sub-folder is reopened, and it counts as a shared cache (outside the classifier's scope), not as temp.
- S3's checkpoint does not cover temp (`checkpoints.py:3-5`). A private, per-run folder that is deleted at the end means nothing the run left in temp outlives it. The card states this, so "undo" is not read as covering temp.

### 1b. Writable roots and the classifier's scope

- The builder returns, with each commands profile, a typed list of its writable roots, each tagged as one of:
  - `in_scope` (the work folder, the run's private TMPDIR);
  - `shared_cache` (`~/.npm`, `~/.cache`, `~/Library/Caches`, and any reopened Darwin cache sub-folder);
  - `device` (the narrowed `/dev` entries, §1).
- CLS reads only `in_scope` (`docs/plans/0164/README.md:80`: "allow" only for effects inside the sandbox's writable area). A write that lands in a shared cache is outside the scope, so no classifier "yes" covers it.
- **Scope checks run on resolved paths.** Every root is stored resolved (`_real`, `command_sandbox.py:49-50`). The helper CLS calls (`in_scope(path)`) resolves its argument the same way before comparing, so a symlink in the work folder that points elsewhere is judged by where it points. Tests: a link to a shared cache, a link to `~`, `/var` vs `/private/var`, a `..` path, a missing tail segment.
- **Hard links** (③Hands): resolving does not help with a hard link, which is a second name for the same file. A real-seatbelt test creates, inside the work folder, a hard link to a same-volume scratch file outside the writable roots (a stand-in for a shell startup file) and checks that creating the link, or writing through it, is refused. If seatbelt lets the write through, the work folder is a write path to any same-volume file the user owns, and no path rule in HR can close it. SBX-M then says so, and the fix becomes a kernel-side rule or a check before running (a follow-up decided with ③Hands).
- SBX only provides and tests the list and the helper. How CLS uses them is CLS's card.

### 1c. Arslan-owned caches (a requirement, settled by ③Hands' review; it was a question)

- A writable shared cache is "written now, run later": a tampered package in the user's `~/.npm`, a pip cache under `~/Library/Caches` or a Homebrew cache is installed later by an unsandboxed process (a manually added MCP server started through `npx`, the user's own terminal). If shared caches stayed writable they would have to go on HR's e list.
- So sandboxed tools get Arslan-owned cache folders (outside the protected roots, as for TMPDIR), through environment variables that redirect them reliably (②Main): `npm_config_cache`, `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `XDG_CACHE_HOME`, `GOCACHE`, and others SBX-M confirms.
- The user's `~/.npm`, `~/.cache` and `~/Library/Caches` become read-only to the sandbox. A tool that cannot be redirected and needs to write its shared cache is listed by SBX-M with its card cost; it is not reopened by default.
- **Separate cache roots per preset** (③Hands, recheck of `0a2be0c8`): the commands preset and the MCP preset never share a cache folder. Otherwise a command can leave a tampered package that a sandboxed MCP server (which has network and granted folders) loads later. If a shared root is ever unavoidable, the MCP start path refuses a cached package whose hash does not match the lockfile. Test: a package planted in the commands cache is not visible to the MCP preset.
- Cost: cold caches, more downloads on first use (measured in SBX-M).

### 2. The system-service allowlist (correction A)

- **Allowed:** only what the corpus in §M shows is needed. Candidates: directory services for user lookup, logging, preference **reads** (`user-preference-read`), the certificate trust service, FSEvents, the DNS service only when network mode is not "proxy". These are not yet verified names; SBX-M fixes the final list. **Notifications are not a candidate** (③Hands): a sandboxed command that can post a user notification can pose as Arslan ("tap to approve"). Denied unless a corpus item needs it, and then only after review.
- **Denied, and each denial tested:**
  - launch-item submission and the launchd job APIs;
  - LaunchServices (open an app or a link);
  - Shortcuts;
  - the pasteboard and the window server (screen);
  - TCC;
  - preference **writes** (`user-preference-write`);
  - the security server (the keychain, f);
  - user notifications (impersonation, above);
  - **daemons that do network work for the caller**, for example background URL sessions (`nsurlsessiond`), **in every network mode** (③Hands): the daemon does the I/O, so a request to it would get past both the proxy port and S2a-1's offline cut (inference; SBX-M checks reachability);
  - **unix-domain sockets not on the allowlist** (②Main, ③Hands): the ssh agent (launchd's and third-party ones), `gpg-agent`, Docker's socket, other user daemons' sockets. Consequence, stated as an expected card cost: **ssh-based git remotes need the re-run card** (git over https through the keychain helper is a separate case, f);
  - Apple Events (already denied, `command_sandbox.py:146`).
- **Never `(allow mach-lookup)` wholesale** (`capability_sandbox.py:49` is the counter-example, `docs/plans/0162/README.md:336` at `11f05434`).
- A denied service shows up as a tool failure, not a card. When the tool needs that service, the model gets the existing note (`command_sandbox.py:241-250`) and may ask to run outside the sandbox. That is the re-run card the second number counts.

### 3. Network

- Mode "proxy" (Q1 option N-a):
  - the commands preset allows `network-outbound` only to `localhost:<proxy port>`;
  - DNS from inside is denied (the proxy resolves);
  - the child environment gets `HTTP(S)_PROXY` / `ALL_PROXY`;
  - the proxy has no site list (NET adds it later, `lead-roadmap.md:87-91`). Its value in v0.1.64 is that the kernel lets out nothing else (no raw sockets, no DNS channel) and the proxy can log host names locally;
  - S2a-1's offline rule becomes `(deny network*)` including the proxy port, as today.
- Mode "as today" (Q1 option N-b): network open in the sandbox, S2a-1 cut unchanged; proxy-only moves to NET (v0.1.65).
- **Loopback, in both modes** (②Main, ③Hands): local dev servers and test databases are fine; Arslan's own port is not.
  - allow `network-bind` and inbound only on localhost (never all interfaces, so a sandboxed server is not reachable from the LAN);
  - allow outbound to `localhost:*`;
  - **deny every port Arslan itself listens on, not only the API port** (③Hands, recheck of `0a2be0c8`): in particular the browser's CONNECT tunnel (`server/services/browser_proxy.py`), which reaches public hosts on 443; otherwise `localhost:*` is a second way out in N-a mode. The list is built from the ports Arslan actually binds at start, not hand-written; corpus item: a sandboxed command connecting to the tunnel's port is refused in both modes;
  - then deny Arslan's own API port (and Hands' and the Bridge's local ports, if any are TCP) after it, since the last rule wins. The port is known to the server when it builds the profile;
  - corpus items: a dev server bound and fetched on localhost, a local test database, Arslan's port refused, a bind to all interfaces refused.
- **DNS:** today's offline profile already blocks resolution on macOS 26.6.2 (③Hands' measurement, above). SBX-M repeats it on the new base in each mode. In proxy mode DNS from inside is denied by design.
- In both modes: `run_python` stays offline. MCP keeps "network only when declared", in proxy mode via the proxy. ssh stays port 22.

### e. Files written now and run later: HR owns it, not SBX

- **e is HR's rule** (③Hands' review of #444). HR's list:
  - git hooks and config;
  - editor task files;
  - `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`, `.cursor/`;
  - `.envrc`;
  - `.npmrc`, `.yarnrc.yml`, a workspace `pip.conf`, `uv.toml`;
  - `.pre-commit-config.yaml`, `.husky/`;
  - `.github/workflows/`.

  HR decides how each is held and writes the tests. SBX does not add these paths, and its tests do not cover them.
- **What SBX provides for HR, and nothing more:** a builder parameter `deny_write_after_roots` (resolved paths or path patterns, emitted after the writable roots and before the protected paths, so the last rule wins). HR fills it without editing the profile code. A golden test checks the ordering with a placeholder entry.
- **For HR to know (verified on main, not decided here):**
  - the home-level files are kernel-protected today only by not being writable roots, which fails with a wide work folder (see "Writable and protected paths");
  - inside the work folder nothing on HR's list is kernel-protected;
  - a plain deny on a repository's config or hooks folder may break repository creation and cloning (not measured; SBX-M can run HR's probes if HR asks, but the rule is HR's).
- **Shared caches are not on e's list** because SBX makes them read-only to the sandbox (§1c). They are also outside the classifier's scope (§1b).

### CAP6b: skill, plugin and MCP config folders are not writable by the model

- **Write-denied in every preset:** `~/.agents/skills`, the plugin folder (path fixed by CAP7; SBX takes it as a parameter so CAP7 does not edit profiles), and Arslan's data folder, which holds the `mcp_servers` table (already protected).
  - commands preset: write-denied;
  - outside floor: write-denied (the floor adds a write-deny, not a read-deny, so ssh and git keep working);
  - MCP preset: write-denied even inside a granted parent folder;
  - `run_python`: cannot reach them at all.
- **Read-denied** in the commands preset and the outside floor, as CAP6a requires (`docs/plans/0164/CAP-capabilities.md:261`): `~/.agents/skills` and the plugin folder. `SKILL.md` is read through `read_skill`, and scripts run only through `run_python`. The MCP config needs no new rule: it is in the data folder, already closed to reads.
- **Outside the kernel** (CAP card `:270`): the U11 bare run and Hands clicks. Their tests check the fallback (a hash mismatch disables the item and asks again), not a refusal.
- `write_file` / `edit_file` refuse these folders even when the working folder contains them (they do not consult `default_protected()` today). One small check in `workspace_paths`, owned by SBX-5.
- **Symlink test** (③Hands): `~/.agents` made a symlink into a writable root (the work folder). The write-deny applies to the real path (`_real`, `command_sandbox.py:49-50`), and a real-seatbelt test proves a write through either name is refused.

### M. The measurement on a real Mac (SBX-M)

- **Probes only.** The corpus lives in `tests/server/sbx/corpus/` (exploit-shaped probes stay in tests, by the rule below). It runs with `pytest -m sbx_mac` under the conftest's scratch HOME, or through `scripts/dev/probe.sh` (`scripts/dev/probe.sh:1-19`: scratch HOME, empty `ARSLAN_SECRET_KEY_FILE=`, fake key, scratch data dir). No real key, token or keychain item is read or written.
- **Services act on the real user's session whatever HOME says** (keychain, preferences, launchd). Those probes:
  - only check reachability, using names that do not exist (a `com.arslan.sbx-probe.*` label or domain, a nonexistent keychain service name, a URL scheme with no handler);
  - throw away any output;
  - under today's profile (the baseline), never write;
  - under the new profile, try the write only where it is expected to be refused. If it ever succeeds, the probe removes what it made at once and the report says so.
- **Four safety details** (③Hands):
  - **git credential helper:** `GIT_TERMINAL_PROMPT=0` and a non-interactive `GIT_ASKPASS`, so a missing credential never opens a prompt;
  - **pasteboard:** never read the general pasteboard (it can hold the user's secrets); use a private named pasteboard, or reachability only;
  - **screen:** reachability only, never a capture (a capture opens a TCC prompt);
  - **launch-job write probe** (new profile only): a job whose program is `/usr/bin/true`, with no `RunAtLoad` and no `KeepAlive`, removed at once whether or not it was accepted.
- **Order:** SBX-2's corpus runs on macOS CI first (free; it catches profile-syntax and toolchain-on-VM issues), then on the user's Mac (②Main). CI does not replace SBX-M.
- **Corpus** (each item under today's commands profile, the new profile, and, where it matters, the outside floor):
  - git: init, add, commit, branch, log in a scratch repository; clone of a small public repository over https (network); `ls-remote` through the keychain credential helper against a host that has no stored credential (reachability of the helper and the security server, f); an ssh remote (expected: needs the re-run card, §2).
  - python: `-c` compute, venv creation in the working folder, `pip download --no-deps` of one small package (network, certificates).
  - node: run a script, `fs.watch` on a scratch folder (file watching / FSEvents), `npm view` of one package (network).
  - swift / Xcode toolchain: `xcrun --show-sdk-path`, `swiftc` hello world, `swift build` of a tiny package (SwiftPM starts its own sandbox for manifests, and seatbelt does not nest, so this is the most likely break), the module cache in the per-user Darwin folder (`command_sandbox.py:56-64`).
  - brew, read-only: `--prefix`, `list --versions`, `info --json` (`HOMEBREW_NO_AUTO_UPDATE` is already set, `terminal_exec.py:170`).
  - DNS: a lookup inside each mode, and with the proxy mode on.
  - Certificate checks: an https fetch with each of curl, python, git, swift (the trust service vs file bundles).
  - launchd / LaunchServices / cfprefsd under default-deny: launch-job reachability and submission, LaunchServices reachability (unhandled scheme), preference read (needed) and write (refused), pasteboard and screen reachability, TCC reachability.
  - Keychain (f): security-server reachability from inside (`Library/Keychains` file denies do not cover a daemon read, `docs/plans/0162/README.md:344` at `11f05434`); the git credential helper inside vs outside.
  - Shells: `zsh -c` as on main today, and `bash -p -c` (S2a-3 a, which lands after SBX).
  - Loopback (§3): a dev server bound and fetched on localhost; a local test database; Arslan's own port refused; a bind to all interfaces refused.
  - Unix sockets (§2): a listener the test creates outside the writable roots, standing in for an agent socket, cannot be connected to; reachability of the real ssh-agent, `gpg-agent` and Docker sockets, connect only, nothing sent.
  - Daemons that do network work (§2): reachability of background URL sessions in each network mode.
  - IPC and ptys (§1): a `multiprocessing.Pool`, a node worker-thread pool, a tool that opens a pty.
  - `/dev` (§1): which entries the corpus actually opens.
  - Temp (§1a): a shell script writing `/tmp/x`, `mktemp` with and without `-t`, Python `tempfile`, an Apple-framework tool writing to `T`; a backgrounded child after the run ends.
  - Caches (§1c): first and second runs of `pip`, `npm`, `uv` with the redirected caches; any tool that ignores the redirection.
  - Hard links (§1b) and the closed app-data folders (§1).
- **The report** (`docs/plans/0164/SBX-measurement.md`) names:
  - the macOS version and build, the hardware, and the git / python / node / swift / brew versions;
  - the profile text's hash per preset;
  - every probe by test id, with its result under each profile;
  - what was **not** measured (for example Xcode GUI builds, QUIC, ssh-based git remotes).

  It quotes no escape strings; those stay in the test files and PR comments.
- macOS CI (`.github/workflows/ci.yml:189-190`) runs the behaviour tests on every PR. It does not replace SBX-M: the runner is a VM with a different toolchain and macOS build.

### The two numbers

1. **Local count of sandbox denials, never uploaded.**
   - Detection: EPERM text as today, plus (to be measured in SBX-M) tagged deny rules that report through the unified log, scoped to the command's process group. If tagged reporting is not usable without extra rights, fall back to EPERM plus known service-failure texts, and the report says it undercounts.
   - Storage: a fixed code on the tool result that `run_recorder` keeps in `ref` (not inside the 2,000-character `result_raw`).
   - Counts: per turn, per job, per conversation.
   - Shown only by `scripts/usage_report.py` and in the local run detail. Never in telemetry, the Bridge, or any upload. A test asserts it is absent from every outgoing payload builder that exists today.
2. **Bench share of "re-run outside the sandbox" cards.**
   - Definition: re-run cards ÷ `run_command` calls that ran in the sandbox, per round and per task, with ask-up-front cards reported separately.
   - Source: the ledger's new `extra.sandbox` and the driver's split counters.
   - Rounds run with `BENCH_SANDBOX=none` (Arslan's own sandbox active); the stand-in declines every such card, as today (`arslan_driver.py:45-48`).
   - Baseline: one round on today's profile before SBX-3 merges, one after.

### After measuring (SBX-8, measurement only)

- On the merged SBX stack, run the bench twice on the same tasks, once with "ask for every command" and once with "ask only when risky" (a bench setting; no product change). Record the cards per task.
- **That card count is the classifier's baseline** (user, 2026-10-28): how many more cards CLS must save than "ask only when risky" alone (pass line "saves cards against 'ask only when risky' alone", `docs/plans/0164/README.md:80`). It is not a go/no-go for SBX or for CLS.
- SBX-8 does not change Settings or the default. Re-offering "ask only when risky" without the known-issue sheet belongs to S2a-3's rebase (its `DELETE-BY` names S2a-3 and #406, `AdvancedSection.tsx:353-354`) and S5a, after B-1's measurement exists (Q5).

## PR split (each ≤ ~800 product lines, `docs/sessions.md:58`)

| PR | What | Product lines (est.) | Tests (est.) | Depends on |
|---|---|---|---|---|
| **SBX-1** | `sandbox_profile.py` builder; today's five profiles reproduced **byte for byte** as presets; no behaviour change | +320 / −200 | +250 (golden texts) | — |
| **SBX-1b** | Fix a defect already on main (found by ②Main's max reviewer on #471, confirmed on macOS 26.6.2): profile paths are written with `json.dumps`, so non-ASCII becomes `\uXXXX`, which seatbelt does not decode. A deny on a non-ASCII folder misses (`保护/secret.txt` stays readable), and an allow on a CJK-named working folder does not apply. Fix: an SBPL string encoder with raw UTF-8, `\` and `"` escaped; control characters measured first (refused or `\xHH`, whichever sandbox-exec parses). Real-seatbelt tests on macOS CI: a non-ASCII protected folder is refused, a CJK working folder is writable, ASCII paths are byte-identical; the `json.dumps` mutant goes red. Its own PR (SBX-1 stays byte-for-byte); effort=max, an independent max review, the user merges | small | small | SBX-1 |
| **SBX-2** | Default-deny base + service allowlist as a preset, not wired; the macOS behaviour tests; the corpus harness | +250 | +450 (corpus, macOS-marked) | SBX-1 |
| **SBX-M** | Measurement on a Mac, report only; may tune SBX-2's allowlist in a follow-up of ≤ 50 lines | 0 (docs) | — | SBX-2 |
| **SBX-3** | Commands use the default-deny preset (IPC, ptys, narrowed `/dev`, unix-socket allowlist, loopback rule with Arslan's port denied, closed app data); `available()` probes it; private TMPDIR per run (location, lifetime, boot sweep); tagged writable roots + resolved `in_scope()` for CLS; `deny_write_after_roots` parameter for HR; denial detection beyond EPERM; SECURITY.md sentences | +340 / −70 | +600 | SBX-M |
| **SBX-4** | `run_python`, artifact checks, MCP onto the shared base; delete `_SEATBELT_PROFILE`; drop wholesale `mach-lookup` from MCP; emit the venv interpreter's two `process-exec` and two `pyvenv.cfg` lines in sorted order (today `computation_profile` emits them in set order, which follows the hash seed: same policy, different bytes; found by ③Hands in SBX-1's byte-for-byte check) | +150 / −120 | +300 | SBX-3 |
| **SBX-5** | CAP6b (skill, plugin, MCP config folders; outside floor write-deny; MCP grant exclusion; `write_file` refusal; symlink test); Arslan-owned caches (§1c). **Not e** (HR) | +240 | +450 (every write path, CAP card `:276-282`) | SBX-3, SBX-M |
| **SBX-6** | Q1 decided N-a (user, 2026-10-28; unless SBX-M shows heavy breakage and the user then picks N-b): local proxy, proxy-port-only network, DNS denied inside | +450 | +300 | SBX-3 |
| **SBX-7** | The two numbers: ledger `extra.sandbox` (no `permissions.py` change), denial code and counts, `usage_report.py` rows, bench driver split | +130 (+100 scripts) | +250 | SBX-3; after #436 (see "File overlaps") |
| **SBX-8** | Bench rounds: retry share before / after; ask-all vs ask-risky cards (the classifier's baseline); report | 0 (docs) | — | SBX-3 … SBX-7 |

Total ≈ 1,880 product lines added, ≈ 390 removed (≈ 1,430 without SBX-6), in 7 code PRs and 2 report PRs. "SBX merged", for the order chart, means SBX-1 to SBX-7 (SBX-6 only if chosen). ③Hands' S2a-3 rebase starts after SBX-7.

## Acceptance

- **One sandbox:** the base block is identical across commands, `run_python`, artifact checks and MCP (test). No preset contains `(allow default)`, wholesale `(allow mach-lookup)` or `user-preference-write` (test over every preset's text). Only the outside floor and ssh keep `(allow default)`, by design (correction B; Q7).
- **Services:** every denied service in §2 is refused from inside the commands preset in a real-seatbelt test on macOS CI, and in SBX-M on the user's Mac. Every allowed one is justified by a named corpus item.
- **Network:** proxy mode: a non-proxy connection and a DNS lookup fail inside; the proxy port works; S2a-1 offline closes the proxy too. "As today" mode: unchanged S2a-1 tests pass. Both modes: daemons that do network work for the caller are unreachable.
- **Loopback:** a localhost dev server can be bound and fetched; Arslan's own port is refused; a bind to all interfaces is refused (real-seatbelt tests).
- **Unix sockets:** a stand-in agent socket outside the writable roots cannot be connected to. SBX-M reports the real ssh-agent, `gpg-agent` and Docker sockets as unreachable, and ssh git remotes as a re-run card.
- **IPC, ptys, `/dev`:** the corpus's `multiprocessing`, worker and pty items pass; only the listed `/dev` entries are writable.
- **Closed app data:** Mail, Messages, Safari and Photos data are refused to reads and writes in the commands preset, whatever Arslan's TCC grants.
- **Caches:** the user's shared caches are read-only inside; redirected tools write only Arslan-owned caches.
- **Hard links:** creating, or writing through, a hard link in the work folder to a same-volume file outside the writable roots is refused, or SBX-M records that it is not and the follow-up is opened before SBX-3 merges.
- **Private TMPDIR:** two runs get different `TMPDIR`s; a sandboxed command cannot write the shared per-user `/var/folders/…/` parent, its `C` cache, `/private/tmp` or `/private/var/tmp` (real-seatbelt tests); the folder sits outside every protected root; it is gone after the run ends, including after a cancel and a timeout, and is kept while a backgrounded child of the run is alive, then removed by the boot sweep.
- **Classifier scope (§1b):** the commands profile's root list tags only the work folder and the private TMPDIR `in_scope`; `in_scope()` answers on resolved paths (tests: symlink to a shared cache, to `~`, `/var` vs `/private/var`, `..`, missing tail).
- **e:** not accepted here; HR's card holds it. SBX's only test for it is the ordering of `deny_write_after_roots` (golden text).
- **CAP6b:** every write path in CAP card `:276-282` is refused (tests), with the two stated exceptions tested as fallbacks.
- **f:** the security server is unreachable from inside the commands preset (SBX-M result named in the report). Inside, the git credential helper returns nothing.
- **B-1:** no SBX PR changes `shell_confirm_policy`'s default, the Settings sheet, or the layer-③ branch condition (`tool_loop.py:1580-1581`) (diff check in review).
- **The two numbers:** the denial count appears in `scripts/usage_report.py` and nowhere outbound (test). The retry share is in the bench report, and SBX-8 records before / after.
- **Compatibility:** the corpus in §M passes under the new profile, or each failure is listed in the report with its card cost. The bench "waiting for you" count does not rise (DeepSeek round, M64's rules).
- **Evidence, four items per PR** (`docs/sessions.md` §8). macOS CI run id plus conclusion for every real-seatbelt claim.
- **Review:**
  - **Changed 2026-10-29: see "Who writes what".** ②Main + an effort=max reviewer on every SBX code PR. Codex GPT-6 Astra at the highest level only for parts that review cannot cover because of safeguards (user, 2026-10-28 evening; v0.1.64 README §1.3); the PR names those parts. When Codex is needed, SBX-1 and SBX-2 go together (no behaviour change, plus a harness), then SBX-3 … SBX-7 one by one (②Main; Q10 settled);
  - every reviewer's points (and Codex's, when it runs) each answered on the PR;
  - safety conclusions shown to the cloud audit (`docs/plans/0162/README.md` §8, review path).

## Size

About 1,430–1,880 product lines added and 390 removed across 7 code PRs, plus ≈ 2,600 test lines. Two report PRs. One session (②Main) at effort=max, with the user at the Mac for SBX-M (≈ 1 hour, no keys) and again for SBX-8's bench rounds (costs within the bench caps).

## Risks and rollback

- **Too tight → more re-run cards → users click "in this conversation"** (the reason for number 2, `lead-roadmap.md:84`). Mitigation: SBX-M before SBX-3. If SBX-8's retry share is high, the allowlist is widened by measured item (never wholesale), in a follow-up of ≤ 50 lines.
- **A toolchain breaks under default-deny** (SwiftPM's nested sandbox is the likely one). Mitigation: the corpus names it, and the report lists it with its card cost.
- **Hardcoded `/tmp` is the main expected source of re-run cards** (②Main): scripts and tools that write `/tmp/...` directly fail once `/private/tmp` is not writable, and seatbelt cannot remap paths. SBX-M counts how much of the corpus does this, so the re-run share has its explanation ready. No reopening of `/private/tmp` without a decision.
- **ssh-based git remotes cost a re-run card** once agent sockets are closed (§2). Expected and stated, not a regression to fix inside the sandbox.
- **A process outlives its run** (`&`, `nohup`, a dev server, L6 later): its TMPDIR stays until the process is gone and the boot sweep removes it (§1a). Compatibility, not security.
- **Profile fails to start on another macOS version.** `available()` probes the real profile, so it reads as "unavailable". Today's card path applies (`unsandboxed:*`), and CLS / S5b's "no sandbox, no approvals" holds.
- **Denial undercount** (non-EPERM failures): stated in the report. Number 1 is a floor, not exact, until tagged reporting is measured.
- **Temp is not undone:** S3's checkpoint covers only the work folder (`checkpoints.py:3-5`). With a private TMPDIR that is removed at the end, nothing a run left in temp outlives it; shared caches stay outside both undo and the classifier's scope.
- **A tool needs the shared Darwin cache** (`command_sandbox.py:56-59`). Reopen only its sub-folder, tagged `shared_cache`, after SBX-M names it.
- **Rollback:** each code PR reverts on its own. SBX-1 is behaviour-neutral, so reverting SBX-3 … SBX-7 returns to today's profiles. No migration. No user setting is added, so there is nothing to migrate back. §9: the old profile functions are deleted in the PR that replaces them, not kept behind a switch.
- **If any review is blocked by a safety check** (Codex, the effort=max reviewer, the cloud audit, or the session's own classifier): **stop. Never work around it**: not by rewording, not by moving the review to another session or model, not by merging without it. v0.1.64 waits (the user's rule for CLS, `docs/plans/0162/README.md:370` at `11f05434`, applied to SBX because CLS, S5a, HR and CAP all rest on it).
- **Rule:** exploit strings only in tests and PR comments. Not in this card, the report, SECURITY.md, commit messages or code comments.

## Not verified (read or inferred, not run)

- Whether denying mach lookups actually stops launch-job submission, LaunchServices, Shortcuts, preferences writes and the security server under seatbelt on macOS 26. That is SBX-M's job; the candidate service names in §2 come from public profiles and are not checked on this Mac.
- That the keychain is readable through the security server from inside today's sandbox (②Main's item 6 says "inferred"; `docs/plans/0162/README.md:344` at `11f05434`).
- Whether Apple's git has `credential.helper=osxkeychain` set by default on the user's Mac.
- Whether `user-preference-read` / `-write` and tagged deny reporting work on macOS 26.
- Which tools (beyond swift, `command_sandbox.py:56-59`) write the shared Darwin per-user cache whatever `TMPDIR` says.
- Where a Run's lifetime ends cleanly enough to remove its TMPDIR (named `execution_context` from `checkpoints.py:4`; not traced).
- That `run_recorder` keeps a `sandbox_denied` key: `result_raw` is cut at 2,000 characters (`run_recorder.py:24`); not checked against real rows.
- The file list of #396 and of the reopened #406 / PR4. Only the three S2a-3 branches named above were diffed; `claude/vigilant-rubin-4sj6q0` (S2a-3 d) touches 30 files, not inspected one by one.
- S3 undo's status: `checkpoints.py` exists on main (`server/services/checkpoints.py:1`); its card's closure was not checked.
- The reference profiles (Codex's seatbelt base policy, Anthropic's sandbox-runtime) were not read in this checkout. If SBX adapts either, it reads it at source and records the license (`THIRD_PARTY_NOTICES.md`), as `terminal_policy.py:21-25` does for Hermes.
- That the working folder can be set to `~` in Settings (only the comment at `file_tools.py:407` says so).
- Loopback reachability (dev server, Arslan's port) under each mode; whether seatbelt can limit `network-bind` to localhost.
- Unix-socket reachability today (ssh agent, `gpg-agent`, Docker): inferred by ②Main and ③Hands, not measured.
- That daemons doing network work for the caller (`nsurlsessiond`) are reachable and bypass the network rules: inference.
- That commands inherit Arslan's TCC grants (Full Disk Access) inside seatbelt: inference; the exact app-data folder paths.
- Which `/dev` entries, POSIX IPC names and pty operations the corpus really needs; whether seatbelt can filter POSIX IPC by name prefix.
- How much of the corpus writes to `/tmp` directly; which tools ignore `TMPDIR`.
- What a backgrounded child does after its run's TMPDIR goes, and where the run-end hook lives.
- Whether seatbelt refuses creating or writing through a hard link to a file outside the writable roots.
- Which cache-redirect variables each tool honours.

## Order with S2a-3 (③Hands)

- **#378 (S2a-3 b) really depends on SBX:** its two-tier list is judged against SBX-M's allowlist, so it needs SBX-M and SBX-3.
- **#375 / #376 (the grammar, `bash -p`) do not depend on SBX in meaning.** They conflict with SBX only as text in `terminal_exec.py`: `bash -p` and the `TMPPREFIX` removal sit next to SBX-3's private `TMPDIR` and SBX-7's denial code. S2a-3 a must point bash's here-document temp at the private `TMPDIR`, which it does by honouring `TMPDIR`.
- **The card keeps one rebase after SBX-7** (option a in ③Hands' review): simplest, one rebase instead of two, and SBX-M already measures both `zsh -c` and `bash -p -c`, so S2a-3 a's shell switch is measured either way. If the schedule gets tight, option b is open: #375 / #376 rebase once after SBX-3, and #378 after SBX-M's report.

## File overlaps (②Main)

- **SBX-7 vs M64 (#436, open):** both touch `scripts/kernel_bench/report.py`; #436 also touches `runner.py`. #436 merges first, then SBX-7 rebases.
- **SBX-7 vs S2a-3 two-tiers:** both edit `scripts/kernel_bench/arslan_driver.py`. SBX-7 merges first (the S2a-3 rebase follows SBX anyway).
- **SBX-7 vs INB2:** INB2 records per run whether it read outside content (migration 0072, or JSON); SBX-7 stores a denial code on the run step's `ref` in `run_recorder`. If either touches `run_recorder.py` or the `Run` model, the second one rebases. If SBX-7 needs a column after all, its number comes after 0075.
- **SBX-5 vs CAP:** `capability_sandbox.py` is SBX's; CAP7 passes the plugin path as a parameter; CAP5 / CAP7b come after SBX.
- **No shared files** with INB1, C7c or Q1 (C7c-4 touches `server/mcp_server/tools.py`, the inbound MCP server, not `server/mcp/session.py`).

## Where the code and the plan docs disagree

1. **"Both touch `command_sandbox.py` and `terminal_policy.py`"** (`docs/plans/0164/README.md:78`; `docs/plans/0162/README.md` §8 review path). The S2a-3 branches do not touch `command_sandbox.py`. The shared files are `terminal_exec.py` (S2a-3 a's shell switch, next to SBX's wrapper and denial code) and `tool_loop.py`. The order still holds, for a different reason: #432 makes the parser the second line after SBX, and S2a-3 b's list is judged against SBX-M's allowlist.
2. **Network "only to the local proxy port"** (`lead-roadmap.md:83`) assumes a proxy. No command proxy exists (`browser_proxy.py`, `proxy_resolve.py` only), and NET is a "deferred candidate" (`docs/plans/0164/README.md:86`). Row D also says "default offline" for v0.1.65 (`lead-roadmap.md:249`), a third model. Q1.
3. **"'Ask only when risky' stays disabled"** (`docs/plans/0164/README.md:21`). It is not disabled. It is off by default and selectable behind a known-issue sheet (`settings_service.py:409-415`; `AdvancedSection.tsx:353-355`). B-1's "stays off" is therefore a default plus a warning, not a lock. Q5.
4. **"One sandbox for commands, `run_python`, installed MCPs"**: there are five profiles (table above). The list omits `ssh_exec`'s `(allow default)` profile (`ssh_exec.py:89-94`). Manually added and remote MCP servers have no sandbox (`session.py:349-351`). Q2, Q7.
5. **S2a card: keep `_SEATBELT_PROFILE` for `SeatbeltBackend.wrapper()` without a profile** (`S2a-command-three-layers.md:47`). No product caller does that, so it is unreachable; SBX-4 deletes it.
6. **The two numbers assume they can be read.** Re-run and ask-up-front cards are the same ledger request (`command_confirm.py:84-94`). The bench counts them together (`arslan_driver.py:203-205`). Denials are not counted anywhere (`terminal_exec.py:237-239`). SBX-7 exists for this.
7. **CAP6b "with `checkpoints/` in the same place"** (`CAP-capabilities.md:271`): there is no separate checkpoints entry. Checkpoints are protected because they live in the data folder (`checkpoints.py:7-8`, `command_sandbox.py:101`). CAP's `:93-96` citation for `arslan_protected` is `:94-104` on main.
8. **Lane of the card's author:** `docs/plans/0164/README.md:78` says the card is written by ⓪Plan with lane ②Main. This brief says ②Main writes it at effort=max. The header follows the brief for the lane; the draft is ⓪Plan's.
9. **`terminal_policy.py:17-19`** says layer ③ runs with no card when the sandbox can start. Since v0.1.63, that holds only under "ask only when risky" (`tool_loop.py:1580`). The docstring is stale; it is fixed in S2a-3's rebase or HR, not SBX.
10. **e's owner:** `docs/plans/0164/README.md:78` puts e in SBX ("e (files written now and run later become a hard rule)") and `:79` puts it in HR too; `:81` makes S5a wait on "SBX, e and S3". ③Hands' review of #444 puts e in HR only. The README rows need the same change (⓪Plan's to make), and S5a's dependency becomes "SBX, HR's e, S3".
11. **"Temp" in the plan** means the run's own space (③Hands), but `temp_roots()` is the shared per-user folder with the `C` cache plus `/private/tmp` and `/private/var/tmp` (`command_sandbox.py:67-76`), and commands share the server's temp as `TMPDIR` (`terminal_exec.py:165-168`).

## User decisions (2026-10-28, ~15:20 UTC; the user said 「都同意」, relayed by ④参谋)

These were the card's seven questions (Q1–Q7, referenced above).

1. **Network: N-a**, a minimal local proxy with no site list, provided SBX-M's measurement shows acceptable breakage. In this mode the kernel allows only the proxy port plus loopback, and there is no DNS from inside, so no raw sockets and no DNS channel.
   - Why the user accepted it:
     - the cloud audit named egress control as the real fix for `run_command` reading files;
     - it matches mainstream practice: Claude Code's sandbox goes through a proxy, and Codex's default sandbox has no network;
     - "complete in one go";
     - NET's site list in v0.1.65 then reuses this proxy.
   - SBX-6 is therefore planned.
   - **If SBX-M shows heavy breakage, bring the numbers back to the user before falling back to N-b** (network open in the sandbox as today, plus S2a-1's cut). Do not fall back without asking.
2. **Manually added MCP servers:** they stay unsandboxed in v0.1.64, as the user configured them (like Claude Code). The add form says so.
3. **Reads:** stay open, minus the protected and closed folders, which now include Mail, Messages, Safari and Photos data (§1).
4. **Sandbox cannot start:** keep today's card (`unsandboxed:*`). CLS and S5b approve nothing without a sandbox.
5. **"Ask only when risky":** stays default-off with its warning until S2a-3 and S5a; SBX only measures. Confirmed.
6. **Re-run share:** v0.1.64 only records it. A ceiling is set after SBX-8 has a baseline.
7. **`ssh_exec`:** goes onto the builder byte for byte in SBX-1.

Settled by the reviews (no longer questions): caches are Arslan-owned (§1c, ③Hands); the classifier's scope is the work folder plus the private TMPDIR (§1b); Codex, when needed, reviews SBX-1 + SBX-2 together, then the rest one by one.
