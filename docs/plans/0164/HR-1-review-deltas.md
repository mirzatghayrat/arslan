# HR-1 review deltas

This is HR-1's (#813, the kernel hold on files that make something run later) review history, by delta. Each section below was written into the PR body when that delta was pushed, and is kept here verbatim and in order, so the PR body can stay a summary. The first round (`3439f59b`, then the `node_modules` exemption in `eedb25d8`) is described in the PR body itself; the deltas start at 2. Two parts of delta 9 had been shortened in the body to fit and are restored here, each marked where it is.

## Review delta 2 (⓪Plan's max review at `eedb25d8`)

**1. git that must change a tracked held file (blocking).** The measurements are in the table under "Compatibility cost". checkout and switch exit 0 there, so the sandbox note never fired.
- `command_sandbox.git_refused(result)`: in the workspace sandbox only, git's own work-tree lines (`error|warning|fatal:` then `unable to unlink`, `unable to create file`, `unable to create symlink`, `unable to write file` or `cannot create directory at`, ending `: Operation not permitted`), whatever the exit code. A config write (`could not write config file`) isn't one: the work tree is untouched.
- `note(..., git=True)` adds a sentence: the work tree may be only partly updated, even if git exited 0; files that run later kept their old content; check `git status`, tell the user, and don't commit over them.
- `terminal_exec`'s post-run branches move into `explain(result, ...)`, unchanged except for this. At exit 0 a new branch records one SBX-7 `eperm` denial through `run_trace.note_denial` and sets the note, with no `sandbox_denied` and no error (as the exit-0 proxy refusal). At a non-zero exit the existing stop branch adds the sentence; it already records `eperm` once, and `note_denial` sets one code per call, so nothing is counted twice.
- Not covered: the remote-only checkout prints only a config-write line and exits 0, so it gets no note (the branch is made without an upstream; nothing in the work tree is wrong). **Superseded in review delta 4:** the English regex above is replaced by a path-keyed detector, and the config-only refusals get the note.

**2. SECURITY.md and this body** now say which git operations fail, as measured, and which keep working. The body's earlier "checkout and stash work" lines are corrected in place.

**3. The node_modules exemption is only below the root.** `run_later.exempts(roots)` is false when a root's path has a `node_modules` component (itself included). `kernel_filters(folders, roots=())` decides per profile over the real paths of the work folder (commands, outside floor) or the MCP server's own folder, its cache and its granted folders, and writes the bare regexes, with no `require-not`, when it doesn't exempt. The regexes stay built from constants. `family(path, root=None)` and `matches(path, root=None)` take the same optional root for HR-2; without one, a dependency folder anywhere still exempts (documented). SECURITY.md says so.

**4. An lstat error while `hooks_path` walks up** (on a parent's `.git`, from a folder below it) is now tested: no profile, and the command doesn't start.

**5. Pins:** the kernel file is 6 markers and 13 cases (the first delta's 4 and 10, plus three cases).

**Tests added**
- Unit (`tests/server/test_hr1_run_later.py`, now 126 cases): the git note at exit 0 (unlink, removal warning, new file, new folder) and at exit 1, through `terminal_exec.explain` with the denial code read off the run trace; a config write, another tool's EPERM at exit 0, and git's line outside the workspace sandbox get no git note; roots inside `node_modules` (three spellings) keep every name held, a nested one below them too; a nested `node_modules` below an ordinary root stays exempt; the kernel text for such a root (directly, through a link with an ordinary name, the folder itself, and as an MCP extra root) is the bare golden, in the commands and MCP profiles too; the lstat walk error.
- Real seatbelt (macOS-marked, SBX harness, scratch HOME, commands preset): a tmp repository whose branch changes a tracked `.github/workflows/zz-stand-in-word.yml` and an ordinary file. `git checkout` exits 0 with HEAD moved, the held file's old content on disk and the ordinary file updated; `git merge --ff-only` exits 1 with HEAD unmoved. git's real output through `terminal_exec.explain` carries the note and one `eperm` denial in both. And a work folder under `node_modules/` refuses the held names, a nested `node_modules` below it included, while an ordinary file is written.

**Mutations** (each red, then restored; the tree checked afterwards)

| Mutation | What went red |
|---|---|
| The exit-0 git branch removed | the exit-0 unit test and the real-seatbelt checkout case (2 failed) |
| The git sentence dropped from the non-zero stop | the exit-1 unit test and the real-seatbelt merge case (2 failed) |
| The exemption kept regardless of the root (`exempts` always true) | the three root unit cases, the kernel-text test and the real-seatbelt case (5 failed) |
| An lstat error in the walk read as "no repository" | the lstat test |

**Checks:** the local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`) gave 29691 passed, 62 skipped and 1 failed: `test_k9b_steering`'s window test, a known load flake, whose file passes alone (22 passed). `check_added_chinese.py --base origin/main` is clean. ruff is clean. The macOS run of the kernel file (`-m macos`, JUnit, `scripts/check_macos_counts.py`): 13 ran, 0 skipped, its pins match.

## Review delta 3: the user's list decision

**1. The CI family is off the deny list.** `run_later.FAMILIES` no longer has `ci`. A CI job runs on the CI service, and only after a push, so a sandboxed write to a workflow file doesn't run anything on this Mac. Its guard moves to the push card (HR-2b). The names stay recognised: `run_later.CI_FILES` (the same pattern form as `FAMILIES`) and `run_later.is_ci_file(path)` (any depth, case folded), for HR-2b to name a pushed change to one. Neither the kernel's profiles nor `matches()` use them, and a comment says so. What follows from this:
- the goldens (`RUN_LATER_REGEXES` loses its CI line, so `RUN_LATER_TEXT` and the SBX-1/3a goldens built from it follow);
- the CI rows move from HELD to ORDINARY, plus a mixed-case spelling and a relative path. A new unit test checks that `is_ci_file` is true exactly for those rows, and another checks that no CI regex is in the kernel text;
- the real-seatbelt family cases go from 7 to 6, and a new case writes six CI files in the commands preset (all written);
- the git-refusal tests use `.vscode/settings.json` as the tracked held file (real seatbelt) and `.vscode/settings.json` / `.husky/<stand-in>` in the unit lines; the node_modules cases use `.vscode/tasks.json`;
- HR-0's `hard_rules.RUN_LATER` rows come from `FAMILIES`, so the `run-later/ci` row is gone with it;
- SECURITY.md: CI files are listed as ordinary, recognised for the coming push card, and the git cost paragraph matches the measurement below;
- the model's note no longer names CI (now "git hooks and config, editor tasks, agent and package settings").

**2. `.vscode` stays denied** (tasks, launch, settings and mcp json, `*.code-workspace`), as the user decided. Why, read from the workbench code bundled with Cursor 3.25.9, which is built on VS Code 1.128.0. VS Code itself isn't installed on this Mac, so this was read from Cursor's VS Code base, not from VS Code:
- `task.allowAutomaticTasks` is a setting with the values `on` / `off`. It defaults to `"on"` and is `restricted` (a workspace setting can't change it);
- `RunAutomaticTasks._tryRunTasks` returns early only when the workspace is untrusted, tasks have already run, or the setting is `"off"`. Otherwise it finds every task with `runOptions.runOn: "folderOpen"`, and `_runWithPermission` runs them with no prompt (it checks only that there are some and that the setting isn't `"off"`).

So a `.vscode/tasks.json` written by a sandboxed command runs, unsandboxed, the next time the user opens that trusted folder.

**3. The everyday git flow, measured** under real seatbelt in the commands preset (SBX harness, scratch HOME). One clone of a bare origin. Both are made outside the sandbox in the harness's tmp work folder, so a push lands inside it. The steps run in this order. "Refused" is the held write git's own EPERM line names; "effect" is read back with git afterwards, outside the sandbox. This is pinned in `test_the_everyday_git_flow_in_the_sandbox`.

| Step | Exit | Refused write | Effect |
|---|---|---|---|
| `git clone <bare> <dir>` | 1 | `.git/hooks` (git's sample-hook templates, first) | no (the stop note since delta 5) |
| `git init` | 1 | `.git/hooks` (templates, first) | no (the stop note since delta 5) |
| (diagnostic) `clone --template=` | 128 | `.git/config` | no |
| (diagnostic) `init --template=` | 128 | `.git/config` | no |
| `git checkout -b x origin/x` | **0** | `.git/config` | branch made and checked out, **no upstream** (git note since delta 4) |
| `git switch -c y` | 0 | none | yes |
| `git push -u origin y` | **0** | `.git/config` | pushed, **no upstream** (git note since delta 4) |
| `git branch --set-upstream-to=origin/x` | **0** | `.git/config` | **no** (git note since delta 4) |
| `git fetch` | 0 | none | yes |
| `git pull --ff-only` (after `switch main`) | 0 | none | yes |
| commit, then switch y and back (no held file differs) | 0 | none | yes |
| `git remote add` | 128 | `.git/config` | no (the stop note since delta 5) |
| husky: `git config core.hooksPath .husky/_` | 4 | `.git/config` | no (the stop note since delta 5) |
| husky: write `.husky/_/<stand-in>` | 1 | `.husky` | no |
| `git config user.name <stand-in>` (local) | 4 | `.git/config` | no (the stop note since delta 5) |

**`.git/config`-only failures: 6 of the 13 everyday steps.** They are the tracking checkout, `push -u`, `--set-upstream-to`, `remote add`, husky's `core.hooksPath` line and `config user.name`. `config.worktree` didn't appear. Three of the six exit 0 with the config part silently missing; the git note didn't fire for them at delta 3 (work-tree lines only) and does since delta 4. A config grant alone would not fix:
- `clone` / `init`: they are refused on the sample hooks first, and on the config beneath them, as the template-free rows show. HR-1b would also need git's template hooks, or to run them with an empty template;
- husky's install: it also writes `.husky/_/`, which stays held.

HR-1b (a one-click-per-conversation grant that lets git update this repository's config) is not built here.

**Pins:** the kernel file is now 8 markers and 14 cases (13, minus the CI family case, plus the CI-ordinary case and the git-flow case).

**Mutation:** the `ci` family put back into `FAMILIES` turned 10 tests red: the text golden, the CI rows of the ordinary table (6), the "kept out of the kernel text" test, the node_modules-root golden, and the real-seatbelt CI case. It was reverted afterwards.

**Checks:** `origin/main` at `9a415870` (#814) was merged in first (corrected in review delta 4: this line used to name `15c481f9`, which the merge didn't bring in), with no conflicts, then `uv sync --frozen`. The local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`, 28 minutes under load) gave 29780 passed, 62 skipped and 5 failed. None of the five is in an HR-1 file. Rerun alone:
- passed: `test_shell_grammar_differential::test_plain_pipeline_is_compared`, `test_profile_activation::test_restricted_trial_over_real_loopback_http_then_rollback`, `test_network_guard::test_real_network_is_on_the_eight_runners_and_one_self_test_and_nowhere_else` and `test_window_permissions::test_once_a_card_in_a_turn_goes_unanswered_the_turns_later_cards_do_not_wait`;
- `test_mcp_wiring::test_an_install_test_that_times_out_stops_the_start_it_began` failed once more when rerun next to the slow ones, then passed alone. It is a timing test outside this PR's files.

ruff is clean, `check_added_chinese.py --base origin/main` is clean, and gitleaks over `origin/main..HEAD` is clean. The macOS run of the kernel file (`-m macos -o xfail_strict=true`, JUnit, `scripts/check_macos_counts.py`): 14 ran, 0 skipped, 0 failed, and its pins match. CI's macOS job is the authority.

## Review delta 4 (review at `048478b9`)

**1. The git note, keyed on the path (blocking).** At `048478b9` the note missed the config-only refusals at exit 0 (a tracking checkout, a remote-only checkout, `push -u`, `--set-upstream-to`), the outside floor that holds the files, and git's translated messages (LANG, LC_ALL).
- `command_sandbox.git_refused(result, command=, cwd=, hold=)`: for a git command, any stderr line that names a held path is a refusal, whatever the words around it and whatever the exit code. git translates its words but never a path. Held paths: the run-later names by the work folder's root rule (`run_later.matches`, which covers `.git/config`, `.git/config.worktree` and `.git/hooks/...` as well as the work-tree names) and the work folder's `core.hooksPath` target, also from a folder below the top. A path is a run of characters between white space, quotes, brackets, colons, commas and semicolons, ASCII or full width (git's Chinese messages put a full-width colon right after a path). Whether the command is git is read from its text (the word `git`) or from `shell_grammar`'s words (quotes removed), generously: a false positive only adds a note. It applies in the workspace sandbox, and under the outside floor when that floor holds them (`mode == "outside"` with `hold`). It replaces the English-only regex.
- `command_sandbox.git_note()`: one note for both places and any exit code. It says some files weren't updated (git config or hooks, editor or agent settings; an upstream, remote or setting may not be saved; a tracked file may have kept its old content), and tells the model to check `git status`, tell the user, and not commit over them. It doesn't mention `outside_sandbox`. `note()` lost its `git` flag; the ordinary EPERM note is unchanged.
- `terminal_exec.explain(..., command=, hold=)`: `_run` passes both. One SBX-7 `eperm` per run: the stop branch records it once (as `eperm`, even beside a proxy refusal), and the exit-0 / floor branch once. Under the floor, another command's EPERM note also names the run-later files when the floor holds them.
- SECURITY.md: the note, that it holds in any language git speaks, and that it applies under the floor.

**2. Pinned by test:** the MCP preset's `roots=` (a unit test over its own folder and its cache, and a real-seatbelt case for an own folder inside `node_modules`). The old regex's symlink and write-file branches are gone with the regex; both line shapes are unit rows of the new detector.

**3. The body:** the merge from main brought in `9a415870` (#814), not `15c481f9`; corrected in delta 3's checks. The git tables mark the exit-0 config rows as noted since this delta.

**Tests added**
- Unit (`tests/server/test_hr1_run_later.py`): 14 git lines naming a held file get the note at exit 0 with exactly one `eperm` (counted by a spy on `run_trace.note_denial` and read off the trace): work-tree lines, the config line (once and twice), the template-hook copy, stand-in German words with and without EPERM text, full-width colons, a trailing period. At exit 1 it is a stop with the git note. The hooksPath target counts from the work folder and from below it. Under the floor the note comes only with the hold. No git note for a non-git command printing a held path (`python3`, `<stand-in>-git`, `.gitx`), for git naming an ordinary path, `src/config` or a held name under `node_modules`, or for git's line on stdout. git is recognised in `/usr/bin/git`, `g'i't`, `env ... git` and `git -C`. The git note ends with the user.
- Real seatbelt (`tests/server/sbx/test_hr1_run_later_kernel.py`, scratch HOME, local bare origin): the four config-only steps each exit 0, leave `.git/config` byte for byte, and carry the note with one `eperm`. Under the outside floor that holds them, checkout to a branch whose tracked `.vscode/settings.json` differs exits 0, moves HEAD, keeps the old file and carries the note. The same checkout with `LANG`/`LC_ALL` set to `de_DE.UTF-8` and to `zh_CN.UTF-8` carries the note (skipped only if git printed no translated line; here both ran). An MCP server whose own folder is inside `node_modules` keeps every name held.

**Mutations** (each red, then restored by hand; the tree checked afterwards)

| Mutation | What went red |
|---|---|
| The detector back to English-only matching (`^(error\|warning\|fatal): ... Operation not permitted$`) | 11: both real-seatbelt language cases, 9 unit rows and tests (German, full-width, template copy, trailing period, hooksPath, and git naming an ordinary path, which the English pattern wrongly noted) |
| The floor branch removed (workspace only) | 2: the floor unit test and the real-seatbelt floor checkout |
| `.git/config` dropped from the detector's held set | 15: all four real-seatbelt config-only cases and 11 unit rows and tests |
| The denial noted twice | 30, every note test (the spy counts calls; `note_denial` itself overwrites) |
| The MCP preset without `roots=` | 2: the unit test and the real-seatbelt MCP case; dropping only its own folder or only its cache turns the unit test red |

**Pins:** the kernel file is now 11 markers and 22 cases (14, plus 4 config-only, 1 floor, 2 language, 1 MCP).

**Checks:** the local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`) gave 29815 passed, 62 skipped and 0 failed (14:46). ruff in CI's scope (`server/ arslan/ tests/ scripts/`) is clean; `check_added_chinese.py --base origin/main` is clean; gitleaks (`gitleaks git --config .gitleaks.toml --log-opts="origin/main..HEAD"`) found no leaks. The macOS run of the kernel file (`-m macos -o xfail_strict=true`, JUnit, read with `scripts/check_macos_counts.py`): 22 ran, 0 skipped, 0 failed, 0 xfail, matching its pins (the script's other errors are the manifest's other files, not run here); the marker meta-test passes. CI's macOS job is the authority, including whether its git prints translated lines (the language cases skip, which that job counts as red, if it doesn't).

**Not done here:** the review's list items 4 to 6 (the floor's exemption decided from the work folder alone, `uv init`, nested repositories' `core.hooksPath` in SECURITY.md, and the note still naming write_file before HR-2).

## Review delta 5 (review at `23332d98`)

**1. The git note needs a refusal line, on either stream (blocking).** At `23332d98` any held path in stderr counted, so a successful commit whose hook prints its `.husky` path, git's not-executable-hook hint, pathspec errors, the add of an ignored `.envrc`, `show`, a failed `apply`, the CRLF warning, a bad config line and `ls git/.npmrc` all got the note and an `eperm`; and a refusal under `2>&1` (on stdout) got none.
- `command_sandbox.git_refused_paths` (with `git_refused` as its bool): a line counts only when it carries the EPERM text (`_DENIED`) **and** names a held path, and both stdout and stderr are read, line by line. git translates its words but not the path, and macOS doesn't translate strerror, so "Operation not permitted" ends the refusal line in every language git speaks; the language cases still pass under real seatbelt. The unit rows that had no EPERM text (the stand-in German, full-width, template-copy and trailing-period lines) now carry it, as git prints it. Only refusal lines are tokenised, which also removes the per-token cost on a chatty hook's stderr (list item 3).
- SECURITY.md (the "Run later" paragraph): the note fires when a line on either stream names one of these files and says the change was refused; a line that only names one doesn't count; setup steps get the ordinary stop note.

**2. Which note for clone, init, remote add and config (list item 1).** These now get the ordinary stop note in the sandbox, and the floor's own note under the floor (`command_sandbox.git_setup_failed`: a non-zero exit where every held path git named is inside a `.git` folder). Why: such a step failed outright and nothing in the work tree moved, so the git note's "partly updated, check `git status`, don't commit over them" doesn't fit. The stop note already says these files can't be changed by a command and how to get the step done (a run outside, which the user reads on its card); the floor's note says only a click on its own card lifts the hold. The git note stays for a refusal on a work-tree file at any exit code (checkout, merge, stash, rebase: the tree may be partly updated) and for the exit-0 config-only refusals (tracking checkout, `push -u`, `--set-upstream-to`: the step looks successful with its upstream unsaved). Keyed on the path, not on the subcommand, so `-C`, aliases and wrappers don't change it.

**3. SBX-7 under the floor (list item 4).** A git refusal under the floor now records no denial, like every other floor refusal (already pinned). `note_denial` is documented as "the sandbox stopped the command", and the weekly count is of the workspace sandbox's denials; so neither floor refusal records one. In the sandbox the git note still records exactly one `eperm`.

**4. The two surviving mutants (list item 5)** now go red (below).

**Tests added or changed**
- Unit (`tests/server/test_hr1_run_later.py`, 220 cases): 13 named-not-refused rows (every false positive above, plus `config --list --show-origin` and `show`'s diff on stdout), each with no note and no denial in the sandbox and under the floor; the `2>&1` test flipped to expect the note (stdout only, and stdout beside other stderr), and EPERM text on one stream with a held path on the other is not a refusal; 3 setup rows (config write, template copy, `<dir>/.git/config`) get the stop note with one `eperm` in the sandbox, the floor's note with none under it, and the git note at exit 0; a work-tree refusal at exit 1 (also beside a config line) keeps the git note; `cat .git/config` and `cp ... .git/hooks/...` aren't git; a work folder inside `node_modules` keeps the note; floor notes with no denial.
- Real seatbelt (`tests/server/sbx/test_hr1_run_later_kernel.py`): the held-file checkout under `2>&1` (exit 0, empty stderr, the EPERM line on stdout) gets the note; a successful commit whose `.husky` pre-commit hook prints its own path to stderr, and `git add` of an ignored `.envrc` (exit 1), get no note and no denial; the floor checkout keeps the note with no denial.

**Mutations** (each red, restored byte for byte, checked with `cmp` against a backup)

| Mutation | What went red |
|---|---|
| EPERM requirement dropped | 13 unit and both real-seatbelt negatives |
| stdout not read | the `2>&1` unit test and the real-seatbelt `2>&1` case |
| Held-path requirement dropped (any EPERM line counts) | 6 unit tests |
| `_GIT_WORD` taking `.git` for the word git | the non-git command test |
| `_held_for_git` without the root rule | the `node_modules` work-folder test |
| `git_setup_failed` always false | 3 setup rows |
| `git_setup_failed` with `any` for `all` | the mixed exit-1 row |
| The floor's git note recording `eperm` | the floor unit test and the real-seatbelt floor case |

**Pins:** the kernel file is now 13 markers and 25 cases (22, plus `2>&1` and the two named-not-refused cases).

**Checks:** the local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`) gave 29837 passed, 62 skipped, 0 failed (8:40). ruff in CI's scope is clean; `check_added_chinese.py --base origin/main` is clean; gitleaks over `origin/main..HEAD` found no leaks. The macOS run of the kernel file (`-m macos -o xfail_strict=true`, JUnit, `scripts/check_macos_counts.py`): 25 ran, 0 skipped, 0 failed, matching its pins. CI's macOS job is the authority.

**Not done here:** list item 2 (git run from a script or a `make` target gets no note), and list item 6 (round 3's items 4 to 6, carried over).

## Review delta 6: ancestor hold (option B)

**The gap.** The held names match by path regex. A command could rename the folder above one (`.git`, `.git/hooks`, `.vscode`, `.husky`, `.claude`, `.codex`, `.gemini`, `.cursor`, a submodule's `.git/modules`), write inside under the new name, where no regex sees a held path, and rename it back.

**The fix (⓪Plan's option B).** SBX-5a's `held_ancestors` now also takes `kept` folders: each is held itself, with every folder above it up to and including the root. A literal `file-write*` deny holds that one folder in place (rename, removal, mode) while files inside are created, written and removed as before (SBX-5a's measurement, and the commit test below).
- `run_later.HELD_FOLDERS` is derived from `FAMILIES`: each pattern's leading plain-name components (up to its first `*`; the last component only when the pattern ends in `**`). That gives `.git` with `hooks`, `worktrees` and `modules`, plus `.vscode`, `.claude`, `.codex`, `.gemini`, `.cursor` and `.husky`. A `*` component is left out, because renaming it keeps the path matching.
- `run_later.held_folders` walks the work folder (for MCP: the granted folders, its own folder and its cache) by real path. It doesn't follow links. It skips `node_modules` under the same `exempts` rule as the regexes, and walks it when the root lies inside one. Inside `.git` it looks only for `hooks`, `worktrees` and `modules`, never git's objects.
- `command_sandbox.run_later_folders` adds each folder's `core.hooksPath` target and feeds both to `held_ancestors(kept=...)` in `commands_profile`, `capability_sandbox.profile` and `minimal_profile`. Their roots are the work folder (plus temp and caches), the granted, own and cache roots, and `/` for the floor.
- Files are never held this way. The regexes already cover writes to them.

**Walk caps and their closed fail.** The caps are `WALK_ENTRIES = 50,000` entries and `WALK_DEPTH = 32`. Past either, or on a folder it can't list, the walk is incomplete. The profile then also denies each held folder by its name regex at any depth (`run_later.folder_filters`, with the same dependency exemption) and logs a warning. That stays closed, at the cost of making a new one (`git init`, `git clone`, a first `.vscode`) in that run. Build time on warm APFS tmp trees: the walk takes about 10 ms for 5,000 entries and 90 ms for 49,500 (4,500 folders). The whole commands profile took about 50 ms at 5,000 entries and about 110 ms at 49,500. This worktree, `.venv` included, walks complete in about 40 ms.

**A held folder that doesn't exist yet** needs nothing, by design: `git init`, `git clone` and a first `.vscode` are made by mkdir. The accepted residual is a folder prepared elsewhere, under no held name, and renamed into a fresh place. For non-git consumers (`.vscode`, `.husky`, agent and package settings) that residual is accepted. git gets a consumer-view check in HR-1b.

**Costs (SECURITY.md).** These fail inside the sandbox:
- `rm -rf .git` (after removing what isn't held);
- renaming or removing a folder that holds a repository or a held folder;
- renaming or removing the work folder itself.

**Mainstream comparison (SECURITY.md, as documented by those projects).**
- Claude Code's sandbox runtime denies writes to named dangerous paths. That is path-based, with a similar residual.
- Codex makes `.git` read-only, which holds git at the cost of a card for every commit.

**Tests**
- Real seatbelt (`tests/server/sbx/test_hr1_run_later_kernel.py`, 7 new markers, 9 cases):
  - Commands preset:
    - renaming `.git`, `.git/hooks`, `.vscode`, `.husky`, or the work folder's subfolder holding a repository is refused, and an ordinary folder beside them moves;
    - the round trip (rename away, write the held file, rename back) leaves no held file, for `.git` (a hook), `.vscode` and `.husky`;
    - a write and commit still work, and `rm -rf .git` fails with `.git/hooks` still there;
    - a dependency's `.git`, `.vscode` and the dependency folder itself still move, while a `.git` beside it doesn't;
    - past the cap, `.git`, `.git/hooks` and `.vscode` are held by name after their parent moved, an ordinary folder moves, and `mkdir -p x/.git` is refused.
  - MCP preset: `.git` and `.vscode` are held in a granted folder and in its own folder.
  - Floor (`run_later_in`): `.git` is held and an ordinary folder moves.
  - The existing everyday git flow and its `FLOW_MEASURED` table are unchanged with the hold in place.
- Unit (`tests/server/test_hr1_run_later.py`, 9 new cases):
  - `HELD_FOLDERS`, derived from the patterns;
  - the walk finds the held folders, each after the ones above it: it searches `.git` only for its own held folders, walks into `.claude` for a nested repository, ignores a link named `.cursor`, and skips `node_modules` unless the root is inside one;
  - both caps and an unlistable folder end the walk incomplete;
  - in the commands, MCP and floor texts, the work folder, `sub` and `sub/.vscode` (and `.git`, `.git/hooks`) are held in that order; there is no literal under `node_modules`, for git's objects or for an ordinary folder; the floor holds up to `/`;
  - the MCP preset holds its own folder's `.git/hooks`;
  - the name filters appear in all three texts only past the cap.

**Mutations** (each red, then restored)

| Mutation | What went red |
|---|---|
| Ancestors not held (only the folder itself) | the unit order test and the real-seatbelt rename test |
| The MCP preset without the hold (`kept=[]`) | 2 unit tests and the real-seatbelt MCP test |
| `node_modules` folders held anyway (`skip = False`) | 3 unit tests and the real-seatbelt dependency test |
| The walk ignoring its entry cap | the unit cap case, the unit fallback test and the real-seatbelt cap test |
| The walk ignoring its depth cap | the unit depth case |

**Pins:** the kernel file is now 20 markers and 34 cases.

**Checks:**
- Merged `origin/main` first (clean merge).
- The local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`) ran before the pin update and gave 30046 passed, 62 skipped and 2 failed. One failure was the pins (expected; updated afterwards). The other was smart1's hanging-rc test (a known flake), which passed when run alone.
- After the pin and hard-rule edits, the marker-pin and hard-rules tests passed (76).
- ruff in CI's scope and `check_added_chinese.py --base origin/main` are clean.
- gitleaks over `origin/main..HEAD` found no leaks.
- The macOS run of the kernel file (`-m macos -o xfail_strict=true`, JUnit, `scripts/check_macos_counts.py`) gave 34 ran, 0 skipped, 0 failed, matching its pin.
- CI's macOS job is the authority.

**Not done here:**
- git's consumer-view check for a `.git` prepared elsewhere (HR-1b);
- the bypass corpus for these shapes (letter case, links, `.git` files), which is Codex's;
- the walk's cost on a real large work folder such as `~`, which is not measured. Past the cap it falls back to holding by name.

## Review delta 7: a cap on the held folders (review at `3c258159`)

**The blocker.** The walk capped entries and depth but not how many held folders it found. `held_ancestors` checked each folder against a list, so the build was quadratic, and it runs on the event loop for every sandboxed command. Every literal also goes on the command line (`sandbox-exec -p`), so enough of them pass ARG_MAX (1 MiB on macOS, the environment included) and no command can start.

**The fix.**
- `held_ancestors` judges membership with a set beside the output list, so the build is linear in the folders held. Nothing else on that path checks membership against a list of held folders (the walk already dedups with a dict).
- The walk now also stops after `WALK_HELD = 256` held folders, and after `WALK_HELD_BYTES = 128 KiB` of literal text for them and the folders above them inside the walk. Past either, the walk is incomplete and takes the existing closed fallback: the by-name filters (`run_later.folder_filters`), the log line and the stop note, as for the entry cap. The count alone doesn't bound the size: 256 held folders, each 32 deep under long names, could still pass ARG_MAX. The byte cap bounds the held literals whatever the layout. The reason and the measurements are in the comment above the caps.
- Profile size at the cap: about 73 KB for the commands profile with 2,000 repositories (19 KB with none). The worst case is about 19 KB plus 128 KiB of literals plus the constant by-name line, which stays well under 1 MiB.

**Measured** (pytest tmp folders under the SBX harness's scratch HOME; N sibling repositories, each with `.git/hooks` and `.vscode`; build is `commands_profile`, start is `sandbox-exec -p … /usr/bin/true`; load average about 6 to 8):

| N | before: build, start, profile | after: build, start, profile |
|---|---|---|
| 0 | | 0.009 s, 0.015 s, 19 KB |
| 200 | 0.37 s, 0.22 s, 140 KB | 0.027 s, 0.062 s, 73 KB |
| 400 | 1.17 s, 0.78 s, 261 KB | 0.025 s, 0.062 s, 73 KB |
| 800 | 4.09 s, 2.94 s, 503 KB | 0.026 s, 0.062 s, 73 KB |
| 2,000 | 23.4 s, then `OSError: [Errno 7] Argument list too long` (1.24 MB) | 0.027 s, 0.062 s, 73 KB |

**List items, fixed.**
- **The note** no longer blames the folder's size for `git init` or `git clone`, which HR-1 refuses in every sandboxed folder. It now says: "This working folder is too large to map, so Arslan holds the folders those files live in (such as .git and .vscode) by name everywhere in it." SECURITY.md says the same: past a cap no new held folder (a `.git`, a first `.vscode`) can be made in that run, and the note says the folder was too large to map. HR-1b revisits it.
- **`_TOO_LARGE`** is set or cleared only by `commands_profile`, keyed by the work folder its walk started from. `run_later_folders` no longer touches it, so an MCP server's walk (which covers its own folder too) and the floor's walk leave the command note alone.
- **Under the floor**, held folders are held in place only inside the work folder. Elsewhere on disk their files stay held by name, but the folders themselves can move. SECURITY.md's run-later paragraph and a comment in `minimal_profile` now say so.

**Tests**
- Real seatbelt (`tests/server/sbx/test_hr1_run_later_kernel.py`, 1 new marker and case): with 2,000 repositories in the work folder, the walk and build take 0.033 s (bound: under 1 s), and the profile is 78 KB with the by-name line. The work folder is marked too large to map. A command starts, a hook write is refused and a file beside it is written. A repository past the cap still moves, and its `.git` and `.vscode` are refused by name once it has moved.
- Unit (`tests/server/test_hr1_run_later.py`, 5 new cases, 1 updated):
  - the count and byte caps end the walk incomplete, and the walk returns at most `max_held` folders;
  - with 400 repositories, the walk returns exactly `WALK_HELD` and the commands profile is under 256 KB;
  - 40 deep chains with long names (fewer held folders than the count cap) end at the byte cap;
  - after an uncapped walk of 1,000 repositories, `held_ancestors` (3,000 held folders, 4,002 literals) takes 0.18 s (bound: 2 s, generous for a loaded parallel run; a first bound of 0.5 s on walk plus hold failed once under `-n auto` at 0.63 s);
  - an MCP server's walk and the floor's walk, complete or not, don't mark or clear the command note;
  - the note test checks the new sentence.

**Mutations** (each red, then restored and diffed)

| Mutation | What went red |
|---|---|
| List membership back in `held_ancestors` | the linear test: 8.1 s against its 2 s bound (6.0 s against the first 0.5 s bound) |
| Both caps removed | the 2,000 case (no fallback, a 1.33 MB profile, past ARG_MAX), the 400-repository cap test and the byte-cap test |
| Byte cap removed (count cap kept) | the byte-cap test |
| `run_later_folders` marking `_TOO_LARGE` again | the MCP and floor note test |

**Pins:** the kernel file is now 21 markers and 35 cases.

**Checks** (head `a44ee579`):
- The local full suite (`ARSLAN_SECRET_KEY=ci-secret pytest -q -p no:cacheprovider -n auto`, after the bound change) gave 30055 passed, 62 skipped and 1 failed: `test_k9b_steering`'s iPhone case, a known flake that passed when run alone.
- The HR-1 unit file, the hard-rules tests and the marker meta-test passed (294).
- ruff in CI's scope and `check_added_chinese.py --base origin/main` are clean.
- gitleaks over `origin/main..HEAD` found no leaks (9 commits).
- The macOS run of the kernel file (`-m macos -o xfail_strict=true`, JUnit, `scripts/check_macos_counts.py`) gave 35 ran, 0 skipped and 0 failed, matching its pin.
- CI's macOS job is the authority.

**Not done here:**
- the build still runs on the event loop; it is now bounded (about 30 ms at the cap), so moving it off the loop is left as an option;
- the carried-over list items (round 5's `.gitmodules` row, round 4's script and `make` item, round 3's items 4 to 6) and this round's item 4 (the walk lists folders from Arslan's own process, including closed Desktop, Documents and Downloads when the work folder is home).

## Review delta 8: the walk skips private folders

**The problem** (delta 7's open item 4). The held-folder walk listed every folder under the work folder. When the work folder is home, or contains them, that listed `~/Documents`, `~/Library` and the other folders macOS's privacy controls (TCC) protect, which can raise a privacy prompt. It also listed the folders the user keeps closed.

**The fix (⓪Plan's ruling, the per-folder design).**
- `run_later.held_folders` never lists, or goes below:
  - the user's closed folders (the `closed` list the commands profile already receives);
  - `~/Desktop`, `~/Documents`, `~/Downloads`, `~/Library`, `~/Pictures`, `~/Movies` and `~/Music`.

  Both lists are built by `run_later.private_folders`, by real path, so a `~` that is itself a link works. The walk recognises a folder by its real path or by `(st_dev, st_ino)`: the inode comes from the listing, and the device is read only when the inode matches one of these folders. Links still aren't followed, so a link elsewhere that points into one of these folders leads nowhere. The skipped folders come back in `HeldWalk.skipped`.
- Inside each skipped folder, every held folder is held by name with `(require-all (subpath "<folder>") <one regex of the held names>)` (`run_later.private_filters`). The path goes into an SBPL string through `sandbox_profile.subpath`, never into a regex. The usual `node_modules` exemption applies. The skipped folder is also passed to `held_ancestors`, so it and the folders above it stay in place, and the by-name hold can't be renamed out of the way.
- **Why per folder, not the whole fallback:** only the skipped subtrees lose the ability to make a new `.git` or `.vscode` in that run. `git init` and `git clone` keep working everywhere else in the work folder.
- A walked folder that is one of these folders, or lies inside one, is walked as before. Arslan already works there, for example in a work folder inside `~/Documents`, or an MCP server's own folder inside `~/Library`.
- `run_later_folders` takes `closed` and also returns whether the walk was complete, so the "too large to map" note no longer depends on the by-name filters. Where each profile gets its list:
  - the commands profile passes its own `closed` list;
  - the floor gets the list from `terminal_exec` through `outside_wrapper`;
  - the MCP preset has no closed list, so it skips only the seven home folders.
- SECURITY.md's run-later paragraph says this.

**Tests**
- Unit tests (`tests/server/test_hr1_run_later.py`, 10 new cases):
  - A scratch home with the seven folders and a closed one, each holding `.git/hooks` and a deeper repository. With `os.scandir` patched to record every folder it opens, none of the skipped folders, or anything under them, is opened by the walk, the commands profile, the floor or the MCP preset (the closed folder is skipped wherever a closed list reaches the walk). The ordinary folder beside them is opened.
  - A home that is a link gives the same result.
  - A work folder inside one of these folders is walked.
  - In each profile's text, every skipped folder gets its `(require-all (subpath …) …)` filter, written out in full in the test, and a literal for the folder itself. No literal points inside a skipped folder.
  - With nothing to skip, the profile has no such filter and the note isn't set.
- Real seatbelt (`tests/server/sbx/test_hr1_run_later_kernel.py`, 1 new marker, 2 cases: `~/Documents` and `~/Library`). The scratch HOME is the work folder. In a repository inside the skipped folder, these are refused: a hook write, renaming `.git` or `.vscode`, the rename round trip, and making a new `.git`. A file beside them is still written and an ordinary folder still moves. In an ordinary folder of the home, a new `.git` is made. Measured: `git init` exits 1 in both places. In the ordinary folder it makes `.git` and then stops on HR-1's hooks folder, as in any work folder. In the skipped folder it makes no `.git`.

**Mutations** (each red, then restored)

| Mutation | What went red |
|---|---|
| Skip removed | all four listing cases, the link case, the three profile-text cases, both kernel cases |
| By-name hold dropped for skipped folders | the three profile-text cases; with the kernel's text assertion disabled too, renaming `.git` and `.vscode` inside `~/Documents` and `~/Library` succeeded |
| `Music` missing from the list (the test writes the seven names out itself) | all four listing cases, the link case, the three profile-text cases |

**Pins:** the kernel file now has 22 markers and 37 cases.

**Checks** (head `4c2688fb`):
- Local full suite (`-n auto`): 30068 passed, 62 skipped.
- ruff in CI's scope and `check_added_chinese.py --base origin/main` are clean.
- gitleaks over `origin/main..HEAD` found no leaks.
- The local `-m macos` run with `check_macos_counts.py`: 816 passed and 3 failed, all fsevents cases (`test_fsevents_reveals_no_external_metadata[mcp]` and `test_fsevents_restores_node_watch[none, port-22]`). Rerun alone, they still failed. They aren't caused by this change: the `[mcp]` case fails in its unsandboxed `(allow default)` control step, and the node-watch case runs on the default-deny base, which this change doesn't touch. No pin difference was reported. CI's macOS job is the authority.

**Not done here:** the MCP preset doesn't receive the user's closed list (it has none), so a closed folder that isn't one of the seven is walked under a granted `~`.

## Review delta 9: consumer aliases

**The class.** A held name (`.vscode/settings.json`, `.envrc`, a git hook) or a held folder (`.vscode`, `.husky`, `.git/hooks`) is a link whose real path is in an exempt place: today, a `node_modules` folder, whose held-shaped names #813 exempts. Seatbelt matches the real path, so a write through the link was allowed, while the consumer (an editor, git, an agent) reads the file through the held name. With the exemption off the same writes are refused, so the hole is the exemption plus the alias.

**Measured first** (real seatbelt, a profile that allows everything except the new rule; macOS 26.6.2, kept as `test_the_symlink_rule_alone_refuses_links_and_nothing_else`):
- (a) `sandbox-exec` accepts `(deny file-write-create (require-all (vnode-type SYMLINK) (regex …)))`. **Yes.**
- (b) `symlink` at a held name (`.envrc`) and at a held folder name (`.vscode`) is refused. **Yes, EPERM.**
- (c) Renaming a link made under an ordinary name onto either is refused by that rule. **Yes, EPERM.** A regular file renamed onto `.envrc`, a folder renamed onto `.vscode`, `mkdir .claude` and an ordinary link are not refused.
- Also found: `sandbox-exec` refuses a string longer than about 1,000 bytes ("Error reading string": 1,005 read, 1,032 not). So the rule is one regex per family plus one for the held folders' names (`run_later.MAX_REGEX`, checked when the regexes are built), not a single alternation.

Since (a) and (c) hold, the kernel rule is used, and no post-run fallback was needed.

**Design**
- **Part 1, links that exist when the profile is built.** The held-folder walk (`run_later.held_folders`) now looks at each link it lists, using the listing's own type, with no extra call. Only a link at a held name or held folder name gets one `realpath`. The link is an alias when its real path leaves the folder the link is in, for any reason: into `node_modules`, a sibling folder, or anywhere. `.git/hooks`, `.git/worktrees` and `.git/modules` are now listed too, for their links. Aliases come back in `HeldWalk.aliases`, and their real paths in `targets`, which count against the walk's caps.
  - When the walk finds an alias, that profile drops the dependency exemption (`kernel_filters(aliased=True)`: the bare regexes, the same switch as a root inside `node_modules`). This applies to the commands profile, the floor and the MCP preset.
  - An incomplete walk drops it too, since it can't vouch that there is no alias where it didn't look. The cap's by-name fallback is bare as well.
  - The alias's real path, and the folders above it, are held in place through `held_ancestors(kept=…)`. Without this, a command could rename a dependency's `.vscode` (the target of a `.vscode` link) away, write in it under another name and rename it back, because the walk skips `node_modules`. This also closes a held name that links to an ordinary-named file in a sibling folder.
  - Inside the private folders the walk doesn't list (delta 8), the by-name hold was wrapped with the exemption. It is now bare and covers the held names as well as the held folders' names (`private_filters`), since the walk can't see an alias in there.
  - Logged as a warning naming up to five aliases. The commands profile records them (`command_sandbox.aliases_in`), and the stop note adds: "Here some of them link out of their folder (…), so they are held inside dependency folders (node_modules) too in this run."
- **Part 2, links made during the run.** Each profile denies `file-write-create` over `(require-all (vnode-type SYMLINK) (regex …))` for every held name and held folder name, at any depth and with no dependency exemption (`run_later.symlink_filters`). It is written before the names' denies in the commands profile, the MCP preset and the floor that holds them. An ordinary file or folder of those names is another vnode type and is made as before. The held names' file-write deny already refused a new link at a held file name; the new part is a held folder name (`.git`, `.vscode`, `.claude`, `.codex`, `.gemini`, `.cursor`, `.git/worktrees`, `.git/modules`).
- SECURITY.md's run-later paragraph says this. Two new HR-0 rows were added: `run-later/aliases` and `run-later/new-links`.

**Tests**

*Restored here.* The body's full Tests section had been condensed at delta 10 and its earlier text wasn't recoverable (GitHub's edit history isn't reachable from here, and the delta 9 commit message has no test list), so this list is reconstructed from the delta 9 commit's test files (`e5ce7bd1`): the test functions and their cases.

- Real seatbelt (`tests/server/sbx/test_hr1_run_later_aliases.py`, 4 markers, 28 cases). The presets are the commands preset, the MCP preset (its granted folder) and the outside floor that holds the files, unless a case says otherwise. Each run lays out its folder first, and the profile is built afterwards, so the walk sees the links.
  - `test_a_held_name_linked_into_a_dependency_is_refused_and_so_is_the_dependencys` (7 shapes in 3 presets, 21 cases). The shapes are `.git/hooks/pre-commit`, `.envrc`, `.vscode/settings.json`, `.claude/settings.json`, `.npmrc` and `.pre-commit-config.yaml`, each a relative link to the same name in a dependency under `node_modules/<stand-in>/`, plus the held folder `.vscode` linked to the dependency's `.vscode` and written through as `.vscode/tasks.json`. In each, three steps are refused: the write through the link, a write to another dependency's `.vscode/launch.json` (the exemption is off), and renaming the link's target away. Both targets keep their old content.
  - `test_a_held_name_linked_into_an_ordinary_sibling_folder_is_refused_and_turns_the_exemption_off` (3 cases). `.envrc` is linked to an ordinary-named file in a sibling folder, and `.vscode` to the sibling's `.vscode`. Writes through both are refused, and so is a write to a dependency's `.vscode/tasks.json`, though nothing links into `node_modules`. The sibling's file and the dependency's file keep their old content.
  - `test_no_link_is_made_at_a_held_name_during_the_run_and_ordinary_ones_are` (3 cases). `symlink` at each of `.vscode`, `.git`, `.claude`, `.cursor`, `.envrc`, `.npmrc`, `.mcp.json`, `.pre-commit-config.yaml` and `.husky` is refused, and so is renaming a link made under an ordinary name onto each (18 refused steps). No link is left at those names. Controls, with no alias in the folder: a dependency's `.vscode/settings.json` is written (the exemption still works), the ordinary link is made, and `mkdir .vscode` and `mkdir .git` succeed.
  - `test_the_symlink_rule_alone_refuses_links_and_nothing_else` (commands preset, 1 case): the measurement above, on `(allow default)` plus only `run_later.symlink_filters()`. `sandbox-exec` accepts it (a); `symlink` at `.envrc` and `.vscode` is refused (b); renaming a prepared link onto either is refused (c); two ordinary links, a file renamed onto `.envrc`, a folder renamed onto `.vscode` and `mkdir .claude` are done.
- Unit (`tests/server/test_hr1_run_later.py`):
  - `test_the_walk_finds_the_held_names_that_link_out_of_their_folder` (new): in a tree where `.envrc` and `.vscode` link into a dependency, and `.git/hooks/pre-commit` and `.claude/settings.json` link into a sibling folder, the walk is complete and its `aliases` are exactly those four, with their real paths as `targets`. `.npmrc` linked to `.npmrc.base` beside it is not an alias, and neither is an ordinary-named link into `node_modules` (a walk from `sub` finds none).
  - `test_an_alias_turns_the_exemption_off_holds_its_target_and_says_so` (new): in the commands, MCP and floor texts, the SYMLINK create rule is followed by the names' bare regexes, the dependency exemption is absent, and the targets (the dependency's `.vscode`, the dependency folder above it, and the sibling hook) are literals in the held line. The warning log names the alias with `.vscode`, and the stop note says "Here some of them link out of their folder (" and names `.envrc` and `node_modules`. A plain folder's profile built afterwards has no such note and is exempt again.
  - Changed: past the cap, every profile writes the bare by-name line (`folder_filters(..., aliased=True)`) and not the exempting one; in a skipped private folder the by-name hold is one bare `(require-all (subpath …) (regex …))` per held path regex, with no dependency exemption; `_tree`'s `.cursor` link now points to a folder beside it (not an alias); `RUN_LATER_TEXT` and the cap and private-folder goldens follow.

**Mutations** (each red, then restored)

| Mutation | What went red |
|---|---|
| Exemption kept despite an alias (`kernel_filters` ignores `aliased`) | 24 of 28 kernel cases: all 21 node_modules shapes and the 3 sibling cases |
| Only `node_modules` targets count, not "leaves its folder" | the 3 sibling cases |
| The SYMLINK create deny removed (a rule that matches nothing) | the 3 new-link cases and the measurement |
| Held folder names left out of the link rule | the 3 new-link cases and the measurement |
| Held folder names left out of the walk's alias check | the 3 held-folder (`.vscode`) node_modules cases |
| The alias's target not held in place | the 3 sibling cases |

**Pins:** `test_hr1_run_later_aliases.py` has 4 markers and 28 cases. The kernel file is unchanged at 22 and 37.

**Checks** (head `e5ce7bd1`, with `origin/main` at `81d3c06e` merged in):
- Local full suite (`-n auto`): 30245 passed, 62 skipped.
- ruff in CI's scope and `check_added_chinese.py --base origin/main` are clean.
- gitleaks over `origin/main..HEAD` found no leaks.
- The local `-m macos` run with `check_macos_counts.py`: 834 passed and 13 failed, all in `test_shell_grammar_differential.py`, a known flake. Rerun alone, that file passed (50 cases). No pin difference was reported. CI's macOS job is the authority.

**Not done here**
- ~~A held folder linked to a folder named otherwise (for example `.vscode -> vsc`, or a `.git` that is a link to a folder with another name): the walk doesn't count it as an alias when its target stays in the same folder, and the files under the target's own name match no held regex, while the consumer reads them through the held name.~~ Covered by delta 10. (Restored here; the body had kept only its first words. Its wording is reconstructed from the PR's remaining-risk line on a `.git` linked to a folder named otherwise and from delta 10's description of the hole.)
- A link of an ordinary name (`pkg -> node_modules/x`), opened by an editor as its own workspace, is not an alias.
- A hard link is not a link to the walk (see the hard-link note).
- **HR-1b's `.sample` exemption has the same shape, and this delta doesn't close it.** A pre-existing `.git/hooks/pre-commit -> pre-commit.sample` stays inside its own folder, so it isn't an alias here. A write through it reaches the exempt `.sample` name, and git runs it as `pre-commit`. New links and renames onto a hook name are refused already. HR-1b's owner should count a hook-name link whose real path is a `.sample` as an alias, and drop the sample exemption in that run.

## Review delta 10: link targets

**The hole (⓪Plan).** A checkout can make `.vscode` a link to `vsc` (git stores links). `vsc/settings.json` matched no held regex, and VS Code reads it as `.vscode/settings.json`.

**The fix.** Each link the walk lists at a held name or held folder name is mapped (`run_later._below`: the family patterns relative to the link's path). `run_later.link_filters` denies, at its real path (`RunLaterHold.at_targets`, all three profiles):
- a held file as a literal;
- a `**` folder as a subpath;
- fixed names as literals (`vsc/{tasks,launch,settings,mcp}.json`, `gd/config`, `gd/hooks/**`);
- `*` names as `(require-all (subpath <folder>) (regex …))`, the depth counted in `/[^/]+` with no path in the regex.

Names are held by real path and by spelling under the target. A missing path is held at its first missing component, so a broken link's target can't be made. Targets stay in place and count toward the caps, with their filter bytes. A target folder is listed for links on, by the consumer's path, unless it's in an unwalked private folder.

**Tests.** Seatbelt (`test_hr1_run_later_link_targets.py`, 5 markers, 36 cases), each in commands, MCP and floor:
- eight layouts: held names refused; `vsc/other.json`, `c/notes.md` and `c/sub/settings.json` written;
- two hops;
- broken links;
- controls;
- `.git -> gd`: hooks and configs refused, objects written, `gd` held. The `.git` file form is HR-1c's.

The unit tests cover the mapping, filters, caps and the private guard.

**Mutations** (each red): denies removed (21+2); whole subtree (18); names unmapped (18); broken links skipped (3); targets or bytes uncounted (unit); no listing through (3); private listed (unit).

**Checks** (`c3524821`):
- Suite: 30297 passed, 62 skipped, and 2 failed (manifest order and counts; fixed, 6 passed alone).
- ruff, the language check and gitleaks are clean.
- `-m macos` on the three HR-1 seatbelt files: 101 ran, and no pin differed.

**Not done here**
- An ordinary-named link opened as its own workspace root (⓪Plan's point 2), such as `pkg -> node_modules/x`, keeps the dependency exemption.
- No link is mapped past the caps or in unwalked folders.

## Review delta 11: links past the held-folder cap, and the profile as a file

**The hole (Codex, at `c3524821`).** With 200 or 1,000 links at held names, the held-folder cap (`WALK_HELD = 256`, `WALK_HELD_BYTES = 128 KiB`) tripped and ended the walk. The by-name fallback can't name a target with an ordinary name, so those targets stayed writable (6 strict xfails). With 50 links, all held.

**The fix (⓪Plan's ruling, one number changed: see below).**
1. Links are outside the held-folder cap. Past it the walk goes on: it keeps no further held folder (those are held by name, as before), but every link it sees at a held name or held folder name keeps its target's filters (`link_filters`, `at_targets`) and its place in `kept` (the target and the folders above it held in place). Only the entry and depth caps, or a folder it can't list, end the walk.
2. Links have their own cap, `WALK_LINKS`. Past it, `run_later.TooManyLinks`: no profile is built. A command in the sandbox, or under the floor that holds them, doesn't start (`terminal_exec._not_started`, code `too_many_links`, `command_sandbox.links_note`: the working folder has too many links at protected names). An MCP server doesn't start (the session's open fails with that message). Only links at held names count; a pnpm-style `node_modules` full of ordinary links doesn't.
3. **`WALK_LINKS` is 256, not 4,096.** Measured on macOS 26.6.2, `.vscode -> vsc` links in a tmp folder, commands profile. Python builds the profile in about 0.2 s for 200 links, 0.3 s for 256 and 0.9 s for 1,000, but sandbox-exec's own compile, at every start, grows with the square of it:

   | links | profile | sandbox-exec start |
   |---|---|---|
   | 0 | 28 KB | 0.02 s |
   | 50 | 94 KB | 0.09 s |
   | 200 | 291 KB | 1.0 s |
   | 400 | 554 KB | 4.8 s |
   | 600 | 817 KB | 10 s |
   | 800 | 1.08 MB | refused: "data object length 65588 exceeds maximum (65535)" |
   | 4,096 | 5.4 MB | aborted after 4 min (`INSTR_JUMP_NE_MAX_LENGTH` assertion) |

   So 4,096 can't start, and 1,000 can't either. 256 keeps a start near 1.5 s. A denser form (one `(require-all (subpath <target>) (regex <depth-counted names>))` per link instead of a literal per name) compiles 1,000 links in 4 s and 4,096 in 152 s: not enough to restore 4,096. **For ⓪Plan to confirm the number**; it's one constant.
4. The profile goes to sandbox-exec as a file (`-f`), in the commands wrapper, the floor's wrapper, the MCP preset and the `available()` probe (`code_sandbox`'s computation preset and `ssh_exec` keep `-p`: not in this delta). `command_sandbox.write_profile` makes it new with `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW`, mode 0600, so a file or a link already at the path fails the start and is never followed. **Where: Arslan's data folder (`sandbox-profiles/`, a 0700 folder of ours), not the run's TMPDIR.** The run's TMPDIR is writable by the run's other commands (a background one could rewrite a later command's profile between its writing and sandbox-exec's read), and an MCP server's own folders by that server. The data folder is closed to all three presets, with the folders above it held. argv is otherwise unchanged: `[sandbox-exec, "-f", <file>, ...]`.
5. Cleanup. A command's file goes when the process has exited, in a `finally`: success, failure, a time limit, a cancel, and a failed start (exec error). sandbox-exec reads it at its start, and the command's own start isn't confirmed separately. Cancelled while the wrapper still builds (it runs in a thread now, off the event loop), the file goes when the thread ends (`command_sandbox.in_thread`). An MCP server's file goes once it has answered `initialize` (so sandbox-exec read it), or with the session's stack (a failed start, a closed session).
6. Build speed, so thousands of ordinary links cost little: `_below` answers a path with no held component by one regex per component and compares compiled components; `listable` compares strings; `link_filters` resolves below a real target by `lstat` per component; `sbpl_string` returns a plain string without its per-character loop (same output).

**Measured** (warm, three runs each, the commands profile's build only):
- 50 / 200 / 256 links: 0.02–0.06 s / 0.17–0.25 s / 0.19–0.32 s; 257: `TooManyLinks` in 0.12–0.27 s.
- pnpm-like, 5,000 ordinary links in `node_modules`: 0.007–0.010 s, against 0.007–0.009 s with no links.
- The same 5,000 links in a folder the walk lists: 0.62–0.77 s, against 0.55–0.65 s without them (the walk's listing, not the links).

**Tests.**
- Seatbelt (`test_hr1_run_later_link_cap.py`, 3 markers, 16 cases), each in commands, MCP and floor, each layout with more held folders than `WALK_HELD`, delivered by `-f`. With 200 and 256 links, every target's held name is refused and unchanged, a target is held in place, and an ordinary file beside them is written (6). With 257, 1,000 and 4,097 links no profile is built (9). From the product path, in the sandbox and under the floor, the command doesn't start, the note says why, and no file is left (1).
- `test_hr1_profile_file.py` (15, portable, sandbox-exec stood in for):
  - the file is 0600, opened with O_CREAT, O_EXCL, O_NOFOLLOW and O_WRONLY, in a 0700 folder;
  - it's gone after success, failure, the floor's run, a time limit, a cancel, a cancel during the build, and a failed start;
  - a file, a link or a dangling link already at the path fails the start (commands and MCP), nothing runs, and the link isn't followed;
  - the MCP file lives outside the server's folders, and the session removes it once the server answers, or on a failed start;
  - the link cap's note comes back from the product path.
- Unit (`test_hr1_run_later.py`): targets outside the held caps, and their own cap; ordinary links don't count (4,000 pnpm-like links under a cap of 1).
- Updated for `-f`: `test_sbx3a_commands_profile.py`, `test_sbx6_mcp_proxy.py`, `test_sbx5a_cap6b.py` (its `args[1]` check would have passed vacuously), `test_capability_sandbox.py`, `test_hard_rules_absolute.py`, `test_s2a1_sandbox.py`, through `tests/server/sbx/profile_files.py`. The SBX harness keeps `-p` for its own small profiles.

**Mutations** (each red):
- targets back under the held cap: 2 unit and 3 seatbelt red;
- the link cap failing open: unit and seatbelt red;
- O_EXCL dropped (O_NOFOLLOW kept): 4 red;
- cleanup skipped on a failed start: 6 red;
- the count including ordinary links: 2 unit red.

**Checks** (local):
- Suite: 30543 passed, 62 skipped and 6 failed. Five were `-f` consumers (`test_hard_rules_absolute.py`, `test_s2a1_sandbox.py`) that read argv after the file was gone; fixed, and those files plus the sixth (`test_smart1_interactive_path.py`, the known loop-wait flake) then passed alone (231).
- ruff, the language check and gitleaks are clean.
- `-m macos` on the touched seatbelt files: 165 of them passed, and no pin differed. `test_sbx3_commands.py` errored at setup only when collected with the others (a fixture not found); alone it passed (32).

**Not done here**
- `WALK_LINKS` is 256 by measurement, against the ruled 4,096 (above).
- A start of 1.5 s near the cap is paid at every command. A work folder that sits near it all the time is slow, not open.
- A profile file left by a crash stays in the data folder (closed to every preset, random names); no sweep at start.
- `code_sandbox` (run_python, artifact checks) and `ssh_exec` still pass `-p`; their profiles are small and hold no links.
