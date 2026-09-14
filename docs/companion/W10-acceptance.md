# W10 — composable acceptance and artifact checks

## Runtime integration

Acceptance checks can carry bounded declarative rules. They are not code or
execution grants. The native loop receives the criteria, records a report before
revealing its proposed final answer, and can attempt at most two repairs within
the same persisted task budget. Repeated identical failure stops sooner. Repair
does not authorize additional tools or replay successful/uncertain writes.

Every report is an immutable task event, tied to the specification revision,
attempt and SHA-256 of the evaluated candidate. CheckResult evidence references
that event. New statuses are `passed`, `failed`, `not_run`, `not_applicable`;
historical `unverified` remains readable. Conditional non-critical checks can be
not applicable only when the contract explicitly declares their applicability.
Critical checks cannot bypass verification that way.

The containing task can succeed automatically only when the declared checks pass
(or are explicitly non-applicable), files pass, and no runtime pause/error or
uncertain external action remains. Model-only votes cannot complete a task.
Manual review preserves existing deterministic evidence rather than replacing
it, and file hashes are checked again at acceptance. A wrapper that changes an
already checked answer causes another verification pass.

## Evidence implemented in this checkpoint

| Check | Evidence and limits |
| --- | --- |
| Text | Exact value, required substrings, bounded character count |
| JSON | Parseability, exact JSON value, required object keys |
| File integrity | Owned Run, no-follow file/manifest reads, regular-file and size bounds, actual byte count and SHA-256 |
| File parsing | Fixed isolated parser: UTF-8 text/JSON/CSV, images, PDF, DOCX/PPTX; optional XLSX parser is honestly not run when absent |
| Image dimensions | Actual parsed width/height, not model claims |
| Research source count | Successful extraction receipts, not snippets or URLs in prose; this does not prove claim support |
| Build/test command | Exact admitted command and argument list, actual zero exit code, optional required output value; no command is launched by the verifier |
| Model assessment | Same admitted adapter and task budget, no tools, non-critical text criteria only; malformed/unavailable assessment stays not run |
| Human review | Authenticated explicit review, retaining the other checks and blocking changed files/uncertain effects |

Factual file/source/build/readback rules cannot choose a model evaluator. A
text-only assessor cannot judge screenshot layout. Deterministic language,
screenshot layout and ASC remote-readback checks currently report unavailable;
their evidence-producing integrations remain open below. A model can assess a
non-critical text-language criterion, but that is labelled a model assessment.

## File and UI boundaries

Stored files have stable artifact IDs and host-assigned logical revision keys.
Workspace writes/edits preserve the intended contents before applying the write;
failure to preserve the snapshot prevents that mutation. The snapshot is not a
claim that the workspace remains unchanged afterward. A later verified revision
can supersede an intermediate file with the same logical key; the prior record
remains visible as replaced. Explicitly linking the old file keeps it in the
required deliverable set, so a corrupt old file cannot be hidden by a new one.
Historical files without lineage are not guessed into a replacement relationship.

Proposed local artifact links are resolved
only against Runs owned by this task/specification. A foreign URL with an
artifact-shaped path does not gain access. Invalid file candidates are not
revealed as working download links after repairs stop; a trusted localized
warning accompanies the incomplete result. The task panel separately shows
automatic checks, model assessments, human review and file status. Detailed
identifiers/codes remain available in a collapsed technical section.

The parser uses the default-deny macOS compute profile, a scrubbed environment,
resource limits and a killable process-group timeout bounded by the remaining
task time. No sandbox means `not_run`, never an unsandboxed fallback. Parser code
and the already-locked PDF/DOCX/PPTX dependencies are included in the staged
desktop runtime; no first-run package/model download is introduced. Parse success
means the supported parser opened the structure, not that layout or facts are
correct. Office archives are size/member bounded and entity-bearing XML is
rejected before document parsing.

## Verification and open integration work

Focused synthetic tests cover false file links, cross-owner/foreign links, empty
and corrupt files, symlinks, changed hashes, wrong JSON/text/dimensions, search vs
opened sources, exact command/value mismatches, finite repair, final-wrapper
changes, conditional checks, model-vote isolation and manual acceptance. A real
Seatbelt subprocess parsed a JSON fixture. Offline UI checks used isolated data,
synthetic models and loopback-only networking; failed checks removed acceptance
controls and retained an explicit resume option.

The frozen foundation (`d6324a25`) ran 4,334 passing backend tests, 14 skips,
with one failure in the explicit macOS-test population manifest after adding the
new parser test. The manifest and CI count were updated together to include that
actual macOS case; this is not a claim of a new Linux execution measurement.
Subsequent deliverable-revision tests covered corrupt/missing intermediates,
explicit old links, write/edit snapshot ownership, and budget failure before a
workspace mutation. Frontend foundation regression passed all 1,720 tests.
The subsequent local run exercised **41 macOS-only tests with zero skips**,
**125 task/recipe entry-point tests**, and **100 focused artifact/task tests**.
The six-language UI regression remained at **1,720 passing tests**. A new full
frozen rerun covers the combined revision-registration and marker changes.

Remaining cross-package integration: W13 supplies typed ASC readback; W14 claim/source support; W15
visual-review inputs; W20 broad file/media inspection and XLSX runtime support.
These are not certified by the current parser or by a model score. Full frozen
regression and release-package execution are recorded separately; this is not a
release-candidate declaration.
