# HOOK: running a plugin's hooks (v0.1.64, last in the chain)

| | |
|---|---|
| Status | **Draft for the user.** Not started. Moved from v0.1.65 to the end of v0.1.64 by the user (2026-11-10). |
| Lane | ⑤CAP. Every PR: effort=max review. The refusal tests are written by Codex. |
| Depends on | SBX merged (SBX-7 #538, SBX-8), HR-1 (#813), CLS and S5b (the shared denial count). HOOK-1 and HOOK-4 don't run anything and can go earlier; HOOK-2 and HOOK-3 wait. |
| Before it | The guard-hook rule from CAP8-2's plugin follow-up: plugins whose hooks are all on the non-blocking list install with the hooks not run; any other event is refused. This card replaces "not run" for the five events below. |

## Why

Plugins carry hooks: commands Claude Code runs at fixed moments. Some are protections (a `PreToolUse` that refuses a dangerous command). Dropping them silently removes the protection. Refusing the whole plugin loses its skills and connections. Running the hooks keeps both, as long as a hook can only make Arslan stricter.

## Scope of the first version

Only these five events, and only the `command` hook type:

| Event | Arslan runs it | What it may do in Arslan |
|---|---|---|
| `PreToolUse` | before a tool call, after the hard rules and before the card | refuse the call (exit 2 or `permissionDecision: "deny"`), or ask for a card (`"ask"`). `"allow"` counts as no answer. |
| `PostToolUse` | after a tool call finishes | add a note for the model, marked as outside content. It can't change the tool's output: `updatedToolOutput` is ignored. |
| `SessionStart` | when a conversation starts | add text to the model's context, marked as outside content |
| `UserPromptSubmit` | when the user sends a message | refuse the message (it isn't sent to the model, and the user sees why), or add context marked as outside content |
| `Stop` | when the model is about to finish its turn | ask the model to continue, at most 3 times a turn, with every action still going through its card |

**Why these five.**
- **Coverage:** they are the events with a protective or working use in the plugins we can see. Of the 7 marketplace plugins with hooks, these five plus the non-blocking list make 6 installable. The 7th (`claude-security`) uses `PermissionRequest` and `UserPromptExpansion`, which have no counterpart in Arslan.
- **The rest are refused:** `PermissionRequest` would answer Arslan's own cards, which rule 3 forbids. Others (`TaskCreated`, `WorktreeCreate`, `PreModelSwitch`, `Elicitation`…) hook Claude Code features Arslan doesn't have, so they would never fire. Showing them as "protecting you" would be false.
- **Command only:** `http` sends the tool's input to a server, which is a leak path. `prompt` and `agent` run a model on that input, which costs money and opens an injection path. `mcp_tool` calls another connection.

Plugins with any other event or type keep CAP8-2's rule: on the non-blocking list → install with that hook not run; otherwise refused.

**Tool names.** Claude Code hooks match its own tool names (`Bash`, `Edit|Write`, `Read`…) and read its input fields (`tool_input.command`, `tool_input.file_path`). Arslan maps a fixed table (`Bash` → `run_command`, `Write` → `write_file`, `Edit` → `edit_file`, `Read` → `read_file`, `mcp__<server>__<tool>` → that connection's tool) and builds the input in Claude Code's shape. **A matcher that maps to nothing is shown on the card as "matches nothing in Arslan, never runs"**, so no one believes a protection is there when it isn't.

## Rules

1. **In the sandbox, with a time limit.** Each run uses the commands preset (`commands_profile`), with no network, the conversation's work folder readable, and nothing writable outside a private temp folder. The plugin's own folder has to be readable for its script, but CAP6b closes plugin folders to every sandboxed read. Reopening one plugin's folder read-only for its own hook is a sandbox change and belongs to the SBX lane: HOOK-2 asks ③Hands for it and doesn't write it itself. The limit is 10 s by default, and a hook's own `timeout` can only lower it.
   - **A hook that needs to write or reach the network.** No hook gets more than this. A write outside its private temp folder fails, and so does a connection. The run counts as an error (rule 2), and the ledger names the denial. There's no card to grant a hook more, in this version or by setting. A hook that formats files in place (a `PostToolUse` running a formatter) therefore fails and changes nothing. The script isn't read in advance (the user's rule: judge by event name only). So the install card says, for every hook: "Runs with no network and can't change your files." After a denied write or connection, the hook's row in Capabilities shows "tried to write files" or "tried to reach the network: blocked".
2. **A timeout or an error doesn't let anything through.** For `PreToolUse` and `UserPromptSubmit`, a timeout, a crash, an exit code other than 0 or 2, or unreadable JSON all count as "ask": the card is shown with "the plugin's check didn't answer". This is stricter than Claude Code, which lets most errors through. For `PostToolUse`, `SessionStart` and `Stop`, an error is logged and adds nothing.
3. **It can only tighten.**
   - A hook's "allow" is not a click. It never answers a card, never skips one, and never counts as the user's words.
   - A hook's refusal counts toward the same "denied in a row" breaker as the classifier (S5b: 3 in a row in a turn, 20 per conversation and per job, then back to cards).
   - What a hook writes to the model is outside content, never the user's instruction.
4. **Unattended runs don't run hooks.** Scheduled tasks and any run with no window to ask (`permissions._ASKER` unset) skip every hook. A `PreToolUse` protection that can't run is no reason to let more through: those runs already refuse what would need a card (`refuse_unattended`).
5. **The user sees and controls them.**
   - The install card lists each hook: the event, its matcher in Arslan's tool names, and the exact command line.
   - Each hook has its own switch under the plugin in Capabilities.
   - Every refusal or "ask" a hook causes goes in the ledger, with the plugin, the hook and its reason.
   - A plugin update that adds, removes or changes a hook switches the plugin off and shows the card again, as a changed connection does today.
6. **Never written by the model.** Hook configuration lives with the plugin in the CAP6b folders and is hashed with the plugin. A changed hash means the plugin is switched off, as for skills.

## PRs

| PR | What | Size (est.) | Can start |
|---|---|---|---|
| HOOK-1 | Read and store hooks: parse `hooks/hooks.json` and a skill's frontmatter hooks; the five events, the command type and the tool-name table; the card's hook rows; per-hook switches stored; a hook change re-shows the card. Nothing runs. | +450 server, plus tests | Now |
| HOOK-2 | The runner: one hook in the sandbox, with the time limit, Claude Code's JSON input and output, and errors mapped to "ask". It isn't called from the loop yet. It needs ③Hands' read-only reopening of the plugin folder (rule 1). | +350, plus tests | After SBX is merged and the reopening lands |
| HOOK-3 | The wiring: `PreToolUse`/`PostToolUse` at the tool call, `SessionStart`/`UserPromptSubmit`/`Stop` in the turn, the shared breaker, the unattended skip, the ledger rows. It touches the tool loop, so it goes after LOOP1's open slices. | +450, plus tests | After HOOK-2, CLS and S5b |
| HOOK-4 | Web: hook rows on the plugin card, per-hook switches in the Plugins sheet, the ledger lines. **A mock goes to the user first.** | +300 | After the mock, alongside HOOK-1 |

About +1,550 product lines in 4 PRs. Codex writes the refusal tests for HOOK-2 and HOOK-3. At minimum:
- a refusing hook stops the call;
- a timeout or crash asks rather than allows;
- "allow" doesn't skip a card;
- an unattended run doesn't run the hook;
- a hook can't write outside its temp folder, reach the network, or read another plugin's folder;
- a changed hook switches the plugin off;
- the denial count trips at 3.

## What it does to the v0.1.64 release

- **On the critical path:** HOOK-2 and HOOK-3, back to back, after S5b. HOOK-1 and HOOK-4 run earlier and don't add to the wait.
- **The added tail:** two max-reviewed PRs after S5b, with each review round at the pace of #808 so far (2 to 3 rounds), plus the Codex test PRs for them.
- **Prerequisites before HOOK-2:**
  - SBX-7 (#538) and SBX-8 must be merged.
  - HR-1 (#813) must be merged.
  - ③Hands' plugin-folder reopening must exist.
- **Prerequisite before HOOK-3:** CLS, S5a and S5b must be merged.
- **If the classifier chain slips,** this slips with it, since the breaker is shared.

## Not in the first version

- The other 28 events.
- The `http`, `prompt`, `agent` and `mcp_tool` hook types.
- A hook changing a tool's input or output.
- Hooks from Codex plugins, whose install location isn't documented.
- Project-level hooks from a repository's `.claude/settings.json`.

## Sources

Event list and behaviour: https://code.claude.com/docs/en/hooks and https://code.claude.com/docs/en/hooks-guide (read 2026-11-10; 33 events, 5 hook types). Plugin counts: the plugin marketplaces cached on the user's Mac, 2026-11-10.
