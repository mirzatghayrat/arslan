# LOOP1 d2b: card titles come from the grammar

| | |
|---|---|
| Decided | The user approved the title change on 2026-11-11, relayed by ⓪Plan. ③Hands agreed the five conditions below on 2026-11-11. |
| Version | v0.1.64, should |
| Parent | `LOOP1-agent-loop.md`, slice d2 (part 1, #826: one reader pass per command in `terminal_policy`) |
| Review | max. ③Hands reads first: `card_purpose` sits next to their command chain. |
| Merge | The user's: the title text on the Bridge's `propose_run_command` frame changes (same shape, no new key). |

## What changes
`card_purpose` stops parsing a command `shell_grammar` understands. Its steps come from the grammar's one reading, the
pass the policy's rules read since #826 (`terminal_policy.reading`). A command the grammar doesn't understand keeps
`card_purpose`'s own step reading (`_parse`, now only for that path), because the grammar gives no steps for it.

**This is a behaviour change, on purpose:** card titles move. The policy verdicts (`assess`, `ask_rules`, `risk_grade`,
inside and outside the sandbox) do not. The frame's `summary` keeps its keys and types; only its values move.

## Why
`card_purpose`'s own parser has no comments, here-documents, compound commands or `!`, so some titles misled:
- `if true; then rm -rf ../x; fi` was titled "Run if". With the grammar it reads as a delete of `../x`.
- `ls # ; rm -rf /tmp/x` was titled as a delete, but the delete is commented out. It now reads as a listing.
- A here-document's body was read as steps: `cat <<'EOF'` with `rm -rf /tmp/x` in its body was a delete.

## Impact
- **Mac card:** the title and step lines. The rules list is unchanged: it is the gate's verdict.
- **Phone:** the title rides in the existing frame's `summary` and `title` (d1, #817). The frame's shape is unchanged.
- `tests/fixtures/card_purpose_vectors.json` (shared with the web tests): the vectors whose reading moved are updated
  in the same PR, so the diff shows each.

## Method
1. Differential, main against the head, over the full corpus (every string in `tests/`, the shared vectors, the
   shell_grammar differential families, the quoted-argument generators), with `outside` False and True. Verdicts and
   the rules list: 0 moves, a hard requirement. Titles: every move counted by category, with title moves where a
   once-only rule is present listed separately and first.
2. Mutants, each killed: the grammar steps dropped, the not-understood fallback dropped, redirect targets dropped, the
   rule-step preference dropped, the outside prefix dropped, the command text replaced by the title, and the two from
   #826's review (the reader pass truncated at 200 characters, or stripped).

## ③Hands' conditions (each pinned in `tests/server/test_loop1_d2b_titles.py`)
1. **The title never hides what asked.** When a once-only rule or `outside-reach` matched a step, the title leads with
   that step, before the step with the most at stake (`terminal_policy.asks_once`, read on the step's own words and the
   files it writes). Main did not prefer it: `rm -rf build && git push` was titled as the delete.
2. **The outside prefix stays.** "No sandbox · …" and the `unsandboxed` mark, per setting (ask_all with a grant, the
   sandbox off, seatbelt unavailable), and the `outside_sandbox` card's "Outside the sandbox · …" with
   `sandbox: "outside"`, on top of the new title.
3. **Unread commands** keep today's step reading, and the `unreadable` rule line stays.
4. **The full command text** stays on the card exactly as today. The title is a summary, never a replacement.
5. **In the differential report,** title moves where a once-only rule is present are listed separately and first.

## Known limits
- A rule that matched text the grammar reads as data (a here-document's body, a comment) has no step to lead the
  title. The title then reads the command that runs (often "Run cat"), and the rules line under it names the rule.
- Folders: only a command with `cd`, `pushd` or `popd` is read a second time, by `shell_grammar.read`, for where each
  step runs; the policy's pass leaves folders out by design (`test_folder_tracking_r6`).
- HR-1b's `git_config` and HR-1c's `git_include` cards have fixed titles of their own, not from `card_purpose`.

## Done means
No second parser for an understood command; every title move explained in the PR; verdicts byte-identical.
