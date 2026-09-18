# Deletion manifest — foundation, reconciliation pending

The approved recovery contract requires the latest independently retained
deletion ledger to be reconciled before an old backup becomes usable. Existing
`backup.restore` quarantines memories but does not accept a later deletion
manifest. Quarantine is not evidence of M06-04 completion.

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

Still required before this can fulfill the recovery contract:

- A trusted local export/import flow and independently retained latest manifest.
- Same-store identity validation and cross-store refusal; fingerprints must not
  be compared under a different store key or assumed portable across stores.
- Apply deletion IDs/fingerprints and source suppression in the staged restored
  database before retrieval/index activation, without altering the old archive.
- Transactional failure/retry and adversarial manifest tests, plus actual
  frozen restore → host-request exclusion evidence.
- UI explanation for missing later ledgers/new-machine restores and review.

No endpoint or automatic importer is introduced in this foundation commit.
