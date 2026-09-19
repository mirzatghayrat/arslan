# Recovery key continuity — implementation design, not acceptance

Source review: `7bd142c6`, 2026-09-19. The candidate-only primitive described in
the implementation checkpoint below now exists; durable-source resolution,
native consent and coordinator integration do not. User-facing activation
remains unavailable. There is no new key storage mechanism.

## Problem

A restored database can pass trial under its backup's original secret, then
fail on a later normal launch because `secret_bootstrap` selects the existing
installation secret instead. Supplying the backup secret only to the immediate
restart does not solve subsequent independent launches. Writing it into the
profile/backup or replacing the installation key violates existing separation
and can break the retained original profile.

## Preferred direction to validate

Keep the installation's durable external secret unchanged. With explicit native
consent, re-encrypt credentials **only in the stopped, disposable restored
candidate**, from the explicitly supplied backup secret to the installation's
already-established durable secret. Retain its database salt. Then trial,
finalize and normal restart must all use that same installation key source.
The source archive and original profile remain untouched and usable on rollback.

This is a proposed integration direction, not permission to rewrite credentials
automatically. Existing `recover_with_salt` is not directly suitable: it uses
process-global active-secret/config state and permits partial recovery. The
offline path must instead use pure `crypto_material.keyring` and the shared
`secret_inventory`, with no secret bootstrap, key generation or salt discovery.

## Required refusal and verification cases

- Resolve the normal launch source with existing precedence, without repairs.
  Verify a durable external source; never label an environment-only secret as
  persisted. Disabled file access, production mode, explicit/file disagreement,
  missing/unsafe/changed source or unsupported configuration must stop activation
  until the user deliberately establishes a supported source.
- Capture explicit consent for adapting restored credentials, separate from
  archive selection. Secrets stay in bounded local pipes, never argv, logs,
  web/model IPC, journals or backups.
- Own lifecycle/profile locks, bind candidate identity, refuse live SQLite
  journals and malformed schema/salt/tokens, and cover every inventory location.
  One unreadable or oversized credential aborts the entire operation. Never
  migrate only the readable subset and claim success.
- Use a transaction with rollback and verify every rewritten value using only
  the target key. Prove candidate failure leaves no partial committed migration;
  source archive, original profile and external key are byte-preserved.
- Bound startup/trial receipts to the rewritten database. Require clean shutdown
  and a separate fresh process launched through the ordinary durable-key path,
  without injecting the backup secret. Verify credentials after that launch.
- Test same-key/no-credential cases, legacy tokens, every inventory table,
  wrong/mixed keys, write/readback failure, interruption, source replacement,
  cancellation, rollback, and a second independent restart.

Until those checks and native consent integration pass, selecting the correct
backup key proves trial compatibility only, not release-ready recovery.

## Candidate-only implementation checkpoint

`server/services/recovery_rewrap.py` accepts an active profile, a distinct sibling
candidate and two in-memory secrets. It locks both cooperative profile domains,
rejects pending activation, links, non-owned/nonregular input and SQLite sidecars,
and copies the bounded database into an owner-private temporary candidate file.
It uses only pure key derivation and the shared encrypted-site inventory. It
validates salt/schema/identity, refuses triggers on credential tables, enforces
per-token/count/aggregate limits, requires every stored credential to decrypt
as UTF-8, and verifies each target-encrypted value from the staged database.
Only a complete transaction and SQLite quick-check permit atomic replacement.
File/profile identities are rechecked before replacement. A post-replace fsync
failure remains uncertain, not an invitation to retry or activate automatically.

No caller exposes this primitive through HTTP, model IPC, the packaged control
protocol or menus yet. In particular, `secret_persisted: false` explicitly means
the primitive did not save or establish the target secret; the coordinator must
still prove that source independently and obtain explicit user consent.

Tests cover all eight current inventory examples, same/different keys, legacy
tokens without a salt, empty credentials, malformed/mixed-key rows, invalid
secrets/salt, triggers/duplicate/null identities, limits, live journals, busy or
pending profiles, symlink/hardlink input, staged write/target-readback/replace
failure and competing candidate modification. Separate-process import testing
proves no configuration or key bootstrap occurs inside the primitive.

A full-schema integration test uses a synthetic backup encrypted with one key
and an original installation encrypted with another. After candidate adaptation,
two fresh processes run the shared normal storage initialization using only the
default external `HOME/.arslan/secret_key`, without an explicit secret or key-file
override. Both decrypt the credential; subsequent switch/bound rollback retains
the original database and archive byte-for-byte. This proves storage/key-path
continuity, not full desktop restart, native consent or release acceptance.
