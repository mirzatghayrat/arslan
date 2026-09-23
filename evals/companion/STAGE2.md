# Stage 2 synthetic input pack — revision 1

This is an offline boundary baseline, **not twelve completed agent tasks**.
`stage2-inputs.json` fixes twelve scenario definitions, inputs/review criteria
for eight research/document cases, and existing runtime bindings for four
memory/lifecycle cases. `stage2-inputs.freeze.json` records SHA-256 hashes for
the definitions, generators/checkers and bound runtime test files. The latter
contain the scripted turns and initial-state setup for the memory cases.
Do not silently refresh hashes after observing a failure: explain the change
and version changed inputs/check criteria before another comparable run.

All websites and products in this pack are fictional `.example` sources.
Receipts are synthesized locally; **no page was fetched**. Text admission and
tamper detection do not certify entailment, conflict resolution or bilingual
answer quality. Public-source snapshots and an authorized model configuration
are still needed for the live pilot. Original pilot IDs/holdouts stay unchanged.

Word bytes use fixed ZIP timestamps; PDF and Word inputs are generated in
memory. These are minimal parser fixtures, not visually reviewed office files.
PDF checking reads its text layer, never invokes an OCR model. The CSV output
is explicitly an independently calculated **oracle**, not an agent-produced
artifact. Currency totals exclude missing amounts without relabelling those
amounts as zero. No real user profile, secret or document is used.

## Reproduce

Use the repository's locked development environment. From its root:

```sh
python -m pytest -q tests/server/test_stage2_inputs.py \
  tests/server/test_memory_multiturn_runtime.py::test_project_identity_is_reloaded_for_each_task \
  tests/server/test_memory_multiturn_runtime.py::test_rejected_guess_stays_out_of_later_context_and_preserves_correction \
  tests/server/test_memory_multiturn_runtime.py::test_summary_regeneration_excludes_deleted_memory_sources_from_later_task \
  tests/server/test_task_repository.py::test_checkpoint_rebuilds_state_results_and_budget_across_sessions \
  tests/server/test_task_repository.py::test_cancel_is_idempotent_retains_completed_work_and_never_boot_resumes \
  tests/server/test_task_repository.py::test_uncertain_write_requires_readback_and_never_automatically_replays
```

From `web/`:

```sh
npm test -- src/__tests__/stage2-input-retention.test.tsx src/__tests__/ComposerAttach.races.test.tsx src/__tests__/attachment-delivery.test.tsx
npm run lint
```

The S2-D4 frontend check uses the fixed JSON inputs with a mocked extraction
transport and the real attachment hook/delivery path. Unsupported and invalid
files are tested both before and after valid input. It verifies state retention
and error codes, not real desktop UI rendering or end-to-end server transport.

## Recorded offline run — 2026-09-23

- Source base: `630df976` plus this input-pack change.
- Python 3.11.15, pytest 9.1.1, pypdf 6.18.1, SQLAlchemy 2.0.51.
- The explicit Python selection: **16 passed**, 11.32 seconds. These are checks,
  not 16 tasks; four memory cases map to seven parameterized/lifecycle checks.
- Frontend retention/ownership/delivery: **21 passed**, 0.826 seconds;
  TypeScript passed. Ruff and whitespace checks passed.
- Existing Starlette/httpx deprecation warning remains.
- Paid/model/network research calls: none. Memory adapter responses are
  scripted; they have no measured real-model token/cost figure.
- New product blockers found by this run: none. Previous Word revision fix
  remains separate evidence. Pilot outcome status: **all 12 not_run**.

## Remaining acceptance, not silently waived

Freeze real public research inputs, choose/authorize a model and budget, obtain
actual task outputs, and review answer quality/source support. For documents,
review real summaries/differences/calculations and open agent-produced outputs.
For memory, verify natural-language interpretation beyond scripted intent.
For recovery, run a complete interrupted research task, not only repository
lifecycle operations. Record missing or failed checks as such. This pack cannot
approve a release, bypass same-SHA CI or substitute for signed-app acceptance.
