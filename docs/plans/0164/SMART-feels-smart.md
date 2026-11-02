# SMART: Arslan follows what you mean, knows its own state, and guides you when blocked

| | |
|---|---|
| Grade | **Must** for v0.1.64 (user, 2026-11-02, relayed by ④参谋; the user asked that it not be pushed to later). |
| Lanes | Parallel, off the SBX path. SMART-1 ③Hands, SMART-2 ②Main, SMART-3/4 ⑥Helper, SMART-5 ⓪Plan with ⑥Helper, SMART-6 the user. |
| Review | SMART-1 touches the command environment, which is security surface, so it needs another session's effort=max review. The rest are reviewed at high, and each author self-merges under #644. |
| Gate | SMART-5's bench gates v0.1.64 alongside M64 and the STY2 bench. |

## Why

The user, verbatim in part: 「Arslan 还是会给我感觉不靠谱，就是干不了事…你和 open claw 都是可以跟上我在说什么或者说我的关注点，就会有"智能"的感觉，Arslan 现在缺乏，我需要你彻底修复好，我希望 0.1.64 会是个全新的很酷很聪明的 Arslan…open claw 遇到卡点会引导用户…也知道自己什么问题甚至自己的最新状态，Arslan 也缺乏这些」.

What a real chat showed (deepseek-v4-flash; the user's questions were "Claude Code vs you", "why can't you code" and "what's in the plan"; relayed by ④参谋 on 2026-11-02):
1. **Wrong environment.** Arslan said `claude` wasn't installed. It is, in `~/.local/bin`, which Arslan's command PATH doesn't include.
2. **Stale self-knowledge.**
   - It read a local folder that isn't the Arslan repo.
   - It then reported GitHub's main as "last pushed 2026-10-22" and used the v0.1.63 plan.
   - Its "what Arslan lacks" answer missed what v0.1.64 already has.
3. **It didn't follow the user's focus.**
   - One-line questions got full-screen reports.
   - A pointed 「你没去看GitHub仓库是吧」 got a long reply.
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
- **Corrections and probes:** when corrected or probed (「你没去看…是吧」), give a short admission and the correct answer, not a new report.
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
- **Run:** on DeepSeek within the proxy cap, before and after SMART-1 to SMART-4.

### SMART-6: the default chat model (the user)
The run above was on `deepseek-v4-flash`. Recommended: flash for Quick Ask only, and pro (or a Claude model) as the chat default. This is the user's call.

## Method

Every piece has red tests first and mutations on its logic. SMART-1 gets an effort=max review, since it's the command environment. SMART-3 and SMART-4 are prompt text, so their evidence is SMART-5's before/after plus the STY bench not regressing.

## External evidence

- CI ids for each PR.
- SMART-5 before and after on DeepSeek: every task at or above its bar after, and none worse.
- The STY2 and M64 benches don't regress.
- A real-Mac check with the user present: the same three questions from the run above get short, current, correct answers, and `claude` is found.

## For the user to decide

1. **SMART-6:** the chat default model.
2. **Other apps' private data:** close other apps' `~/Library/Application Support/<app>` folders to Arslan's file tools by default (a security change; SBX-5's protected list), or rely on SMART-4's rule.

## Size

About +250 product lines and +400 test lines, in 4–5 PRs, plus the SMART-5 bench scripts.
