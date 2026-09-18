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

## Restore selection from a stopped current installation

`backup.restore(..., current_db_path=...)` now reads the explicitly supplied
current SQLite database in a read-only snapshot and locates its independent
ledger by store UUID. It optionally checks an imported manifest as a third
source. The current DB export closes a committed-delete/file-mirror gap when
the local file is missing or behind; a newer independent ledger wins over an
older DB. Every supplied history must belong to the same store and be contained
in the newest history; equal-epoch histories must agree exactly. Divergent,
foreign, corrupt or unsafe local evidence refuses installation rather than
silently falling back, even if a valid import was also supplied.

The selected payload is reconciled inside the existing quarantined staging
transaction. It must still match the backup store and pass its epoch checks.
Neither current DB, local ledger, imported record nor original archive is
rewritten. The result reports sources checked and which source was selected,
without exposing paths. No current installation is discovered implicitly: a
trusted caller supplies its DB path. The application restore UI still needs to
bind that argument to trusted installation configuration, not arbitrary HTTP
input. Arslan must be stopped; this service does not terminate or prove absence
of another running app instance.

The existing offline operator command now supports `--current-db-path` and
`--deletion-manifest`. Import reads are bounded, regular-file-only and refuse
symlinks. `restore --help` explicitly states the stop-app requirement. A new
machine may import an exported record without a current DB. Omitting both
retains the established quarantine behavior and reports that no later deletion
record was applied; it cannot infer deletions made after the old backup.

Six-file regression passed 109 cases in 83.27s, including all 40 scripted
host-runtime bindings. A current-installation variant of M06-04 proves deleted
content stays out of every captured new-task request and used receipt, and
re-saving remains refused. The 19-case coordinator/CLI suite was then rerun
with exact refusal-code assertions and final help text: 19 passed in 1.71s.
Targeted lint/whitespace checks passed. These tests cover current/lagging/missing
files, ledger-ahead/import-newest selection, older consistent imports, corrupt
or conflicting histories, no install/staging leftovers on refusal, unchanged
inputs, and new-machine import/quarantine. They do not prove native UI, frozen
execution of the new selector, full regression or physical crash durability.

## Packaged profile ownership before recovery

The packaged entry now holds a cooperative POSIX process lock for the complete
server run. `backup.restore(..., current_db_path=...)` acquires the same lock
before reading records or creating staging, retaining it through installation.
Busy ownership is refused immediately with `data_profile_in_use`; no PID is
guessed, no other process is signalled, and no wait silently turns a previous
attempt into a later restore. Missing-current-installation/new-machine restores
still only target a new directory and do not claim an old profile was stopped.

The stable empty 0600 lock file is `.<database-name>.arslan-lock` beside the
canonical DB path. Symlinks, hardlinks, non-regular files, foreign ownership and
unsafe permissions are refused. The file is intentionally not removed on
release: presence alone is not ownership, and unlinking could split concurrent
callers across different lock inodes. Closing the descriptor or process death
releases OS ownership. A real synthetic child-process kill/reacquisition test
passes; the process killed is only the child created by that test.

Busy/unsafe packaged startup returns a fixed error code before announcing a
server port. The desktop handshake maps only known codes to six-language
messages, and startup failure/timeout now reaps its own child. It does not kill
the owner of the busy profile. Native code compiles and its 31 tests pass; live
rendering of these messages has not been observed.

This is a prerequisite, not a completed native recovery coordinator. Older
installed versions and plain `uvicorn server.main:app` launches do not acquire
the packaged-entry lock. The operator must still stop those writers; a free
cooperative lock is not proof that every possible writer is absent. Native
stop/confirmation/file selection/restart activation, current release rebuild
and full regression remain open. No current user installation was started,
stopped, restored or replaced by these changes.

## Fixed packaged acknowledgement and regression checkpoint

Repeated packaged recovery checks exposed a separate persistence race: companion
repository cleanup could commit after HTTP success had already been sent. All
18 repository dependencies now finish in function scope, before transmission.
ASGI boundary tests verify commit-before-201 and conflict-before-409, including
the absence of a row after a refused commit. A dependency-wide guard prevents
an endpoint from silently returning to post-response cleanup.

The fixed `07e5886f` backend passed the complete offline suite (5,009 passed,
14 skipped), and repeated packaged checks now cover two immediately stopped
acknowledged creates, independent-ledger repair, profile ownership and selection
of current records during restore. The native executable and sidecar were rebuilt;
fresh/upgrade/quarantined-restore and isolated compute checks passed. Exact hashes
and evidence limitations are recorded in `W17-release-audit.md`.
This supersedes the earlier pending-rebuild/full-regression status, not the
remaining native UI, trusted activation or real-model evaluation gates.

## Exclusive final installation

The staged recovery directory is now installed with the platform's atomic
no-replace rename operation. A target created between validation and installation
is refused without replacing even an empty directory. Unsupported exclusive
rename operations fail closed and remove only our staging; the caller can retry
explicitly after resolving the destination. Tests preserve the competing
directory's inode and archive bytes and verify that eight concurrent installers
produce exactly one winner. This does not defend against hostile ancestor-path
replacement or certify power-loss durability. See the W17 checkpoint for exact
platform coverage and the still-pending frozen rebuild/native activation gates.

## Packaged offline restore entry

The sidecar now accepts `--restore-offline --archive PATH --new-data-dir PATH`
with either `--current-db-path PATH` or explicit `--new-machine`. Both modes may
also use `--deletion-manifest PATH`. This is a stopped-writers maintenance
interface, not a live HTTP route. Current-installation mode retains cooperative
profile ownership and record selection; new-machine mode without an import
cannot know later deletions and still quarantines restored memory.

The rebuilt binary itself has passed current-installation and imported-record
restoration, exclusive target refusal and two subsequent restored boots. A
separate empty maintenance HOME stays empty, without normal profile/token/key
bootstrap. The command never changes the app's selected data directory, secret
or installed binary; trusted native activation remains separate unfinished work.
See W17 for the exact binary hash and source-backup/frozen-restore distinction.

## Ownership during directory switching

The packaged/maintenance `hold()` now acquires two cooperative locks, in order:
a stable private `.arslan-profile-<namespace-sha256>.lock` in the profile's parent,
then the existing `.<database-name>.arslan-lock` inside the profile. It must own
the first before even creating the active directory. Moving the directory can
therefore no longer let another cooperating startup create a new inner-lock
domain while the original owner is still active.

The namespace hashes the directory name and DB name with a separator; it is not
a content fingerprint. Both locks remain empty and private. The existing inner
lock still respects preceding packaged owners, but those old binaries do not
take the outer lock and must be stopped before any future directory activation.
This prerequisite is tested with actual OS locks and a competing subprocess.
A durable activation journal, secret compatibility preflight, native confirmation
and health-checked rollback are still required before enabling directory swaps.

## Credential compatibility before activation

The read-only `recovery_preflight.check()` prerequisite now accepts a checkpointed
restored DB and an explicitly supplied in-memory secret. It returns counts and
statuses only: compatible, no stored credentials, secret required, unreadable
credentials, invalid salt, credential limit, or unavailable. It neither loads
the app configuration nor creates secret files, adopts salt or rewrites values.
Current and legacy ciphertext reads use shared pure derivation code. The shared
inventory includes provider/MCP credentials, SSH private identity and MCP OAuth
token/client settings; public identity and regular settings are not credentials.

The future trusted coordinator must own profile lifecycle exclusion and validate
the restored profile separately before using this result. Pending SQLite journal
files refuse the check; immutable read access is only valid while writers remain
stopped. Compatibility alone is not approval to activate a profile. Native
integration and the reversible switch journal are still unfinished.

## Internal switch journal and rollback

`profile_activation.switch_for_trial()` now provides the internal stopped-profile
substrate: credential preflight, latest deletion reconciliation, exclusive private
journal, and two no-overwrite directory moves. It preserves the original under a
unique sibling name. `rollback()` verifies recorded directory identities, moves
the candidate back and restores the original without deleting either one.
Recorded identities let rollback recover after a forward or reverse move even
when the process did not get to update another phase marker.

The pending journal is outside the moved directory and blocks normal packaged
boot/maintenance before an absent active directory can be recreated. This is not
yet exposed to a user: there is no trusted trial-boot permit, health verification,
finalize operation, native picker or confirmation. Do not invoke the internal
switch on real data as if it were a finished activation feature. Existing generic
startup-unavailable copy is only a fail-closed fallback until native recovery
guidance is implemented. W17 records the actual process-interruption test scope.
