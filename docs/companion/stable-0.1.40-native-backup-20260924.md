# Native backup closeout — 2026-09-24

## Follow-up authorized by user and verified

The user explicitly permitted the narrow path-tracking repair after the failed
v14 run. Commit `1f5ae8f8` follows only the confirmed operation's retained
original directory, preserving the original archive metadata identity and all
confirmations. External archives are unchanged. Wrong operation IDs, replaced
files (even identical bytes) and symlinks are rejected by the new Rust test.
Full Rust suite: 80 passed, one existing opt-in frozen fixture ignored; Clippy
passed with warnings denied. No additional paid model calls.

Native v15 used a new isolated copy of the synthetic profile, the same backend
`9f418a16`, and shell `1f5ae8f8`. The internal manual archive from v14 now passed
the original two confirmations, isolated trial, finalization and automatic
restart to the online Cedar workspace. Original data remained retained.
Post-stop verification checked 19 assets against archive hashes, credential
compatibility with the synthetic key, wrong-key read-only refusal, database
integrity, preserved chat and zero usage rows. A SQLite backup snapshot included
committed WAL; the initial raw preflight correctly refused leftover journals.
The verifier's initial incorrect table name `usage_logs` was corrected to the
actual `usage_ledger`; neither initial verifier error is counted as a pass.

Receipt: `../stable-0140-native-9f418a16/native-restore-v15.json`, SHA256
`64403b8fbd12637c6a1d5879f45803ada42555fd4b16e8fc463c7ab4e6d0e512`.
All owned acceptance processes exited. Prior v8 native wrong-key refusal and
v4/v5 corrupt/interrupted recovery evidence remain applicable: this change is
after credential rewrap and does not weaken those checks. This is development
bundle acceptance, not final Developer ID/notarized artifact acceptance.

The historical blocker and failed outputs below remain intact. It is resolved
by the authorized repair, not reclassified as a passing v14 run.

## Source and isolation

Backend/web source `9f418a1600433602fef978a9f23e171ed0e083e2`; native shell
final tested source `e5bb8c2d` (only backup UI fixes after that backend source).
Ad-hoc local development bundle, independent `com.arslan.acceptance.stable0140`,
still source version `0.1.40-beta.6`, NOT a release or final signed candidate.
No `/Applications` replacement, real profile or real key access. Synthetic
credential targets loopback port 9, model `never-call`. New paid calls **0**.

Evidence root: sibling `stable-0140-native-9f418a16`.
Bundle executable SHA256 `a4381fdd9af4204ed21130ba990d35639968f4beefe2002fda69706d48a44ee1`;
sidecar SHA256 `e594d49d2ee09a975a0de9ecc0ee0090fe8cd8e4fcc670adabfb3e4e53c3ba0a`.
`native-v14-inputs.json` identifies the synthetic 0.1.38 source/profile.

## Actual results

- Packaged development app booted the synthetic 0.1.38 profile (schema 0046),
  retained the synthetic Cedar conversation and reached an online workspace.
- Two automatic pre-migration snapshots were generated, both schema 0046.
  This is not the one-snapshot source-only rehearsal: the packaged startup's
  read-only preflight and later storage initialization saw different physical
  fingerprints. Subsequent current-schema restarts did not add upgrade archives.
  Three-archive retention remains the implementation cap, not an assertion of
  exactly one archive in this native run.
- Both automatic archives and all four manual archives passed every manifest
  member byte-count/SHA256 check and restored into exclusive new directories.
  Both automatic snapshots opened with pinned 0.1.38 source and the same
  synthetic key; chat, fact, credential, artifact and integrity assertions passed.
  This old-version open is source-level, not a 0.1.38 signed binary launch.
- Native Settings > Memory & Data > Create backup showed its consent, created
  a new archive, displayed its full location and external-key reminder, and
  restarted to the same online synthetic workspace. Previous archives retained.
  Final observed archive: `manual-96ed2e0ccb530441c461668e10c8a6e3abee77021d999b7ccb1abffc5f6d4a29.zip`.
- Native restore selected that archive and the original synthetic key, then
  confirmed stop/prepare. It stopped safely in Recovery paused after switching
  directories, before final activation. This is a **FAILED native round trip**,
  not a pass or deferred case. Original data and restored candidate were retained.
- Quit/reopen showed Unfinished data recovery. Explicit native Return to
  original data restored the original profile and online Cedar workspace.
  The candidate remains separate; all owned acceptance processes then quit.

Receipt: `../stable-0140-native-9f418a16/archive-verification-v14-after-rollback.json`,
SHA256 `858af7359871a2bf051a79c7f5730bc9965ef2ac128e2d5f92fe7d549a5c34eb`.
An earlier receipt `archive-verification-v14.json` scanned zero archives during
the switch and is **not evidence of passing verification**. It is retained;
the verifier now requires nonempty results. Raw logs are private local evidence,
may contain one-time synthetic tokens, and must not be uploaded.

## Native defects found and retained

1. Backup initially rejected the deliberately poisoned developer data override,
   although packaged startup ignores it. `bedf7a17` aligns the native check;
   subprocess regression confirms both poisoned overrides never select that path.
2. Disabling the parent window stranded the Cocoa completion sheet. The final
   fix keeps the native window enabled under the maintenance gate, stops the
   backend, and attaches the result sheet to its owning window. Earlier trial
   changes/archives remain recorded; unparented result was not accepted as UI proof.
3. Remaining integration defect: the selected archive is inside
   `Arslan/backups`. `switch_for_trial` renames `Arslan` to `.arslan-previous-*`.
   `NativeSteps::recheck_target` subsequently rechecks the original archive path,
   which no longer exists. The coordinator therefore pauses before Trial.
   The archive itself remains intact in the retained original directory.

## Decision boundary

N/U are **not closed**; no candidate CI, PR, tag or release created by this batch.
The user explicitly requested no change to the restore flow. Resolving item 3
requires deciding whether to permit a minimal path-identity fix in the existing
restore adapter (retain checksum/inode checks and all confirmations), or use a
different manual-backup location/copy-out workflow. Do not bypass the recheck,
claim old external-archive success covers this newly failing path, or publish.
Next: user direction on this narrow restore/backup integration boundary.
