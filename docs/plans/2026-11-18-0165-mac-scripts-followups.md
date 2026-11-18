# 0.1.65: approved AppleScript and the Reminders/Calendar path (follow-ups from the 0.1.64 pre-tag run)

**Source.** The 0.1.64 pre-tag plain-mode rerun (L7-7, DeepSeek, 2026-11-18): T1 (Reminders) fell from 3/3 to 1/3.
- **r2.** The model's approved Reminders script was kept in the command sandbox only because it had `--` comments (`task_service.unwrapped_once`, `_OSA_COMMENT`). There `current date` failed to compile (-2741), and the model asked to leave the sandbox instead.
- **r3.** EventKit has no XPC in the default-deny commands profile (since #520), by design.

0.1.64 ships only a hint for the first case (`recovery_hints.KEPT_FOR_COMMENT_HINT`, from `task_service.kept_for_comment`). The security decision is unchanged. The user split the rest into the two items below, both for 0.1.65.

## 1. Strip comments before the check, only if the checked text is the text that runs
- **Today.** A `--` or `#` comment anywhere keeps an approved inline osascript wrapped. A quote inside a comment shifts which quotes pair up, and a variable app target could hide in what looked like a string (S2a-1, ⓪Plan's re-review). So the gate reads a commented script as unreadable.
- **The change.** Remove AppleScript comments (`--` to end of line, `#` to end of line, `(* … *)`) with a tokenizer that respects string literals. Then run the bare-run check on the result.
- **Condition (the user's).** The text that is checked must be exactly the text that runs. After stripping, Arslan executes the clean version: the stripped script is what goes to osascript. It never checks one text and runs another. The card shows the script that will run.
- **Review.** Max (Opus 5.5 or stronger). This widens what runs with no sandbox.
- **Tests.**
  - comments containing quotes, `"--"` inside a string literal, nested `(* (* *) *)`, `#` after code;
  - a stripped script that becomes empty or opaque stays wrapped;
  - the executed bytes equal the checked bytes (spy on the spawn).

## 2. Common Reminders and Calendar actions without ad-hoc scripts
- **Today.** Creating a list, a reminder or an event depends on the model writing a script that passes the bare-run check. A script file, an EventKit binary, a comment, or a helper with no app named all stay in the sandbox and fail there.
- **Options, to choose before building.**
  - (a) Dedicated tools (create list, add reminder with a due date, add event), each with its own card that shows the fields.
  - (b) A one-time per-app grant ("Arslan may use Reminders in this conversation"), under which a plain script for that app runs bare without a card each time.
- **Constraint either way.** Reads are open and the guard sits on writes, as the mainstream agents do. Delete and send stay on a card.
- **Measure.** T1 ×3 on DeepSeek and Claude, with and without comments in the model's script. Also ask1a-ds T1 r2's path (a script file, `current date` with no app).
