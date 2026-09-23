# Stage 2 — daily research assistant, bounded delivery

Approved direction: 2026-09-23. This follows the published beta.3 preview;
it does not resume the complete v1.2 goal or authorize another release.

## Batch A: identity and a small evaluation plan

- Read the running desktop version via Tauri, not `server.config.app_version`
  (whose independent default is `0.1.0`) or a baked-in frontend version.
- Show version and stable/preview classification in Settings. A plain browser
  cannot identify an installed desktop app. Older shells missing the permission
  show unavailable, never a guessed stable version.
- Offer a previewable, click-to-copy identity summary. It includes only client
  type, version and channel. No upload, account, model call, path or conversation
  access is introduced. This is NOT a complete task diagnostic bundle.
- Select 12 development cases below. Selection is not execution or a success
  rate. Existing catalog/holdout definitions and scoring rules stay unchanged.

## Existing diagnostic surfaces and privacy boundary

`TaskPanel` already exposes attempts, task budgets, events, recovery and linked
`RunReplay`. Replay already shows model, elapsed time, usage and artifacts.
`RunReplay.buildRunMarkdown` also exports user messages, system prompts and
injected knowledge; that export must not be represented as sanitized feedback.
`evolution_diagnostics` diagnoses learning eligibility, not arbitrary app failures.
Reuse these mechanisms before adding another event store or dashboard.

For user reports, request expected outcome, observed outcome, reproduction
steps and optionally a user-chosen screenshot/task ID. No background upload.
An expanded task diagnostic export needs a separate allowlist, preview and
explicit sharing action. Regex redaction alone is not sufficient.

## Fixed first-pass cases — all `not_run`

The first pass is a 12-case development pilot, not the full catalog's 90 live
attempts, and not a statistically reliable product success-rate estimate.
No holdout task is selected. Four document cases are explicit extensions of
W20, because the old 30-family catalog does not contain a document family;
they are not relabelled as existing research/design cases.

| Pilot ID | Existing basis | Input to freeze next | Required outcome |
| --- | --- | --- | --- |
| S2-R1 | R02 | Three dated public product pages, same comparison fields | Comparable claims and direct sources; unknowns not invented |
| S2-R2 | R04 | Two sources that genuinely disagree | Describe conflict, scope and dates; no unsupported resolution |
| S2-R3 | R05 | An old recommendation plus newer official information | Identify what changed and what remains unknown |
| S2-R4 | R07 | Chinese and English sources on one question | Answer in requested language while preserving original evidence |
| S2-D1 | W20 input coverage | A short synthetic PDF with page markers | Summary and references to correct pages; no claim of visual verification from text alone |
| S2-D2 | W20 input coverage | Two synthetic DOCX revisions | Correct differences and action items, attributable to each version |
| S2-D3 | W20 input coverage | Synthetic CSV with known totals, empty cells and mixed labels | Correct computed results and usable output; disclose missing values |
| S2-D4 | W20 input coverage | Encrypted or unsupported document | Explain limitation without inventing contents; retain other prepared inputs |
| S2-M1 | M01-03 | Isolated projects A/B and a confirmed A-only rule | A uses its rule; B does not inherit it |
| S2-M2 | M04-08 | Unconfirmed guess followed by user correction | Guess is not promoted to fact; correction affects subsequent work |
| S2-M3 | M06-03 | Deleted preference referenced by an old summary | Later work and regenerated summary do not reintroduce it |
| S2-M4 | C01 | Saved bounded research task interrupted before completion | Explicit recovery retains budget and evidence, does not repeat completed effects |

Before execution, freeze exact inputs, hashes, model/configuration and checker
rules. Synthetic/replay/live results remain separate. Live model calls require
explicit model/call/cost authorization; current authorized paid-call count is zero.
Do not silently change these cases or drop failures after observing results.
Use existing evidence schemas/reporting where applicable rather than inventing
an overall green badge for a hand-picked subset. Document extensions need explicit
checker bindings before claiming execution.

## Batch B: baseline and focused fixes

Prepare isolated inputs and execute the permitted checks first. Record source
revision, inputs, environment, result/artifact, elapsed time, usage (unknown is
not zero), correction count and evidence. Human review checks claim support and
usefulness; parseability alone does not establish either.

Select at most three top blockers from the fixed cases for the first repair
batch. Reproduce before fixing; rerun affected checks and relevant existing
regressions. Broader safety failures can block delivery but are not permission
to expand into unrelated features. Report remaining failures and stop at the
batch boundary. A new preview release is a separate decision, with same-source
CI and package acceptance; this source-only batch is not installed beta.3.

## Later bounded stages

1. Compare bounded tool output and on-demand evidence retrieval on the same
   cases. Preserve full evidence and retrieval handles; disclose truncation.
   Measure whole-task cost and quality, not only a single prompt's token count.
2. Evaluate model routing in observe-only mode before changing default behavior.
3. Select one authorized external workflow only after credential/permission
   boundaries are accepted. Do not enable general browser writes now.

Icon exploration remains separate. No automatic publication, data migration,
replacement of the installed app, runtime downloads or model training is part
of Batch A.

## Batch A source verification — 2026-09-23

- App identity, Settings shell and six-locale parity: 39 tests passed.
- Existing Settings, routing, language, field ownership and locale-content
  regressions: 45 tests passed.
- Shell configuration: 3 tests passed; the only added native permission is
  `core:app:allow-version`, scoped to the existing main-window loopback origin.
  The installed Tauri ACL manifest confirms this enables only the version read.
- TypeScript, production web build, Ruff for the changed Python test and
  whitespace checks passed. The web build retains its large-chunk warning.
- No signed/native build, installed-app replacement, native visual acceptance,
  live-model calls or execution of the 12 pilot cases was performed. Native
  permission behavior still needs verification in the next rebuilt test app.
- Existing local beta.3 release-note edits were preserved, not included as
  evidence of a new source build or overwritten. No tag/release was changed.
