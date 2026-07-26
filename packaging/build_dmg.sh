#!/usr/bin/env bash
# Build the Arslan macOS app and a drag-to-install .dmg.
#
# Adapted from andrewyng/openworker's packaging/build_dmg.sh (MIT, Copyright
# (c) 2024 Andrew Ng). The step order, the dereference/framework guards and
# the notarize-then-staple-then-verify sequence come from there; the sidecar
# layout, the bundle verification and the web build are ours.
#
#   1. build the SPA          (server/main.py serves it; without this the
#                              window is blank — see verify_bundle.sh)
#   2. PyInstaller onedir     (packaging/arslan-server.spec)
#   3. verify the bundle      (imports, no AGPL, no db, no secrets)
#   4. stage into Tauri's resources slot, DEREFERENCED, + sign every Mach-O
#   5. tauri build            (produces Arslan.app)
#   6. hdiutil                (wrap into a compressed .dmg)
#   7. sign -> notarize -> staple -> spctl
#
# UNSIGNED BY DEFAULT. Set APPLE_SIGNING_IDENTITY to a
# "Developer ID Application: … (TEAMID)" identity to sign; add the
# APPLE_API_* trio to notarize. Missing either degrades with a loud warning
# rather than failing, so a fork can still build something runnable.
#
#   ARSLAN_SKIP_NOTARIZE=1   sign but skip the notary round-trip (minutes).
#                            Local builds carry no quarantine flag so
#                            Gatekeeper never prompts on this machine — which
#                            is exactly why a build made this way must NEVER
#                            be distributed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DESKTOP="$ROOT/desktop"
TAURI="$DESKTOP/src-tauri"
APP="Arslan"

# Single source of truth for the version — the same file the release workflow
# checks the git tag against.
VERSION="$(node -p "require('$TAURI/tauri.conf.json').version")"
ARCH="$("${CARGO_HOME:-$HOME/.cargo}/bin/rustc" -vV | sed -n 's/host: //p' | cut -d- -f1)"

step() { echo ""; echo "==> $*"; }

# --------------------------------------------------------------------------
# CI keychain bootstrap
# --------------------------------------------------------------------------
# On a fresh runner the certificate exists only as the APPLE_CERTIFICATE
# secret. `tauri build` does its own import later, but we sign the sidecar
# BEFORE that (step 4), so the identity has to be findable now — otherwise
# codesign fails with "no identity found", which reads like a keychain problem
# rather than a missing import. Local builds never set APPLE_CERTIFICATE and
# skip this entirely.
if [ -n "${APPLE_CERTIFICATE:-}" ] && [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  step "importing the signing certificate into a temporary keychain"
  KC_DIR="$(mktemp -d)"
  KC="$KC_DIR/arslan-signing.keychain-db"
  KC_PASS="$(openssl rand -hex 16)"
  security create-keychain -p "$KC_PASS" "$KC"
  security set-keychain-settings -lut 21600 "$KC"
  security unlock-keychain -p "$KC_PASS" "$KC"
  printf '%s' "$APPLE_CERTIFICATE" | tr -d '\n\r' | base64 -d > "$KC_DIR/cert.p12"
  security import "$KC_DIR/cert.p12" -P "${APPLE_CERTIFICATE_PASSWORD:-}" \
    -A -t cert -f pkcs12 -k "$KC"
  rm -f "$KC_DIR/cert.p12"
  # Without this, codesign blocks on a UI prompt that does not exist on a
  # headless runner and the job hangs until it times out.
  security set-key-partition-list -S "apple-tool:,apple:" -s -k "$KC_PASS" "$KC" >/dev/null
  security list-keychains -d user -s "$KC" login.keychain-db
fi

# --------------------------------------------------------------------------
step "[0/7] preflight"
# --------------------------------------------------------------------------
# Seconds, and it saves minutes. codesign only parses the entitlements file at
# step 4, so a malformed one fails four minutes into the build with
# "AMFIUnserializeXML: syntax error near line 14" and nothing pointing at the
# cause. (An XML comment cannot contain a double hyphen; a comment mentioning
# a command-line flag put one there.)
plutil -lint "$TAURI/entitlements.plist" >/dev/null || {
  echo "ERROR: entitlements.plist is not valid XML — codesign would reject it at step 4" >&2
  exit 1
}
# The updater public key must be present, or installed copies silently never
# update: Tauri accepts an absent pubkey and just produces no updater
# artefacts, which looks like a successful build.
node -e '
  const c = require("'"$TAURI"'/tauri.conf.json");
  const k = c.plugins?.updater?.pubkey;
  if (!k || k.length < 40) { console.error("ERROR: no updater pubkey in tauri.conf.json"); process.exit(1) }
' || exit 1

# --------------------------------------------------------------------------
step "[1/7] building the web UI"
# --------------------------------------------------------------------------
# BEFORE PyInstaller, which stages web/dist into the bundle. server/main.py
# only mounts the SPA when its static dir exists, so skipping this yields an
# app that answers /api/* and shows a blank window.
( cd "$ROOT/web" && npm ci --silent && npm run build )
[ -d "$ROOT/web/dist/assets" ] || {
  echo "ERROR: web build produced no assets — the app window would be blank" >&2
  exit 1
}

# --------------------------------------------------------------------------
step "[2/7] freezing the backend sidecar"
# --------------------------------------------------------------------------
"$ROOT/.venv/bin/pyinstaller" --noconfirm --clean \
  --distpath "$HERE/dist" --workpath "$HERE/build" "$HERE/arslan-server.spec"

# --------------------------------------------------------------------------
step "[3/7] verifying the frozen bundle"
# --------------------------------------------------------------------------
# Before anything is staged or signed: signing a broken bundle just produces a
# signed broken bundle, several minutes later.
"$HERE/verify_bundle.sh" "$HERE/dist/arslan-server"

# --------------------------------------------------------------------------
step "[4/7] staging the sidecar into Tauri resources"
# --------------------------------------------------------------------------
mkdir -p "$TAURI/binaries"
# rm -rf FIRST: cp writes THROUGH a symlink at the destination, so a leftover
# dev-convenience link here could clobber whatever it points at.
rm -rf "$TAURI/binaries/sidecar"
# -L dereferences. Tauri's resource bundler flattens symlinks into duplicate
# REAL files, so without this what we sign and what Tauri copies are different
# bytes, and the copies arrive unsigned. Dereferencing here makes them identical.
cp -RL "$HERE/dist/arslan-server" "$TAURI/binaries/sidecar"

if [ -n "$(find "$TAURI/binaries/sidecar" -type l | head -1)" ]; then
  echo "ERROR: symlinks survived staging — Tauri would flatten them into unsigned copies" >&2
  exit 1
fi
# Any file under a *.framework/ path triggers codesign's bundle inference,
# which cannot validate a flattened layout. Our PyInstaller output has no
# framework today; this guard is what keeps a future dependency from silently
# introducing one (openworker took three Invalid notarization verdicts on
# exactly this before removing theirs).
if [ -n "$(find "$TAURI/binaries/sidecar" -type d -name '*.framework' | head -1)" ]; then
  echo "ERROR: a .framework appeared in the sidecar — it cannot pass notarization" >&2
  exit 1
fi
chmod +x "$TAURI/binaries/sidecar/arslan-server"

if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  step "    signing the sidecar's Mach-O files"
  # BEFORE tauri build: `tauri build` signs the .app, sealing resources into
  # that signature, but does NOT sign nested binaries inside resources.
  # Unsigned Mach-Os there fail notarization.
  #
  # Every Mach-O gets hardened runtime + a timestamp. Entitlements go ONLY on
  # the entrypoint: disable-library-validation is needed because the bundled
  # Python dylibs carry a different Team ID, and granting it more widely than
  # necessary weakens the app for no benefit.
  find "$TAURI/binaries/sidecar" -type f ! -name "arslan-server" \
    ! -name "*.py" ! -name "*.pyc" ! -name "*.txt" ! -name "*.json" \
    ! -name "*.html" ! -name "*.css" ! -name "*.js" \
    -print0 | while IFS= read -r -d '' f; do
    file -b "$f" | grep -q "Mach-O" || continue
    codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime "$f"
  done
  codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime \
    --entitlements "$TAURI/entitlements.plist" "$TAURI/binaries/sidecar/arslan-server"
fi

# --------------------------------------------------------------------------
step "[5/7] tauri build"
# --------------------------------------------------------------------------
# Updater artefacts (.app.tar.gz + minisign .sig) are produced only when the
# signing key is present. Keyless builds skip them so forks still work; a
# keyless RELEASE would strand every install without auto-update, hence the
# warning rather than silence.
UPDATER_OVERLAY=()
if [ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  UPDATER_OVERLAY=(--config '{"bundle":{"createUpdaterArtifacts":true}}')
else
  echo "    WARNING: no TAURI_SIGNING_PRIVATE_KEY — building WITHOUT auto-update artifacts (not releasable)."
fi
# ${arr[@]+…}: plain "${arr[@]}" on an EMPTY array is an unbound variable
# under `set -u` in macOS's stock bash 3.2.
( cd "$DESKTOP" && npx tauri build --bundles app ${UPDATER_OVERLAY[@]+"${UPDATER_OVERLAY[@]}"} )

BUNDLE="$TAURI/target/release/bundle"
APP_PATH="$BUNDLE/macos/$APP.app"
[ -d "$APP_PATH" ] || { echo "ERROR: tauri produced no $APP.app" >&2; exit 1; }

# The one assertion that cannot be checked earlier: what Tauri actually copied.
if [ -n "$(find "$APP_PATH" \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) | head -1)" ]; then
  echo "ERROR: a database file ended up inside $APP.app" >&2
  exit 1
fi

# --------------------------------------------------------------------------
step "[6/7] wrapping into a .dmg"
# --------------------------------------------------------------------------
# hdiutil rather than Tauri's own dmg bundler, which drives Finder over
# AppleScript and fails in a non-interactive session.
STAGING="$(mktemp -d)"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
DMG="$BUNDLE/dmg/${APP}_${VERSION}_${ARCH}.dmg"
mkdir -p "$(dirname "$DMG")"
rm -f "$DMG"
hdiutil create -volname "$APP" -srcfolder "$STAGING" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGING"

# --------------------------------------------------------------------------
step "[7/7] signing / notarizing the .dmg"
# --------------------------------------------------------------------------
if [ -z "${APPLE_SIGNING_IDENTITY:-}" ]; then
  echo "    (unsigned dev build — set APPLE_SIGNING_IDENTITY for a distributable DMG)"
elif [ "${ARSLAN_SKIP_NOTARIZE:-}" = "1" ]; then
  echo "    ARSLAN_SKIP_NOTARIZE=1 — signing the container, SKIPPING notarize/staple (do not distribute)"
  codesign --sign "$APPLE_SIGNING_IDENTITY" --timestamp "$DMG"
else
  codesign --sign "$APPLE_SIGNING_IDENTITY" --timestamp "$DMG"

  # CI hands the App Store Connect key over as APPLE_API_*; notarytool wants a
  # file path, so release.yml decodes APPLE_API_KEY_CONTENT and exports
  # APPLE_API_KEY_PATH.
  if [ -n "${APPLE_API_KEY_PATH:-}" ] && [ -n "${APPLE_API_KEY:-}" ] \
     && [ -n "${APPLE_API_ISSUER:-}" ]; then
    xcrun notarytool submit "$DMG" \
      --key "$APPLE_API_KEY_PATH" \
      --key-id "$APPLE_API_KEY" \
      --issuer "$APPLE_API_ISSUER" \
      --wait
    xcrun stapler staple "$DMG"
    # The same check Gatekeeper runs on a downloaded file. Fail the build
    # rather than ship a DMG that greets users with "Move to Trash" — a
    # notarization can be REJECTED and still leave a signed, stapled-looking
    # file behind.
    spctl -a -t open --context context:primary-signature "$DMG"
    echo "    Gatekeeper: accepted (notarized + stapled)"
  else
    echo "    WARNING: signed but NOT notarized — public downloads will see the" >&2
    echo "    'Move to Trash' dialog. Provide APPLE_API_KEY_PATH / APPLE_API_KEY /" >&2
    echo "    APPLE_API_ISSUER to notarize." >&2
  fi
fi

echo ""
echo "Done → $DMG"
