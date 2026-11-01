# L11-3: after the rule card (#603's follow-ups)

⑥Helper, 2026-11-01. #603 (L11-2, "make this a rule for this folder?") merged as `209e5381`. This card covers what its "Not covered" list left, plus one bug found while reading for it. Parent card: [K10-L11-folder-rules.md](K10-L11-folder-rules.md).

| | |
|---|---|
| Lane | ⑥Helper |
| Review and merge | L11-3a and L11-3b write into or remove from the user's rules files, so both are on the security surface: another session reviews at effort=max, and the user merges. L11-3b is UI, so its mock goes to the user first. |
| Branches | `claude/0164-l11-3a-remove`, `claude/0164-l11-3b-memory` |
| Tier | should (with L11) |
| Order | 3a first (a bug). 3b after the user OKs its mock. 3c is in this PR. |

## What is there (main `6953a7c4`)

- **The record of what the card wrote:** the setting `folder_rules_user_files`, path → `{"own", "lines": [{"lesson_id", "line", "sep"}]}` (`server/services/folder_rules.py:240-270`).
- **Overview lists those lines** with Remove (`folder_rules.listing`, `:401-418`; `web/src/components/workbench/OverviewTab.tsx:102-106`, `:203-206`). Remove calls `POST /lessons/{id}/rule` with `remove`.
- **That endpoint starts from the lesson row** (`server/api/lessons.py:95-103`):
  - no row → 404 `lesson_not_found`;
  - the row's `rule_offer` isn't `added` → 409 `rule_not_added`.
- **Memory deletes a lesson outright** (`DELETE /lessons/{id}`, `server/api/lessons.py:146-157`; `web/src/components/companion/MemoryList.tsx:166-168`). It doesn't look at the rules record.
- **The offer exists only as a live chat item** (`web/src/stores/arslanStore.ts:753-756`), built from the turn's `rule_offer` frame. A reload rebuilds the thread from saved messages, and the item isn't one of them.
- **The lesson's evidence already reaches the web.** `lessons.present` returns `evidence` whole (`server/services/lessons.py:157-164`), including `rule_offer` and the offer record.

## L11-3a: a deleted lesson strands its line (bug)

**Today:**
1. The card adds a line.
2. The user deletes that lesson in Memory.
3. Overview still lists the line under the file with Remove, because the rules record keeps it.
4. Remove gets 404, and the toast says it failed. The line can only be removed by editing the file by hand, and the record keeps listing it.

**Fix (recommended):** Overview's Remove works from the rules record, not the lesson row.
- A new `POST /conversations/{id}/folder-rules/remove` with `{file, lesson_id, line}`:
  - `file` is a key the listing returns for each file: the real path's index in the conversation's found files, never a path the client chooses;
  - the server resolves `file` against the conversation's current listing, finds the entry matching both `lesson_id` and `line`, and calls `folder_rules.remove_rule`.
- If the lesson row still exists, its `rule_offer` becomes `removed`, as today.
- The old lesson-based `remove` stays for the live card.
- **Why both `lesson_id` and `line`:** SQLite can reuse a deleted row's id, so a later lesson could carry the same id.

**Other option, for the user to decide (an extra):** Memory's delete sheet for a lesson whose line is in a file says so, and offers "Also remove it from AGENTS.md". That is UI, so it goes in 3b's mock. Without it, deleting a lesson leaves the file as it is, and the user removes the line from Overview. That matches how Claude Code treats `CLAUDE.md`: the file is the user's, and forgetting a memory doesn't edit it.

**Size:** about +40 server lines and +10 web lines.

## L11-3b: the offer and the line in Memory (mock first)

**Today:**
- Once the chat reloads, an unanswered offer is gone. The lesson keeps `rule_offer = offered`, so it is never offered again.
- Memory's lesson rows say nothing about rules files.

**Proposed (for the mock):** each lesson row in Memory's learned practices shows its rule state, from the evidence it already has:
- **offered:** "Offered as a rule for `AGENTS.md`", with Add / Not now. Add sends the record's own conversation id, so the server's checks are unchanged: `conversation_changed`, `folder_changed` and `lesson_changed` still apply.
- **added:** "In `AGENTS.md`", with Open (the reader) and Remove (3a's endpoint).
- **skipped / removed:** nothing.

**The mock:** the row in each state, English and Chinese, light and dark, like L11-0's. It also shows 3a's extra (the delete sheet's line), so the user can pick it there. Nothing is built before the user's OK.

**Size:** about +60 web lines and six-language strings in `web/src/locales/workbench.ts` (no JSON locale, #525).

## L11-3c: the real-Mac smoke

The steps #603 listed are added to `SMOKE.md` in this PR, under "K10 + L11".

## L11-3d: from #621's effort=max review (#603's code)

#621's review and re-check found these in #603's and K10-1's file paths. The new Remove reaches them too. They're all Low; each needs a failing test first, from the reviewer's probes:

- **F2, no lock.** The rules record is read, the file edited, and the record saved, with nothing held across those steps. A double click on Remove (two requests at once) can find the same record line twice, and the second removal takes the user's own identical line. Fix: one `asyncio.Lock` around `add_rule` / `remove_rule`. One process serves the app, so no file lock is needed.
- **F4, the separator comes off the wrong copy.** When Add put a separator newline before its line (the file had no final newline) and the same line appears twice, Remove takes out the last copy plus a newline. That can strand the first copy without its newline, or take the final newline off the user's copy. Fix: record where Add wrote (the file's length before), and take the separator only when the line still sits at that spot.
- **F6, two opens and a rewrite in place.** `_take_out` reads with one open and writes with another. A file replaced in between (an editor's save) loses that edit, and a crash in the middle of the write leaves it half-written. Fix: read and write through one descriptor (`O_RDWR`, then `fstat` to check it's the same file), so an edit made in between is never written over. The write stays in place, as #603's F5 decided, so the file's mode, owner and other attributes stay as they are.

- **R5, a folder swap between the read and the write, on Linux (#621 re-check).** #621 checks the folders with a realpath before the read, and on macOS the write's `O_NOFOLLOW_ANY` refuses a link anywhere in the path. On Linux, a folder swapped for a link after that check is still followed by the write. Fix: with F6's single descriptor, cover `_append` too. Open the folder first with `O_DIRECTORY | O_NOFOLLOW` at each step, then the file relative to it (`dir_fd`), so no later swap can redirect it. Arslan ships for macOS, so this is CI's platform and the server's, not the user's.
- **R6, the read side follows folder links (#621 re-check).** K10-1's `_read` opens each folder with `O_DIRECTORY` and no `O_NOFOLLOW`, so a folder link in the path is read through. It's a read, not a write, and the text counts as outside content unless D3 trusts it. Fix: `O_NOFOLLOW` on the folder opens too, plus a check that the walked folder is its own realpath. A refused folder adds a note, as a refused file does.

**Fails closed since #621 (R4), as corrected by #626's review (R9):**
- **A touched subfolder that becomes a folder link after Add.** Add and Remove refuse it (409 `rules_file_refused`) instead of following it. The user can still edit the file by hand, and Overview keeps listing the line.
- **A project folder moved, with a link left at the old place.** The conversation's folder resolves to the new real path, so this isn't a link refusal:
  - Add answers `folder_changed`.
  - Overview lists the file under its new path, where the record has no line, so it shows no Remove.
  - The line stays in the file, and the record keeps the old path.
- **The offered → added check** in `/lessons/{id}/rule` runs outside the write lock. Two Adds at once from the same card could both pass it. The second append is then a duplicate line, recorded twice. Overview lists both, and its Remove takes each one out.

Size: about +60 server lines. Security surface: an effort=max review, and the user merges.

## Not here

- **Showing the live card again after a reload,** by saving it as a thread item. 3b's Memory row covers the same need without a new kind of saved message.
- **Model-initiated writes** to `AGENTS.md` / `CLAUDE.md` (HR's rule, unchanged).

## Four lines (`docs/sessions.md` §6)

1. **References:**
   - Claude Code's memory files: the user edits them directly, and `/memory` opens them (`code.claude.com/docs/en/memory`).
   - ChatGPT's "Manage memories": each saved memory is listed with its own delete.
2. **Raw material:** the file:line list under "What is there".
3. **Method:**
   - **3a, failing tests first:**
     - Add, delete the lesson, then Overview's Remove: the line is gone and the record is empty (today, 404 and the line stays).
     - The same with a second lesson that reused the id and added a different line: only the matching line goes.
     - A `file` key that isn't in the conversation's listing: refused.
     - A hard-linked or symlinked file is still refused (#603's N1, through the new path).
   - **3a, mutants:** match on `lesson_id` only; take `file` as a client path; skip the listing check.
   - **3b:** web tests per state (offered, added, skipped and removed); Add from Memory sends the record's conversation; Remove calls 3a's endpoint and the row reloads. Mutants on each.
4. **External evidence:**
   - CI runs cited.
   - The SMOKE steps on a real Mac.
