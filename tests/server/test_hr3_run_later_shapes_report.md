# HR-3 parser fix and adversarial command-shape report

Parser-only follow-up to the shapes evidence at `2175cf57`, against product base
`6353205a882046842a4bec13fd8c17d2050bfae4`. The product change is confined to
`server/services/terminal_policy.py`. The command gate is unchanged.

## Changes

- `_sed_script_targets` is a new local helper that reads command boundaries,
  addresses, substitution delimiters and escapes before recognizing `w`/`W`
  commands or the substitution `w` flag. A filename is the rest of that line.
- `_sed_targets` reads explicit expressions and the implicit first script;
  file-backed scripts return unknown. Existing in-place operand checks and
  whitespace/semicolon splitting remain additive.
- `_tool_targets` finds package-manager verb pairs across options, skips known
  separate option values, and retains both readings of unknown options. npm's
  `c` alias is recognized. Existing prefix hits remain conservative holds.
- `_command_targets` recognizes the requested Python module and versioned pip
  spellings as pip, without adding other tools.

## Corpus counts before and after

The original 620 cases (619 distinct command strings) have 565 expected hits
and 55 expected misses. Their disjoint observed outcomes are:

| Original corpus | Named hits | Unknown hits | Misses |
| --- | ---: | ---: | ---: |
| Before | 410 | 147 | 63 |
| After | 418 | 147 | 55 |

All eight direct-write misses are fixed: joined sed `w` and substitution `w`
for each of the three held names, plus npm's separate `--prefix` and
`--location` values. The writers family changes from 60 named hits, 15 unknowns,
and 6 misses to 66 named hits, 15 unknowns, and no misses. Configuration tools
change from 9 named hits and 2 misses to 11 named hits and no misses. Every
other original family is unchanged.

The additional 94 cases cover 55 expected hits and 39 expected misses. They
exercise both sed names, expressions, uppercase `W`, flags, escapes, alternate
delimiters, groups, addresses, newlines, full filenames, file scripts, option
values, aliases, unknown options, and pip spellings. Controls cover replacement
text, read operations, option values resembling verbs, and unrelated tools.
Each added hit also asserts its named target or the unknown sentinel.

| Expanded 714-case corpus | Named hits | Unknown hits | Misses |
| --- | ---: | ---: | ---: |
| Before | 414 | 147 | 153 |
| After | 468 | 152 | 94 |

Thus the expanded corpus has 620 hits and 94 misses after the fix, with no
unexpected outcome. Unknowns count as hits, not as named targets.

## Gate matrix and remaining strict xfails

The eight fixed shapes have ordinary passing parser and `never_auto`
assertions. Each also passes all five modes of the click-lift matrix: outside
conversation grant; sandbox off with an unsandboxed grant; sandbox off with an
unsandboxed rule; sandbox off with ask-all and an exact text grant; and seatbelt
unavailable with an unsandboxed grant. These are **40 passing matrix cases**,
each checking the once-only card, user acceptance, and rejection of a non-user
callback. The original three-mode card assertions also remain and pass.

The matrix now contains 35 shapes across five modes: 30 shapes pass completely,
and these five retain their original strict xfails in every mode:

- Assignment followed by a variable redirection.
- An eval containing a direct write.
- A function definition containing a direct write.
- An `env -S` command containing a direct write.
- A `find -exec` command containing a direct write.

Those commands already return unknown and show the ordinary once-only card.
The frozen gate clears an unreadable unknown hit before enforcing a user click,
so a callback recorded as a grant can still reach the fake executor. This is
blocker 2, not a parser miss. **Exactly 25 strict xfails remain.** No other
xfail is retained or introduced.

Historical shapes-only validation was **1,285 passed, 65 xfailed**. The expanded
file now has **1,569 passed, 25 xfailed**; its additional passing cases include
the eight fixes, their five-mode matrix coverage, and the new parser assertions.

## Differential

The disposable pytest harness loads an unmodified copy of the base policy
module and compares complete target lists for the shapes and existing HR-3
test commands: 1,364 distinct command strings. Calls made by the other requested
test files bring the observed total to 1,365, with the same transitions.

| Family | Original corpus: empty to non-empty | Expanded checks: empty to non-empty |
| --- | ---: | ---: |
| sed / gsed | 6 | 22 |
| npm | 2 | 17 |
| pnpm | 0 | 6 |
| yarn | 0 | 7 |
| pip, including Python module forms | 0 | 7 |
| **Total** | **8** | **59** |

There are no non-empty-to-empty transitions, no changes between two non-empty
target lists, and no transitions in unrelated families. Sixteen exploratory
npm/pnpm option-value spellings also retain their original conservative holds;
the prefix fallback prevents the option-aware scan from removing those holds.
This is conservative policy parsing, not a claim to validate every CLI invocation.

## Mutation and validation

A scratch copy of the unchanged base policy module supplied `run_later_targets`
in a focused pytest mutation run. No generated command was executed. The
per-test monkeypatch restored the fixed callable after each test; the product
source was never overwritten with the mutation.

The mutation produced **233 failed, 51 passed**:

| Assertion group | Mutation failures |
| --- | ---: |
| Shape hit assertions | 59 |
| `never_auto` assertions | 59 |
| Added exact-target assertions | 51 |
| Five-mode matrix for the eight original misses | 40 |
| Original three-mode card assertions | 24 |

All eight original fixes fail again, including all five gate modes. The 51 new
hit shapes that require the fix also fail their parser, `never_auto`, and target
assertions. The 39 added non-write controls and four previously covered hit
shapes keep passing (51 assertions total).

Final requested gates:

- `test_hr3_run_later_text.py`, `test_hr1_run_later.py`,
  `test_shell_grammar.py`, and `test_hr3_run_later_shapes.py`:
  **3,407 passed, 25 xfailed**, with the existing Starlette/httpx deprecation warning.
- Ruff over `server/` and `tests/`, without fixes: passed.
- `git diff --check`: passed.

All policy probes and tests run in-process under pytest with disposable HOME,
cache, and temporary directories and the requested CI secret. One existing
HR-1 test would launch `true`; the disposable harness replaces its `_execute`
boundary with an in-process result while retaining the test's executor,
hold-propagation, and outside-floor assertions. The harness is not committed.

## Not claimed

- No fix for blocker 2 or changes to the frozen command gate.
- No live shell writes, exploit execution, kernel/seatbelt proof, network test,
  or exhaustive shell/sed dialect coverage.
- No inspection of scripts, archives, copied trees, existing symlink contents,
  Makefiles, or user startup files. Original documented residuals remain.
- No complete repository test run, dependency sync, or gitleaks scan.
- No Claude or Astra review occurred. The required reviewer footer records the
  intended handoff, not a completed review.
- No fetch, push, PR creation, or changes to `.github/`.
- First-command isolation is not claimed retroactively: the initial task-file
  read preceded discovery of its environment requirements. Subsequent commands
  explicitly use a non-login shell and the disposable HOME/cache/tmp setup.
