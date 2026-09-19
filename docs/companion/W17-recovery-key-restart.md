# Recovery key continuity — implementation design, not acceptance

Source review: `7bd142c6`, 2026-09-19. No key migration or new key storage is
implemented by this note. User-facing activation remains unavailable.

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
