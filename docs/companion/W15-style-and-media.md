# W15 — style evidence and media workflows (in progress)

Starting point: `8dfdae69`. This checkpoint does not complete W15 or certify the
D01–D08 real-task evaluations.

## Versioned project style references

The existing memory repository now supports a structured `StyleReference` on a
project-scoped `style_rule`: reference type/location, positive or negative use,
rationale and tentative/confirmed interpretation. It reuses the same revisions,
deletion/restore controls, source ownership, proposal review and cloud-memory
permission policy rather than creating a parallel preference database.

The Memory editor exposes these fields in all six languages. Evidence is visible
in proposal review, source details and revision history. Reference locations are
inert text: saving them neither opens nor uploads a file, nor claims that a source
was inspected. A user-confirmed interpretation is distinct from source verification.

Tentative interpretations and agent-inferred references stay proposed. Existing
host text-only confirmation digests cannot approve a newly attached reference or
remove its evidence. Confirmation uses the user review flow. References cannot
be written as global or task memory; temporary/no-learning callers remain blocked.
One-time choices therefore cannot silently broaden into global style rules.

Project context carries the rule, polarity, source and rationale as reference data,
subject to the existing scope/owner/status/cloud filters and the complete token
budget. Invalid or unconfirmed reference structures are excluded. Changed evidence
on an otherwise duplicate rule requires explicit editing, not silent replacement.
Older clients omitting the new field preserve existing evidence on compatible
edits; explicit user removal is versioned. Deleting the memory erases its reference
metadata along with all old revisions.

## Verification

- Existing memory/API tests: 26 passed.
- New style tests with memory/context regressions: 45 passed before the additional
  sensitivity case. Style/context/restore selection: 32 passed.
- Six-language editor submission, inert-source rendering and resource parity:
  11 focused frontend tests passed. TypeScript and targeted Python checks passed.
- Tests use synthetic project references and local databases, no actual reference
  file reads, media backend calls, cloud upload or model invocation.
- Combined style/memory/context/restore/API regression: 59 tests passed in 17.59
  seconds. Complete frontend regression: 233 files / 1,782 tests passed in 18.81
  seconds. Production build passed in 6.11 seconds; existing chunk-size warnings
  remain. Real-browser layout inspection is still pending the locked Mac.

## Still required

- Complete the pinned media backend adapter contract (capabilities, preflight,
  estimate, generate/edit, cancellation and verified artifacts), without arbitrary
  node/model installation. Missing backend/license/hardware must remain explicit.
- Provide and exercise the editable/runnable design workflow and unavailable-backend
  fallback; verify font/overflow/interaction truth and output corruption handling.
- Run actual UI checks and permitted D01–D08 evidence; retain unsupported and
  human-judgment dimensions rather than treating this contract test as a score.
