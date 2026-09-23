# Stable public-input preparation — 2026-09-24

Source baseline `cffdaa8f4e975780f456cf0ba0b4ea764b29c503`. No paid model,
credential/profile read, native install or release action in this batch.

## Complete inputs archived

`evals/companion/stable_sources.py --collect` (run as a Python module) fetches
only seven fixed public URLs. The five original README revisions match **all
five historical SHA-256 values**. Complete bodies and provenance are retained
under `stable-0140-live-evidence-20260924/public-inputs/`, outside Git. This is
input collection, not a model reading the page or a generated source receipt.
Existing archives are checked and reused; no overwritten baseline or refetch
masquerading as the earlier snapshot.

| Source | Raw bytes | Local extracted characters | Current 12,000-character reader cap |
| --- | ---: | ---: | --- |
| Lightning current | 10,438 | 9,436 | Fits |
| Lightning legacy | 9,958 | 9,462 | Fits |
| OpenSquilla English | 35,785 | 33,376 | Truncated |
| OpenSquilla Chinese | 32,837 | 18,871 | Truncated |
| Serena current | 15,097 | 14,051 | Truncated |
| Planck abstract page | 78,858 | 4,011 | Fits after extraction |
| SH0ES abstract page | 50,055 | 4,103 | Fits after extraction |

The extraction probe uses the same trafilatura library on archived bytes, but
does not claim a live `web_extract` receipt. The actual executor still caps its
result to 12,000 characters. R1/R4 therefore need a supported bounded way to
read relevant content beyond the initial segment before spending calls; do not
increase test-only limits or relabel the first segment as a complete read.
R3's complete extracted inputs fit; runtime/source support still needs review.

## R2: genuine public disagreement selected before model execution

The fixed [Planck v4 abstract page](https://arxiv.org/abs/1807.06209v4) gives a
base-LambdaCDM-inferred H0 of 67.4 ± 0.5 km/s/Mpc. Its revision date is
2021-08-09. The fixed [SH0ES v3 abstract page](https://arxiv.org/abs/2112.04510v3)
gives a Cepheid-SN baseline of 73.04 ± 1.04 km/s/Mpc and explicitly identifies a
five-sigma discrepancy with Planck+LambdaCDM; revision date 2022-07-18.

Both estimate the same parameter, but by different methods and assumptions.
This is an authentic reported scientific tension, not a claim that identical
measurements disagree or that a later publication automatically supersedes the
earlier one. The task must retain those distinctions, uncertainty and dates,
must not select a winner unsupported by the two pages, and must not assert the
current state of this scientific debate. Only the complete **abstract landing
pages** are inputs; no full-paper reading or independent data analysis is claimed.

The canonical `S2-R2-preflight.json` freezes raw-body hashes, URLs, prompt and
semantic criteria. It includes the source-scope review required by the budget
guard. This removes the input-selection gap, **not** the task-outcome gap.
The original contract's `blocked_inputs` remains its historical snapshot;
progress is recorded in this additive preflight without changing/resetting the
contract-pinned ledger. No synthetic-conflict result is substituted.

## Paid-call wiring boundary

`stable_live.StableAdapter` now wraps a supplied, identity-checked primary:
one non-streaming call per durable reservation, a cross-process in-flight lock,
exclusive input/response/accounting records, actual usage bounds and a HALT on
unknown usage, failure or cancellation. An unfinished/partly written accounting
record after process loss blocks subsequent calls. Errors are recorded by type,
not their potentially sensitive provider message. Streaming consumers use that
same one-shot path, not the provider's retrying stream fallback.

This adapter has been tested only with local doubles. The isolated host runner
and current primary/pricing preflight still must be connected before live work.
No model key was loaded. The canonical grant remains **0/36, US$0.00 reserved**.

## Follow-up: bounded read and transport repair

The production reader now offers an explicit 40,000-character maximum while
retaining its 12,000 default. A separate 8,000-character generic tool-feedback
cut was also repaired for validated web receipts, with bounded serialization
and honest partial status when delivery itself must shorten content. All seven
archived sources fit this path in the opt-in offline replay, and their effective
text/receipts are retained in `public-reader-preflight-v1/` with implementation
hashes. This does not retroactively change the old partial live outputs or
certify the new real-model comparison. See the stable exit-plan checkpoint for
reproducer and regression results.
