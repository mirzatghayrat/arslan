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

## Interruption/retry evidence

Failure injection now covers an exception immediately after revision payload
erasure and an exception after reconciliation finishes, before transaction
commit. Each leaves no installed destination or staging directory, preserves
the original archive and live exported metadata, and allows successful retry
with only an empty deleted revision. This does not simulate process kill,
power loss or filesystem failure.

The complete manifest/backup/restore/runtime selection passed 73 tests in
78.80s, including all 39 scripted runtime bindings. Current frontend regression
passed 244 files / 1,893 tests in 22.01s; TypeScript and targeted lint passed.
The full backend suite, rebuilt package and native download remain outstanding
for the manifest changes, as do trusted restore import and independently
retained current ledgers.

## Frozen export and restored-boot evidence

`scripts/frozen_deletion_restore_smoke.py` now starts the actual temporary app's
bundled backend with disposable homes. It creates two synthetic memories,
stops the process for a pre-deletion archive, restarts to delete one via its
authenticated API, and exports the later metadata through the frozen endpoint.
It checks unauthorized refusal, attachment/no-store/nosniff headers, and absence
of memory text or the digest key. The source restore coordinator applies that
export before two actual frozen restored boots. Both expose a content-free
deleted stub, reject re-saving the deleted content, keep the other memory
quarantined/local-only, and re-export the same deletion metadata. The original
archive bytes remain unchanged.

This harness passed against backend SHA-256
`c83fe225bff2349332770559a523a52d89baa249b2fc42f0698b75d0a2a7a5e0`.
It does not capture frozen host model requests, exercise native file download,
provide restore-import UI, or prove independent automatic ledger retention.
The source scripted host-request binding remains separate evidence.

## Independent local ledger mirror

`memory_deletion_ledger` now stores a private per-store manifest in
`<database-parent>/.memory-deletion-ledgers/<instance-uuid>.json`. This is outside
the SQLite snapshot and excluded from the existing backup asset allowlist. It
is on the same machine/disk, not a separate-device backup. POSIX file-backed
databases are supported; unavailable platforms/storage report unavailable.

The repository mirrors only after a successful deletion commit. The legacy
expert-preference route, which commits its own session, does the same. Startup
refreshes the mirror after the migration/activation transaction, before seeders
or background work. A rolled-back delete never reaches the mirror. A disk error
does not undo or report failure for an already committed deletion: it is logged
generically and exposed through authenticated, no-store
`GET /api/v1/memory/deletion-record-status` (`current`, `missing`, `stale`,
`ahead`, `unavailable`). No path, key or memory content is exposed there.

Storage uses a 0700 directory, 0600 files, no-follow descriptor-relative access,
owner/type/permissions/hardlink checks, a bounded advisory lock, an exclusive
temporary file, file fsync, atomic replace and directory fsync. It refuses
corrupt/conflicting existing history and never replaces a higher deletion epoch
with a lower one. The existing manifest bounds still apply. A snapshot write
that fails leaves the old record intact where possible; startup can repair the
DB-commit/file-write gap. This is not a proof against physical disk failure or
power loss, and it does not turn the separate file and database into one atomic
transaction. An abrupt process death may leave a private pending file.

Settings offers an explicit local-record check. Six-language copy says “last
check”, distinguishes an ahead record from missing/stale/unverifiable records,
and does not claim restore safety merely because epochs match. No periodic
polling, automatic export download or filesystem path picker was added.

Validation: 77 backend cases passed in 4.98s, including rollback, mirror failure
and repair, ten concurrent first-write rounds, monotonic/history guards,
symlink/permissions/hardlink/size refusals, backup exclusion, real repository and
legacy expert deletion commits, startup and authenticated status. An initial
concurrent lock-creation failure was fixed with exclusive creation followed by
opening the existing lock; the final selection passed. Two frontend suites
passed 17 cases in 2.05s. TypeScript, targeted lint/whitespace and production web
build passed (3.31s; existing large-chunk warning).

Still open: automatic selection/reconciliation of the installation's ledger by
the application restore workflow, trusted native restore/import, actual native
download/layout, full regression and a candidate rebuild for this new mirror.
The previously verified frozen candidate predates the mirror and status UI.
