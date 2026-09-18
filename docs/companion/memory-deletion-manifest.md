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

No endpoint or automatic independently retained ledger is introduced yet.
