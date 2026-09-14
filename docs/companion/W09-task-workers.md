# W09 — temporary collaborators and versioned methods

## Delivered boundary

The host can assign up to four independent briefs in one `delegate_work` call,
with at most two workers running concurrently across the containing task. Each
worker shares the task's persisted execution budget, receives only its explicit
brief, and uses the same native model/tool loop and action journal. No permanent
Spawn is created. Existing specialist selection, names and history are unchanged.

Research, Apple release/growth, and product design methods have immutable numbered
versions. The authenticated editor saves a new version only on explicit save;
earlier runs retain their original method version. Instructions cannot grant
permissions or tools. Known credential-like material is rejected at input/output
boundaries; this is defense in depth, not an OS secret-isolation claim.

Workers are deliberately read-only: only an explicitly assigned subset of the
host's current `web_search`/`web_extract` tools is available. Recursive delegation,
memory access, file modification, connection access and external writes are not
supported. The dispatcher enforces this subset even if a resolver supplies more
tools. This also prevents two workers from concurrently modifying the same file.

## Lifecycle and evidence

Worker records belong to a task, specification revision and execution attempt.
Identical requests reuse owned results. Partial work restarts only after explicit
task resume, retaining prior output, progress fingerprints and the same budget.
Ordinary branch failure and branch-local no-progress do not fail independent
branches. Cancellation stops active and queued workers; boot and backup recovery
mark unfinished work interrupted without launching it. Atomic status updates keep
late results from undoing cancellation/recovery.

Results contain output, remaining work, artifact references (empty for this
read-only implementation), and opened-source receipts derived from successful
extraction calls. Search snippets are not counted as opened sources. A worker's
`completed` status means its response returned, not that the host task passed
acceptance. Worker runs do not receive an automatic judge verdict.

## Verification

- Twelve focused worker tests cover concurrency/context isolation, shared budget,
  deduplication, scope/recursion denial, cancellation, immutable method revisions,
  authentication, branch-local no-progress, explicit resume, boot recovery,
  backup recovery, and late result fencing.
- Frontend tests cover explicit saves, failed-save draft retention, escaped
  worker output, collapsed contributor details, and six-language key parity.
- Offline real-app UI exercise used an isolated database and synthetic adapter,
  with non-loopback HTTP disabled. A real host delegation created two worker runs,
  their saved output remained inspectable, and task acceptance remained pending.
  The method editor saved version 2 without altering version 1. Light/dark and
  900px viewport checks found and fixed a squeezed dashboard header.
- Type checking and production web build passed. Full regression results are
  recorded after verifying the frozen commit, not inferred from these checks.

## Remaining gates

Artifact-specific acceptance and bounded repair are W10. Privileged broker/OS
isolation is W11 and is not supplied by these worker scopes. This checkpoint is
not a release candidate or evidence of live model/account task quality.
