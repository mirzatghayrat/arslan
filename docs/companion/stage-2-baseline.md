# Stage 2 — offline boundary baseline, 2026-09-23

Source baseline: `dd3f78371621f0cb34d78cdfa34c105555ae463d`.
Work branch: `codex/research-stage2-2026-09-23`, isolated from the frozen
beta.4 candidate. No paid model, user documents, installed application data,
external account actions or release changes are used by this batch.

## What this baseline does and does not measure

These are synthetic parser/runtime regressions, not completed user tasks.
All 12 pilot outcomes remain **not_run**. Their denominator stays 12; no
completion percentage is inferred from the number of passing unit tests.
The full live input pack and model configuration are not yet frozen.
Existing regression fixtures are reusable boundary evidence, not substitutes
for the pilot's public sources, human usefulness review or live model output.

| Pilot | Offline boundary evidence to reuse | Still required for pilot acceptance |
| --- | --- | --- |
| S2-R1 | `tests/test_research_evidence.py`: unread/fabricated sources rejected | Three frozen public pages; complete comparison and reviewed claims |
| S2-R2 | Same file: an exact quote does not certify a false assertion | Dated conflicting inputs and an answer preserving the disagreement |
| S2-R3 | Same file: fetch freshness is not fact freshness | Old/new official inputs and reviewed change analysis |
| S2-R4 | Same source receipt/quote boundary | Frozen bilingual inputs and language/evidence review |
| S2-D1 | `tests/server/test_pdf_source_locators.py` | Frozen short PDF, actual summary and page-by-page review |
| S2-D2 | `tests/server/test_docx_source_locators.py` | Two frozen revisions, actual differences and action items |
| S2-D3 | `tests/server/test_input_formats.py` protects text decoding | Frozen CSV, independently calculated oracle and opened output artifact |
| S2-D4 | Input-format/archive failure checks | Mixed valid/unsupported inputs, retention and honest end-user explanation |
| S2-M1 | `test_project_identity_is_reloaded_for_each_task` | Confirmed project rule used correctly in a useful answer |
| S2-M2 | `test_rejected_guess_stays_out_of_later_context_and_preserves_correction` | Natural-language guess/correction interpretation and useful answer |
| S2-M3 | `test_summary_regeneration_excludes_deleted_memory_sources_from_later_task` | Real summarization and paraphrase review after deletion |
| S2-M4 | `tests/server/test_task_repository.py`: checkpoint, cancellation, uncertain writes | Interrupted research flow with useful persisted evidence and explicit recovery |

Memory test names above refer to `tests/server/test_memory_multiturn_runtime.py`.
Scripted adapters exercise production prompt and storage boundaries but do not
establish real-model quality. No live budget has been authorized.

## Reproduced blocker 1: Word revisions pollute current text

Before the repair, both new regression variants failed: paragraphs/inline runs
inside `w:moveFrom` (and defensively `w:del`) reached extracted text alongside
the new content. A moved deadline could therefore appear twice or contradict
the current requirement. This directly affects S2-D2's attribution boundary.

Repair:

- Exclude deletion/move-source subtrees, including nested textboxes.
- Retain insertion/move-target text and original XML paragraph indices.
- Prepend a bounded extraction disclosure when tracked revisions occur.
- Do not claim full revision-history comparison, accepted changes, rendered
  layout fidelity or all Word revision semantics. Original files remain intact.
- Apply the same reader to ephemeral and knowledge-ingest paths; no compression
  model rewrites source positions. If the disclosure cannot fit the extraction
  budget, report truncation rather than silently returning an unqualified body.

The reproducer and fix are synthetic XML-level evidence, not Word UI validation.
No attempt is made here to support a complete Word revision renderer.

## Verification recorded for this repair

- Pre-fix: both `revision_source` variants failed, exposing old source text.
- Post-fix: document locators, format readers, memory multi-turn runtime,
  task repository and research evidence suite: **108 passed** (89.58 seconds).
- Final document locators plus extract API and accepted-file-type agreement:
  **106 passed** (3.41 seconds), including the two additional ingest/limit tests.
  These groups overlap; do not add them as unique tests or pilot successes.
- Ruff and `git diff --check` passed. Tests retain the existing Starlette/httpx
  deprecation warning. No real model or paid service was invoked.
- No native build, visual acceptance or new release was produced by this patch.
