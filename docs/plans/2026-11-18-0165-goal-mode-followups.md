# Goal mode (L7): follow-ups for v0.1.65

Goal mode ships in v0.1.64 **off by default**: Settings › Advanced, `goal_mode`, see `settings_service.goal_mode`. This list holds the work left after the v0.1.64 stack (#857 … #991, #993). It also holds the later items from that stack's reviews.

- **Owner:** the goal-mode lane (LOOP1), unless an item names another.
- **Must land before goal mode is on by default:** the items marked **Before default-on**.

## Decided for v0.1.65

- **Folder judgements.** The judge reads a named folder's files directly inside it, within a bounded number of files and characters. Today a judgement over a folder gets no verdict (`judged_not_a_file`), and the goal hands the check to the user. This changes the "never a folder" bound for a check's own subject only, and needs its own review.
- **Before/after for change checks (T8 fix A).** When a goal starts, the host copies the text of each judgement check's file. The judge then gets "Before this goal:" and "Now:". That makes "shorter" or "unchanged" checks judgeable; today they stop for the user.
- **goal-outputs cleanup.** Removed outputs are kept under `data/goal-outputs/<goal>/<time>`, with no cleanup today. Three rules:
  - clear a goal's folder when the goal completes successfully;
  - delete it with the goal or with its conversation (**Before default-on**);
  - remove anything older than 30 days.
- **Leftover-process stop (Before default-on).** The stop message is localized, with Chinese first. It also gives the user a simple way to end the named process: a reply that has Arslan end it, or a button on the card.
- **Status words.** The takeover and status replies show the raw status token (for example `review`). Localize them in `goal_left` and `goal_status`.
- **A version conflict after drafting** ends `/goal` as `TASK_REVIEW_REQUIRED task_version_conflict`, with no line that says why. Add one.
- **`/goal edit start <B>` while another goal runs** keeps the edit, but the reply only says another goal is running. Say that the edit was saved.
- **A failed goal gets no card after a takeover.** `_open` excludes the failed phase. Include it.

## Later items from the v0.1.64 reviews

### Leftover processes and the host's check runs (#986, #991)
- **The disclosed residual.** macOS hides the environment of its own binaries, so a process that called `setsid`, was reparented and runs a platform shell is invisible to the leftover check. The full fix is to run the host's check where no leftover process can write.
- **A re-planter during the replay.** A process started by work code the check imports, during the host's own replay runs, isn't detected between runs.
- **FIFO in `_digest` (pre-existing).** `goal_mode._digest` reads with `read_bytes()`, so a protected file replaced by a FIFO blocks every verdict. Use the `O_NONBLOCK` + `fstat` pattern `_clear` uses.
- **The keep fallback.** The fallback folder under the per-user temp folder is removed by macOS's periodic temp cleanup.
- **Unlink by name after the clone or copy.** Compare `fstatat(name)` with `fstat(src)` before the unlink.
- **The TMPDIR scan** reads every process's environment. Limit it to processes started after the goal's first recorded command.
- **Hard links (pre-existing).** Check whether a sandboxed command can hard-link a protected file into the workspace; the commands profile doesn't deny `file-link`.
- **Pseudo-paths on the card.** "(a process …)", "(kept in …)" and "(over the … bytes)" are pseudo-paths in `changed`, so the card shows them as protected files. Give them their own blocker field.
- **The process table guard** runs before date parsing. Check the parsed rows instead; this is theoretical under `LC_ALL=C`.
- **The copy fallback** reads to end of file, not to the size it checked. Cap the read.
- **`KEEP_MAX`** applies per outputs line, not per verdict. There is also no total cap.
- **Tests:** a nested-path case for the finished-run name rule. The `[left-its-group]` test should assert the pid, not the interpreter name.
- **Stop messages** cut long commands at 160 characters. Cut from the middle instead, so the script name stays visible.
- **`_clear`'s input** includes only paths matching the check's outputs that aren't protected or accepted.
- **The "didn't write it again" reason** is given after a gate refusal, a declined card or no exit code. Check `type(exit_code) is int` first.
- **`fnmatchcase`'s `*` matches `/`,** and it also decides what is moved.
- **`goal_checks.room()`** has no hard cap when no budget is in scope.

### Drafting and the judge (#989, #993)
- **A cancel that lands after the goal row is committed** leaves no card until a reload. Shield the tail after the commit.
- **The drafting chip can stay up in other windows** after a budget stop or TaskError during drafting. Clear it on a task_state that is no longer running.
- **The chip clears on any `message` frame,** for example a background job's result. This is cosmetic.
- **Untested:** the `clock.expired()` clause of the budget label, and `_set` re-raising TaskError during drafting.
- **Missing drafting filter phrasings.** The filter that drops a judgement restating a `check:` line misses "exits with status zero", "exits successfully" and non-English wordings.
- **Documentation judgements.** The filter still drops a documentation judgement that says "the command exits …".
- **A lenient judge.** On one bench run, a judgement about a TOTAL row passed although the row was wrong.

## Already in v0.1.64 (for the record)
- The replay cap is 12 runs. A check that reveals its tests in k stages needs k + 2 runs, so more than about 10 stages can't settle. This is a known limit in the release notes.
- Leftover processes are detected and never ended. When one is found before a check line that declares outputs, the goal stops and names it.
- More than 64 MB of one check's outputs stops the goal for review. This is a known limit in the release notes.
