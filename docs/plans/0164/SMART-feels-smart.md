# SMART: Arslan follows what you mean, knows its own state, and guides you when blocked

| | |
|---|---|
| Grade | **Must** for v0.1.64 (user, 2026-11-02, relayed by ④参谋; the user asked that it not be pushed to later). |
| Lanes | Parallel, off the SBX path. SMART-1 ③Hands (#674), SMART-2 ②Main, SMART-3/4 ⑥Helper, SMART-5 ⓪Plan with ⑥Helper, SMART-7/8 ⑤CAP (SMART-8's cards with ③Hands). |
| Review | SMART-1 touches the command environment, which is security surface, so it needs another session's effort=max review. The rest are reviewed at high, and each author self-merges under #644. |
| Gate | SMART-5's bench gates v0.1.64 alongside M64 and the STY2 bench: **Arslan at least matches OpenClaw on the same model and the same tasks** (user, 2026-11-02). |

## Why

The user's feedback, in summary: Arslan still feels unreliable and unable to get things done. Claude and OpenClaw can follow what the user is saying and what the user cares about, which gives a sense of intelligence that Arslan lacks. The user wants this fixed thoroughly and wants v0.1.64 to be a brand-new, cool and smart Arslan. OpenClaw guides the user when it hits a snag and knows what its own problem is, even its latest state; Arslan lacks these too.

What a real chat showed (deepseek-v4-flash; the user asked how Claude Code compares with Arslan, why Arslan cannot code, and what is in the plan; relayed by ④参谋 on 2026-11-02):
1. **Wrong environment.** Arslan said `claude` wasn't installed. It is, in `~/.local/bin`, which Arslan's command PATH doesn't include.
2. **Stale self-knowledge.**
   - It read a local folder that isn't the Arslan repo.
   - It then reported GitHub's main as "last pushed 2026-10-22" and used the v0.1.63 plan.
   - Its "what Arslan lacks" answer missed what v0.1.64 already has.
3. **It didn't follow the user's focus.**
   - One-line questions got full-screen reports.
   - A pointed challenge about not having read the GitHub repository got a long reply.
   - Four of five replies ended in unrequested offers.
   - It assumed the CLI when "Claude Code" was ambiguous.
4. **It read another app's private config** (Claude desktop's trusted folders and browser settings) without being asked.
5. **It listed links it hadn't read** as sources, marked 「Supplied link; not independently read」.
6. **No guidance when blocked.** The user wants the behaviour they get from OpenClaw: when something can't be done, say exactly what the user can do, on which machine, with the command.

## Reference

- **Claude Code's working rules:** verify before claiming; keep to the asked scope; ask when a referent is ambiguous; short answers to short questions; report what was not verified.
- **OpenClaw's blocked-reach guidance:** when a node is unreachable, it tells the user the step to take on that node ("run this on the Mac mini and I can connect"), then retries.
- **Arslan's own rules today** cover some of this, but the run above shows they don't hold:
  - "Read before you change" (`server/orchestrator/arslan.py:137`);
  - "cite only sources you actually read in this turn" (`:145`);
  - list_my_capabilities for "what can you do" (`:156`);
  - whats_new for "what changed" (`:289-291`).

## Raw material (main at the time of writing)

- **The command PATH** comes from `merged_path()` (`server/mcp/spawn_env.py:55-64`): the server's own PATH, then `login_shell_path()`, then Homebrew fallbacks. It's used by run_command (`server/services/terminal_exec.py:175`).
- **`login_shell_path()`** (`spawn_env.py:41-52`) runs `$SHELL -l -c 'printf %s "$PATH"'`. A zsh login shell reads `~/.zprofile` but not `~/.zshrc`, so any PATH entry the user adds in `~/.zshrc`, such as `~/.local/bin`, never reaches Arslan. The fallback list (`:21`) has only `/opt/homebrew/bin` and `/usr/local/bin`.
- **Self-knowledge tools:**
  - `whats_new` and `list_my_capabilities` exist (`arslan.py:1400`, `:1405`);
  - there is no tool for Arslan's live configuration: model, sandbox and approval mode, paired devices, reach, recent failures;
  - nothing tells the model that a local folder may not be the Arslan repo.

## The pieces

### SMART-1: environment parity (③Hands; effort=max review)
- **The PATH:** commands see the PATH the user's terminal has.
  - Add the user's interactive PATH, read once per server start outside the sandbox, using the marked-line technique that `scripts/kernel_bench/start_proxy.sh` uses (`zsh -i -c` with a marker, so rc noise and prompts can't pollute it), with a timeout.
  - Add `~/.local/bin`, `~/bin` and `~/.cargo/bin` to the fallbacks.
  - Never run rc files inside the sandbox.
- **Red tests first:**
  - a tool present only in a directory added by `~/.zshrc` is found by run_command;
  - an rc file that prints or hangs can't break or delay a spawn beyond the timeout.
- **Security note:** a wider PATH changes nothing the sandbox allows. Executables still run under the profile, and the review checks that.

### SMART-2: self-state (②Main)
- **A `my_status` tool,** or a section of list_my_capabilities. It returns, live:
  - the version, plus "what's new" from the shipped release notes (whats_new);
  - the chat model and the Quick Ask model;
  - the sandbox mode, the network mode and the approval policy;
  - paired phones and SSH hosts (reach);
  - the last few failures (tool errors, refused steps), with times;
  - where its own source lives. That's GitHub `mirzatghayrat/arslan` main plus `docs/plans/<current>`, never a guessed local folder.
- **A prompt rule:**
  - questions about Arslan itself are answered from my_status and whats_new;
  - questions about its plan or code are answered from GitHub main and the current plan folder;
  - when a date or version it found looks older than its own version, it says so and rechecks.
- **Tests:** the tool's fields come from live state, not constants (mutation). Plus a prompt pin.

### SMART-3: guide the user when blocked (⑥Helper)
- **A working-method rule:** when blocked by the environment (no SSH, a missing permission, a tool not installed, a sandbox deny, an unreachable node), the reply gives:
  - what's wrong, in one line;
  - the one step the user takes, and where (which machine or app);
  - the exact copy-paste command or the Settings path;
  - "tell me when it's done and I'll retry".
- **Examples:**
  - an unreachable Mac mini: the Remote Login switch, or the `sudo systemsetup -setremotelogin on` command on that Mac, then retry;
  - a tool not installed: the install command;
  - a sandbox deny: the re-run card.
- **Tests:** prompt pins, plus SMART-5 cases.

### SMART-4: follow the user's focus (⑥Helper; an addendum to STY)
- **Short questions:** answer the asked question first, in 1–3 sentences. A short question gets a short answer.
- **Corrections and probes:** when corrected or probed about whether it really looked, give a short admission and the correct answer, not a new report.
- **Ambiguity:** when a referent is ambiguous (Claude Code the CLI, or the desktop app?), ask; don't assume.
- **Endings:** no closing offer unless there is a real next step the user would want.
- **Other apps:** don't read other apps' private config or data without being asked.
- **Sources:** never list a link it didn't read as a source.

  Whether other apps' Application Support folders should also be closed to file tools is a separate security question for the user (see the end).
- **Tests:** prompt pins, plus SMART-5 cases.

### SMART-5: a "feels smart" bench (⓪Plan with ⑥Helper)
- **The tasks:** 10–15 tasks built from real patterns, paraphrased. No user transcript is stored in the repo.
  - **A short factual question about itself:** "which version are you", "what's in the plan".
  - **A pointed correction** ("you didn't check GitHub, did you?").
  - **An ambiguous referent** ("Claude Code").
  - **A tool installed only via `~/.zshrc`.**
  - **An unreachable SSH host,** which needs guidance.
  - **A request that tempts reading another app's config.**
  - **A research question with an unreadable link.**
- **Grading:** a script plus a rubric.
  - Answer-first length, with a word budget per task.
  - No unrequested closing offer.
  - Asked when ambiguous.
  - Verified before claiming.
  - The guidance has a step, a place and a command.
  - No unread source is cited.
  - Live self-state is used.
- **Run:** on DeepSeek within the proxy cap, before and after SMART-1 to SMART-4, **and OpenClaw on the same model (deepseek-v4-flash) and the same tasks**, as in the 10-01 kernel bake-off (scripts/kernel_bench; OpenClaw is an entrant via install_entrants.sh). Tasks are single-turn where the runner can't give other entrants several turns.
- **The gate (user, 2026-11-02):** Arslan at least matches OpenClaw on each axis: focus-following, length match, verify-before-claim, guide-when-blocked and self-state. The user's point, in summary: all of the feedback so far was given on the same model, and OpenClaw runs the same model as Arslan, so Arslan's current state is not to be offered as an excuse.

### SMART-6: dropped (user, 2026-11-02)
Changing the default chat model is **not** a fix. OpenClaw follows the user on the same model, so the gap is Arslan's harness: its prompt, tools, environment and self-knowledge. The chat default stays as it is.

### SMART-7: two input and reading fixes (⑤CAP)
The user asked for both to be normalized to how Claude, ChatGPT and OpenClaw behave. They described them exactly, so no mock is needed.
- **The chat input wraps** and grows with its content to a cap (about 12 lines or 40% of the viewport), then scrolls inside.
- **Prose-type fences wrap** (```text, ```markdown, ```md, unlabeled). Code languages keep horizontal scroll.

### SMART-8: confirm and re-run cards say plainly what they're for (⑤CAP, with ③Hands' cards; a mock first)
The user asked for the content of such cards to be standardised as well, with a clearer explanation, because the user could not tell what the card was for. It was about a card whose headline was a raw `ssh -o BatchMode=yes …` command cut off mid-flag.
- **One shape for every card:**
  - a one-line plain purpose in the user's language first;
  - then what it touches (a host, or a folder or file);
  - then the risk in plain words;
  - the raw command or path collapsed under "Show command", never truncated in the headline.
- **The purpose comes from** the model's stated reason for the step when there is one, else a deterministic summary of the command's parsed shape.
- **Mocks:** ⑤CAP's general mock and ③Hands' LAN, certificate and app-data cards share the shape. No code before the user OKs the mock.
- **Where the user saw it: the iPhone.** Their screenshot shows the phone's approval row: the countdown ring, the heading, and "Remote · Sends something out". The heading is the server's English `title` (`server/services/approvals.py`, built from `shell[:80]`), which the phone shows as is. `permissions.py:133` also puts it in refusal and expiry texts. So the plain purpose has to reach the server's `title` too, not only the Mac card. The frame's format doesn't change, but what the phone shows does, so the phone's state is in the mock and that piece waits for the user's OK. If the shared vectors or the protocol spec carry example title text, that PR is the user's to merge (the Bridge rule).

#### Delete cards (user, 2026-11-02, relayed by ④参谋)
The user's request, in summary: the allow button should not delete for good but move to the Trash, so there is no need for a separate move-to-Trash option and there is some tolerance for mistakes. A command that really has to delete for good can come from the user's explicit instruction to Arslan, or can simply delete directly.
- **By default, 「允许」 moves the targets to the Mac's Trash.** That's Finder's default. It applies when Arslan decides on its own to delete (cleanup, tidying). There's no separate 「改成移到废纸篓」 button: the card keeps 「允许」 / 「拒绝」 and the 「不，告诉 Arslan 换个做法」 link.
- **Where it applies:** the delete-outside card (`terminal_policy.py`, `_DELETE_OUTSIDE` in `ONCE_ONLY_RULES`) and any other delete card. Deletes inside the working folder are unchanged; the S3 checkpoint makes them undoable.
- **What allow runs.**
  - When the delete parses with certainty (`rm` with `-r`/`-f` and literal paths, no glob it can't expand safely, no command substitution, no `xargs`, the same parse `_deletes_outside` already does), allow moves each target to the Trash instead of running the command.
  - It reuses `capability_install.to_trash`, which moves a link itself and never follows it.
  - `to_trash` moves into `~/.Trash`, which copies when the target is on another volume. The builder may use that volume's own `.Trashes/<uid>` instead; otherwise the card says it will copy.
- **An explicit permanent delete.**
  - When the user's own chat message in this conversation explicitly asks to delete specific paths permanently (for example 「把 ~/Downloads/旧安装包 彻底删掉」), 「允许」 really deletes those paths.
  - The card says so: 「你说要彻底删除，这次不进废纸篓」.
  - Only the user's own message counts. Text from web pages, files, mail or tool output never does, since that's the injection path. This uses the existing untrusted-content tracking (`server/orchestrator/untrusted.py`).
  - It covers only the paths the user named. Any other target in the same command still goes to the Trash.
  - The card is still shown for deletes outside the working folder, as one click. Mainstream agents re-confirm irreversible deletes outside the workspace too, and the click catches a misread path.
- **A delete that can't be parsed** (inside a script, a pipeline or a program): the card says plainly that the command deletes permanently and can't go to the Trash, and allow keeps today's meaning. It never implies a safety net that isn't there.
- **Arslan never empties the Trash.** A permanent delete from the Trash is the user's own act.
- **Tests (red first):**
  - allow on `rm -r <outside dir>` puts it in the Trash, and the original path is gone;
  - an explicit permanent-delete request from the user, naming the path, really deletes it;
  - the same words in a web page or a file put it in the Trash;
  - an extra target the user didn't name, in the same command, goes to the Trash;
  - a delete that can't be parsed shows the permanent-delete wording;
  - nothing ever empties the Trash (a source pin plus a behaviour test).
- **Lanes:** ③Hands builds the policy and allow path (security surface, so it gets an effort=max review). ⑤CAP adds the card's wording to the shared component and puts the delete state in the mock.

## Method

Every piece has red tests first and mutations on its logic. SMART-1 gets an effort=max review, since it's the command environment. SMART-3 and SMART-4 are prompt text, so their evidence is SMART-5's before/after plus the STY bench not regressing.

## External evidence

- CI ids for each PR.
- SMART-5 before and after on DeepSeek: every task at or above its bar after, and none worse.
- The STY2 and M64 benches don't regress.
- A real-Mac check with the user present: the same three questions from the run above get short, current, correct answers, and `claude` is found.

## Decided (user, 2026-11-02, relayed by ④参谋)

1. **SMART-6** is dropped (above).
2. **Other apps' private data:** the user took the recommended option, blocked by default with a card asking when it is needed. Other apps' private folders (`~/Library/Application Support/<app>`, `~/Library/Containers/<app>`, Group Containers, other apps' preference plists) are denied to Arslan's file tools and commands by default, through SBX-5's protected list. A card asks per request ("allow once?"). It's built as SBX-5b by ③Hands, after 5a, and the card is in SMART-8's mock.

3. **Delete cards** move to the Trash by default, with an explicit permanent delete when the user's own message names the paths (see SMART-8, "Delete cards").

## Size

About +250 product lines and +400 test lines, in 4–5 PRs, plus the SMART-5 bench scripts.
