# Companion evaluation catalog

The bounded [Stage 2 synthetic input pack](STAGE2.md) has a separate 12-case
scope; it does not change this catalog, holdouts or the 90-attempt denominator.

This is **not** the existing 30-test engineering acceptance suite and does not call a model or an external account. It defines 30 product-task families, each with three attempts, plus 60 multi-turn memory scenario specifications.

The initial catalog deliberately says `real_inputs_pending`. Actual project inputs, immutable input hashes and authorization must be supplied before `real_frozen` is valid. Visible task families are not secret holdout inputs: development and holdout input sets must be independently sourced and frozen before tuning. Memory scenarios currently have `specification_pending_runtime_binding`; validating their JSON does not mean the memory policy passes them.

Partial cross-turn runtime bindings now exist in `tests/server/test_memory_multiturn_runtime.py`.
See [the evidence and limitations matrix](../../docs/companion/memory-runtime-bindings.md):
these inspect actual host prompts and receipts with a synthetic adapter, not real
model answer quality. They do not mark the 60-scenario catalog completed.

The initial split reserves 20 development and 10 holdout families before runtime implementation. Holdout IDs: R03/R06/R08, A03/A07/A10, D03/D06/D08, C04. Their real materials are still pending; seeing a task description is not access to a frozen holdout input. Do not feed holdout outcomes into automatic optimization.

## Evidence and scoring

- `schema.py` validates task revisions, budgets, checker types, source references and attempt identity.
- `scoring.py` requires independently produced check evidence. A successful run label alone does not pass. Safety checks cannot be optional or model-judged.
- Missing attempts, unsupported tasks and budget failures stay in the fixed denominator. No best-of-three selection. Attempts for one task must share configuration and initial-state hashes.
- Synthetic/replay evidence is counted explicitly but never creates a live completion rate. A live report requires authorized, frozen real inputs. A critical failure or unverified critical check blocks release even when the aggregate rate is high.
- `release_blocked=false` is only the absence of these local blockers, not full release approval. Human UX review, platform/packaging tests and the other plan gates still apply. Eligible live reports include a reproducible 95% task-cluster percentile-bootstrap interval; the three attempts stay together when tasks are resampled. Small-sample and all-identical-score degeneracy remain limitations, not evidence of certainty about unseen tasks.
- Evidence references are locations, not proof that the referenced contents were verified. Domain checkers must produce/validate them; the assistant must not grade its own statements as completed work.

Generate an honest all-unrun report:

```sh
.venv/bin/python -m evals.companion.report --output /tmp/companion-unrun-report.json
```

Supply checker results with `--attempts path/to/evidence.json`. The output path must not already exist. This command only validates and summarizes files; it never starts the tasks.

The budget values are initial development limits, not a retrospective adjustment mechanism. Freeze their final values with real inputs before measuring; changes require a new catalog revision and cannot be applied retroactively to existing attempts.
