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
# A framework-build interpreter poisons the bundle at the source: PyInstaller
# copies its Python.framework into _internal/, and any file under a
# *.framework/ path can never pass notarization in the flattened sidecar
# layout. The staging guard at [4/7] catches the RESULT after minutes of
# building; this names the CAUSE in seconds. uv's managed CPython (see
# .python-version) is a standalone build and passes.
"$ROOT/.venv/bin/python" - <<'PYCHECK' || exit 1
import sys
if "Python.framework" in sys.base_prefix:
    sys.exit(
        "ERROR: the venv interpreter is a framework build "
        f"({sys.base_prefix}) — PyInstaller would bundle Python.framework, "
        "which cannot be notarized. Recreate the venv with uv's managed "
        "Python: uv sync --frozen ... (honours .python-version)."
    )
PYCHECK

# The updater public key must be present, or installed copies silently never
# update: Tauri accepts an absent pubkey and just produces no updater
# artefacts, which looks like a successful build.
# Decoded the way Tauri itself decodes it, not length-checked: the pubkey is
# the base64 CONTENT OF THE .pub FILE (comment line + key line), and the raw
# inner minisign key passes any length check while failing Tauri's decode with
# "invalid utf-8" — after the build, the signing, and an ACCEPTED
# notarization (run 30206539950 died exactly there).
node -e '
  const c = require("'"$TAURI"'/tauri.conf.json");
  const k = c.plugins?.updater?.pubkey || "";
  let d = "";
  try { d = Buffer.from(k, "base64").toString("utf8") } catch {}
  if (!d.includes("minisign public key")) {
    console.error("ERROR: updater pubkey is not the base64 content of the .pub file (must decode to the untrusted-comment + key lines)");
    process.exit(1);
  }
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
# The dereference and the two guards live in their own script so they can be
# tested without a five-minute build in front of them.
"$HERE/stage_sidecar.sh" "$HERE/dist/arslan-server" "$TAURI/binaries/sidecar"

step "[4b/7] building the push-to-talk listener"
# --------------------------------------------------------------------------
# A tiny Swift binary, not code in the Rust shell: Speech and AVAudioEngine are
# Swift APIs on a real-time audio thread. It ships INSIDE the bundle, which is
# what makes it legal — TCC reads the usage strings from the app's Info.plist
# and a child living there inherits them. Measured: the same binary outside a
# bundle carrying those keys is killed outright by TCC, not denied.
mkdir -p "$TAURI/binaries/listen"
swiftc -O -o "$TAURI/binaries/listen/arslan-listen" "$HERE/listen/arslan-listen.swift"
# A listener that failed to build must not produce a quietly voiceless app.
test -x "$TAURI/binaries/listen/arslan-listen" \
  || { echo "ERROR: the listener did not build" >&2; exit 1; }

swiftc -O -o "$TAURI/binaries/listen/arslan-voice" "$HERE/listen/arslan-voice.swift"
test -x "$TAURI/binaries/listen/arslan-voice" \
  || { echo "ERROR: the conversation helper did not build" >&2; exit 1; }

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

  step "    signing the listener"
  # No entitlements: a non-sandboxed Developer ID app was MEASURED recording
  # with none, and audio-input cannot be embedded by plain Developer ID signing
  # anyway. Hardened runtime and a timestamp are what notarization wants.
  codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime \
    "$TAURI/binaries/listen/arslan-listen"

  codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime \
    "$TAURI/binaries/listen/arslan-voice"
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

# The launch clip, for the same reason and in the opposite direction: it must
# be PRESENT. A missing clip is the one defect in this feature that produces no
# symptom — the launch screen catches the load failure and degrades to its
# pulsing dot, so the app starts normally, looks deliberate, and nobody reports
# anything.
#
# 🔴 The first version of this check looked for the file inside Arslan.app and
# failed the v0.1.19 build. It was the CHECK that was wrong: Tauri embeds
# everything under frontendDist into the executable rather than copying it into
# Resources (measured against the shipped v0.1.18 — its .app contains no loose
# splash files, and its binary carries the frontendDist path). Probing for a
# file while the consumer reads an embedded blob is a false negative, and a
# false negative here blocks a release that was fine.
#
# So this asserts what can actually be asserted at each layer:
#   HARD  — the clip is on disk where tauri build will pick it up. This is the
#           real regression risk (renamed, deleted, or never committed).
#   SOFT  — the asset key survives into the binary. Reported, not enforced,
#           because Tauri may compress the embedded key table; a check whose
#           failure mode is unknown must not be allowed to fail a release.
SPLASH_HTML="$DESKTOP/splash/index.html"
CLIP_NAME="$(sed -n 's/.*<video[^>]*data-clip="\([^"]*\)".*/\1/p' "$SPLASH_HTML" | head -1)"
if [ -z "$CLIP_NAME" ]; then
  echo "ERROR: $SPLASH_HTML no longer references a launch clip" >&2
  exit 1
fi
if [ ! -s "$DESKTOP/splash/$CLIP_NAME" ]; then
  echo "ERROR: the launch clip '$CLIP_NAME' is missing or empty at $DESKTOP/splash/." >&2
  echo "       tauri build embeds frontendDist, so it would ship without one and" >&2
  echo "       the launch screen would silently fall back to a loading dot." >&2
  exit 1
fi
APP_BIN="$APP_PATH/Contents/MacOS/arslan-desktop"
if [ -f "$APP_BIN" ] && LC_ALL=C grep -qa "$CLIP_NAME" "$APP_BIN"; then
  echo "     launch clip embedded: $CLIP_NAME ($(du -h "$DESKTOP/splash/$CLIP_NAME" | cut -f1))"
else
  echo "     NOTE: '$CLIP_NAME' is on disk but its key was not found in the binary." >&2
  echo "           Expected if Tauri compresses the embedded asset table; if the" >&2
  echo "           animation is also missing at runtime, start here." >&2
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
