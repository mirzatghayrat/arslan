# Release keys — custody, backup, rotation

Everything the release pipeline signs with, what happens if each piece is lost, and
what it costs to replace it. Written because the answer to "what if the signing key
is gone?" was, until now, not written down anywhere.

All eight secrets live in **GitHub Actions secrets**, which are **write-only**: once
set, no workflow log, API call, or repository admin can read the value back out.
That property is what makes the table below matter — "it's in CI" is not a backup.

## Inventory

| Secret | Used by | If lost |
|---|---|---|
| `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD` | `build_dmg.sh` codesign | **Recoverable.** Re-export the Developer ID Application certificate from the maintainer's login keychain, or revoke and re-issue it in the Apple Developer portal (Team `XULY3SAJ22`). |
| `APPLE_SIGNING_IDENTITY` | `build_dmg.sh` codesign | **Not a secret at all** — it is the certificate's common name, printed by `security find-identity -v -p codesigning`. It sits in Actions secrets for convenience, not confidentiality. |
| `APPLE_API_KEY`, `APPLE_API_ISSUER`, `APPLE_API_KEY_CONTENT` | `notarytool submit` | **Recoverable, with one catch.** Issue a new App Store Connect API key in the portal. The `.p8` content is downloadable **exactly once** at creation — a lost `.p8` cannot be re-downloaded, only replaced by a new key. Not fatal: notarization keys are freely re-issuable. |
| `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | updater artefact signing | 🔴 **Irreplaceable. See below.** |

Certificate expiry: the Developer ID Application certificate is valid until
**2031-07-27**. Notarization stops working the day it expires, and a re-issued
certificate means updating `APPLE_CERTIFICATE` — this does **not** strand installs,
because the OS checks the notarization ticket and the signature at install time, not
the identity of the signer against a previous release.

## 🔴 The updater key is the one that cannot be replaced

Auto-updates are minisign-signed. The **public** half is compiled into every shipped
binary from `plugins.updater.pubkey` in `desktop/src-tauri/tauri.conf.json`; the
updater verifies each downloaded artefact against **that compiled-in value** before
it installs anything.

Two consequences follow, and they are the whole reason this document exists:

1. **Losing the private key strands every existing install.** New releases signed
   with a different key produce signatures that old binaries reject — they keep
   checking against the public key they were built with. Those users stay on their
   current version forever until they manually download and install a new build.
   Upstream states this plainly: lose the private key and you cannot publish updates
   to users who already have the app.
2. **Rotation costs the same thing as loss.** Rotating is not a recovery path for a
   *lost* key — it is the same event, chosen deliberately. Rotate only if the key is
   believed compromised, and expect to tell existing users to reinstall by hand.

Tauri does offer a runtime `pubkey` override (the plugin builder accepts one) that
exists specifically to implement key-rotation logic — a build can be taught to trust
a *new* key ahead of time. **We do not use it**: `lib.rs` registers
`tauri_plugin_updater::Builder::new().build()` with no override, so the compiled-in
key is the only trusted key. Adopting the override would only protect installs
shipped *after* the change, so it is a future-proofing move, not a repair.

### Custody

The maintainer keeps the only readable copy of the private key offline, in the
secrets sidecar that accompanies the data backup (`arslan-secrets-<stamp>/`, whose
own README lists the exact filenames). **This document deliberately does not print
that path**: this app runs model-driven shell tools on the maintainer's machine, so
a public file naming the location of the updater key is a map to the one credential
with no recovery path. The unlock password is not stored beside the key.

Verify the offline copy still matches what ships — this compares the local public
half against the value compiled into the app, and prints nothing secret:

```bash
python3 - <<'PY'
import base64, io, json, os
conf = json.load(io.open("desktop/src-tauri/tauri.conf.json"))
shipped = conf["plugins"]["updater"]["pubkey"].strip().splitlines()[-1]
local = io.open(os.path.expanduser(input("path to .key.pub: "))).read().strip().splitlines()[-1]
print("MATCH" if shipped == local else "MISMATCH — the offline copy does not sign what ships")
PY
```

Last verified: **2026-08-11** — the offline public half matches
`plugins.updater.pubkey` byte for byte.

### If it is ever actually lost

There is no way to recover it, so the procedure is damage control, in order:

1. Generate a new keypair: `npx tauri signer generate -w <new-key-path>`.
2. Put the new private key and its password into Actions secrets
   (`TAURI_SIGNING_PRIVATE_KEY` / `_PASSWORD`) and the new public key into
   `plugins.updater.pubkey`.
3. Ship a release **and say in its notes that existing installs must be replaced by
   hand** — they cannot self-update across the key change, and they will fail
   silently, because a failed background check is silent by design.
4. Treat the stranded population as the real cost: every install before the rotation
   is frozen at its version until its user takes manual action.

## Related

- `SECURITY.md` — the trust model these keys implement.
- `packaging/build_dmg.sh` — where the Apple secrets are consumed; it injects
  `createUpdaterArtifacts` via a `--config` overlay, which is what makes the
  `.app.tar.gz` and its `.sig` exist at all.
- `.github/workflows/secrets-preflight.yml` — validates the Apple secrets without
  printing them. It does **not** cover the updater key.
