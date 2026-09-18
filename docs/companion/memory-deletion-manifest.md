# Deletion manifest — staged reconciliation, UI integration pending

The approved recovery contract requires the latest independently retained
deletion ledger to be reconciled before an old backup becomes usable.
`backup.restore` now accepts an optional deletion manifest and applies it in the
quarantined staging transaction before installing the restored directory.
Absent manifests retain quarantine and explicitly report not applied.

`memory_deletion_manifest.py` defines a bounded version-1 metadata format and
read-only export from a caller-owned database snapshot. It contains store UUID,
deletion epoch, entry IDs, per-deletion epoch, existing keyed content fingerprints
and scope identifiers. It does not export memory/revision text, source payloads,
provider credentials or the internal fingerprint key. Scope identifiers remain
private metadata; this is not a public-sharing format or an authorization token.

Parsing requires exact fields, canonical UUIDs, bounded integer epochs, digest
shape, valid scope/key combinations and no duplicate fingerprint/scope identity.
Duplicate JSON keys, extra fields, malformed UTF-8/JSON, deep nesting, more than
10,000 entries and payloads above 4 MiB fail closed. Exports over those limits
fail rather than silently truncate. The service does no file/network I/O.

Fifteen tests passed in 3.81s, including an actual repository deletion followed
by deterministic export/roundtrip, payload exclusion, malformed metadata and
resource bounds. Lint and whitespace checks passed. No existing restore path,
schema, user data or runtime activation behavior changed.

## Staged reconciliation follow-up

The coordinator refuses foreign store UUIDs, stale epochs and unquarantined
databases. It matches entry IDs or keyed fingerprints of any revision in the
same scope, erases matched content/source/revision/proposal and legacy recovery
payloads, retains empty deleted stubs, merges tombstones, and advances the epoch.
Restore already clears indexes/cached prompts and suppresses old source IDs;
reconciliation does not relax those controls. Failure leaves the destination
absent; the input archive is never rewritten. Reapplication is idempotent.

The 31-case manifest/backup/restore selection passed, including old archive →
later actual repository deletion → exported manifest → reconciled restore.
Tests cover ID and fingerprint matching, activated legacy recovery-row/index
erasure, duplicate application, foreign-store/malformed refusal, and unchanged
archive bytes. Lint/whitespace checks pass. This is source-level evidence, not
a rebuilt-package or actual host-request acceptance for M06-04.

Still required before this can fulfill the recovery contract:

- A trusted local export/import flow and independently retained latest manifest.
- Transactional failure/retry and adversarial manifest tests, plus actual
  frozen restore → host-request exclusion evidence.
- UI explanation for missing later ledgers/new-machine restores and review.

The explicit export endpoint and settings control below are now implemented;
automatic independent ledger retention and restore-import UI are not.

## Source runtime evidence after reconciliation

The M06-04 binding now makes an actual pre-deletion archive, deletes the memory
through the repository, exports the later manifest, restores to a new directory,
and binds the real task/host runtime to that restored database. Captured outbound
system/user prompts and persisted used receipts exclude the deleted text/ID.
Only an empty deleted stub/history remains, and a repeated save is refused by
`memory_previously_deleted`. This uses a scripted adapter, not a real provider.

Another test verifies unquarantined stores and stale epochs are refused without
changing the exported deletion metadata. The focused manifest/backup/restore/
runtime selection passed 44 tests (27 deselected) in 20.59s; the new runtime
binding separately passed in 2.32s. Lint/whitespace checks passed. No production
code changed in this follow-up. Package, UI and independent ledger retention
remain unverified/unimplemented, so M06-04 is not marked fully complete.

## Explicit authenticated export

`GET /api/v1/memory/deletion-manifest` now exports through the authenticated
companion router and existing session transaction. Responses use `no-store`,
an attachment filename and `nosniff`. Uninitialized stores and invalid/oversized
exports produce stable 409 codes; parser diagnostics are not returned. There
is no import/write method at this endpoint.

Settings → Memory & Data includes a Lucide download control using the existing
authenticated request helper. It only runs on click, prevents overlapping
requests, ignores results after departure, cleans up its temporary download
link/URL, and shows a localized generic failure without backend diagnostics.
All six languages explain private metadata, separate storage, re-export after
deletion and the absent restore-import UI. No saved-file success is claimed:
the browser/desktop download destination still depends on its download support.

API/manifest tests passed 36 cases in 1.53s. Two frontend suites passed 8 tests
in 1.61s, including delayed URL cleanup and no download after departure;
TypeScript, targeted lint and whitespace checks passed. Native file download,
visual layout and a complete regression/package rebuild remain unverified.
