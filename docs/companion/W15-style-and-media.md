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

## Restricted local-media adapter checkpoint

Implemented a host-only `MediaBackend` library with capabilities, read-only
preflight, uncalibrated estimates, fixed single-image generation, targeted cancel,
job reconciliation and PNG verification. Precise editing explicitly returns
unsupported; an unmasked image-to-image operation would not preserve unrelated
pixels. This is not a working user-facing image generator yet.

The candidate external runtime is ComfyUI 0.35.0 at immutable commit
`40c4fcdf513a4523e39d54a9d391908af8df8171`. Its source and models are not bundled.
API references: [pinned server routes](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/server.py)
and [job status normalization](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/comfy_execution/jobs.py).
The adapter uses the per-job cancel route, never global interruption. A dispatched
cancel is not treated as proof of completion. A missing job remains unresolved,
including when upstream removes a queued job without retaining history.

Host configuration requires a checkpoint revision, exact SHA-256 and license
metadata. Preflight checks source checkout, checkpoint bytes, advertised core-node
origins and memory capacity without loading a model. This does not establish that
the listening process came from that checkout, certify a model license, or isolate
custom code in an already-running service. Trusted process provisioning and
independent host authorization review are still required before enabling execution.

Requests bind owner, task, run, random job ID, model pin and parameters into an
approval digest. A private SQLite journal commits full-snapshot compare-and-swap
transitions before submission/cancellation, blocking stale and concurrent duplicate
submission across restart. Remote reads also validate the durable snapshot. Failed
or timed-out submissions are never automatically retried. HTTP is fixed to loopback,
does not follow redirects or environment proxies, and has response-size and total
request-time bounds. Only one bounded PNG with the owned output prefix is accepted;
dimensions, decoding and content SHA are checked. Artifact model SHA is the requested
pin, not independent proof of the runtime's actual model execution.

Only an authenticated read-only capability endpoint is exposed in the application.
There is no execution/configuration API or agent tool. Connections displays the
unavailable status and template distinction in all six languages; failed status
fetches remain unknown, not falsely unavailable or ready. No automatic installation,
cloud reference upload, video generation or paid service has been added.

Verification for this checkpoint:

- Media adapter/journal plus companion API: 55 tests passed (44 media tests).
- Six-language status/editor focused tests: 15 passed; TypeScript passed.
- Complete frontend regression: 234 files / 1,789 tests passed in 18.08 seconds.
- Production build passed in 3.02 seconds; existing bundle-size warnings remain.
- Targeted Python lint and whitespace checks passed. Tests used local synthetic
  bytes and mocked HTTP only, no real model or ComfyUI process was invoked.
- The Mac is still locked; actual UI inspection and D01–D08 evaluation remain
  pending. W15 and the overall release-candidate gate remain open.
