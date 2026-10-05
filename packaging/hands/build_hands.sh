#!/usr/bin/env bash
# Build "Arslan Hands.app" and, NEXT TO it, agent-desktop into OUT_DIR
# (0.1.53; spec §1–2):  OUT_DIR/Arslan Hands.app  +  OUT_DIR/agent-desktop
#
#   packaging/hands/build_hands.sh OUT_DIR
#
# 1. agent-desktop from OUR FORK at the pinned commit (agent-desktop.pin), with
#    its vendored dependencies: `cargo build --release --locked --offline`, so no
#    crate is downloaded and the lockfile cannot drift. A checkout whose HEAD is
#    not the pin is refused. HANDS_AGENT_DESKTOP_SRC=<checkout> reuses a local
#    clone (same check).
# 2. Our helper, desktop/hands (`--locked`).
# 3. The bundle: Contents/MacOS/arslan-hands, Info.plist with its own bundle
#    id (com.arslan.desktop.hands — macOS lists and grants Accessibility to THIS
#    app, never to Arslan.app), the icon, the Apache-2.0 notice, and
#    agent-desktop's sha256. agent-desktop itself is NOT inside the bundle:
#    measured on a real Mac, a binary in Contents/MacOS run on its own (its
#    responsibility disclaimed) got the bundle's Accessibility grant — anything
#    could have used it. Beside the bundle it gets the grant only as Hands'
#    child, and Hands checks its sha256 (recorded inside the sealed bundle)
#    before every run.
# 4. Signing, inside out: agent-desktop with its own identifier (so macOS never
#    takes it for the app), then the bundle; hardened runtime, timestamp, no
#    entitlements. APPLE_SIGNING_IDENTITY unset → ad-hoc (development only: the
#    helper then has no Team ID and skips its peer check, and says so).
#
# Notarization is the DMG's (build_dmg.sh): nested code is checked with it.
set -euo pipefail

OUT="${1:?usage: build_hands.sh OUT_DIR}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CARGO="${CARGO_HOME:-$HOME/.cargo}/bin/cargo"
command -v "$CARGO" >/dev/null 2>&1 || CARGO=cargo

# KEY=value lines only; read, never sourced (macOS's bash 3.2 cannot source <(…)).
while IFS='=' read -r key value; do
  case "$key" in
    REPOSITORY|BRANCH|COMMIT|UPSTREAM|UPSTREAM_TAG|UPSTREAM_COMMIT) printf -v "$key" '%s' "$value" ;;
  esac
done < "$HERE/agent-desktop.pin"
: "${REPOSITORY:?}" "${COMMIT:?}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/arslan-hands.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# ── 1. agent-desktop, pinned, vendored, offline ─────────────────────────────
if [ -n "${HANDS_AGENT_DESKTOP_SRC:-}" ]; then
  SRC="$HANDS_AGENT_DESKTOP_SRC"
else
  SRC="$WORK/agent-desktop"
  git init -q "$SRC"
  git -C "$SRC" fetch -q --depth 1 "$REPOSITORY" "$COMMIT"
  git -C "$SRC" checkout -q FETCH_HEAD
fi
HEAD="$(git -C "$SRC" rev-parse HEAD)"
if [ "$HEAD" != "$COMMIT" ]; then
  echo "ERROR: agent-desktop checkout is at $HEAD, the pin says $COMMIT" >&2
  exit 1
fi
if [ -n "$(git -C "$SRC" status --porcelain --untracked-files=no)" ]; then
  echo "ERROR: agent-desktop checkout has local changes" >&2
  exit 1
fi
# A vendored file that git ignores is on THIS disk but not in a clean fetch, so a
# local build passes where the release build fails (measured: the fork's `.vim/`
# rule dropped two files cargo checksums; only a clean fetch showed it).
if [ -n "$(git -C "$SRC" status --porcelain --ignored -- vendor | grep '^!!' || true)" ]; then
  echo "ERROR: agent-desktop's vendor/ holds files git ignores; a clean fetch would not have them" >&2
  exit 1
fi
[ -d "$SRC/vendor" ] && grep -q 'replace-with = "vendored-sources"' "$SRC/.cargo/config.toml" \
  || { echo "ERROR: the pinned agent-desktop has no vendored sources" >&2; exit 1; }

( cd "$SRC" && CARGO_NET_OFFLINE=true CARGO_TARGET_DIR="$WORK/ad-target" \
    "$CARGO" build --release --locked --offline -p agent-desktop )
AD_BIN="$WORK/ad-target/release/agent-desktop"
AD_SHA="$(shasum -a 256 "$AD_BIN" | cut -d' ' -f1)"
echo "    agent-desktop $COMMIT sha256 $AD_SHA"

# ── 2. the helper ───────────────────────────────────────────────────────────
# HANDS_DEV_UNVERIFIED_PEER=1: development only (see desktop/hands/Cargo.toml).
FEATURES=()
if [ "${HANDS_DEV_UNVERIFIED_PEER:-}" = "1" ]; then
  echo "    DEVELOPMENT BUILD: peer check off — never ship this" >&2
  FEATURES=(--features dev-unverified-peer)
fi
"$CARGO" build --release --locked --manifest-path "$ROOT/desktop/hands/Cargo.toml" \
  --target-dir "$WORK/hands-target" ${FEATURES[@]+"${FEATURES[@]}"}
# A development build (dev peer check, or not signed with an identity) gets its own bundle id and
# name. macOS keys the Accessibility grant by bundle id and keeps the code requirement of the build
# that asked, so a development build and the signed release sharing com.arslan.desktop.hands leave
# the other one refused while its switch shows on (measured on the user's Mac, 2026-10-05: tccd
# "Failed to match existing code requirement for subject com.arslan.desktop.hands"). Both ids fall
# under the never-list's com.arslan.desktop.* entry.
BUNDLE_ID=com.arslan.desktop.hands
BUNDLE_NAME="Arslan Hands"
if [ "${HANDS_DEV_UNVERIFIED_PEER:-}" = "1" ] || [ -z "${APPLE_SIGNING_IDENTITY:-}" ]; then
  BUNDLE_ID=com.arslan.desktop.hands.dev
  BUNDLE_NAME="Arslan Hands (dev)"
  echo "    development bundle id $BUNDLE_ID (its own Accessibility entry)" >&2
fi
HANDS_BIN="$WORK/hands-target/release/arslan-hands"

# ── 3. the bundle ───────────────────────────────────────────────────────────
VERSION="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" \
  "$ROOT/desktop/src-tauri/tauri.conf.json")"
APP="$OUT/Arslan Hands.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HANDS_BIN" "$APP/Contents/MacOS/arslan-hands"
rm -f "$OUT/agent-desktop"
cp "$AD_BIN" "$OUT/agent-desktop"
cp "$ROOT/desktop/src-tauri/icons/icon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$SRC/LICENSE" "$APP/Contents/Resources/LICENSE-agent-desktop"
cat > "$APP/Contents/Resources/NOTICE" <<NOTICE
Arslan Hands includes agent-desktop (https://github.com/lahfir/agent-desktop),
Copyright its authors, licensed under the Apache License, Version 2.0 (see
LICENSE-agent-desktop). Built unmodified from $REPOSITORY at $COMMIT
(upstream ${UPSTREAM_TAG:-} ${UPSTREAM_COMMIT:-}) with its dependencies vendored.
NOTICE
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$BUNDLE_NAME</string>
  <key>CFBundleDisplayName</key><string>$BUNDLE_NAME</string>
  <key>CFBundleExecutable</key><string>arslan-hands</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHumanReadableCopyright</key><string>Arslan. Includes agent-desktop (Apache-2.0).</string>
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null

# ── 4. signing, inside out ──────────────────────────────────────────────────
# agent-desktop first; its signed sha256 is recorded in Resources BEFORE the
# bundle is signed, so the bundle's seal covers the record.
if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  # HANDS_SIGN_TIMESTAMP=none: local development builds only (no notarization).
  SIGN=(--sign "$APPLE_SIGNING_IDENTITY" "--timestamp${HANDS_SIGN_TIMESTAMP:+=$HANDS_SIGN_TIMESTAMP}" --options runtime)
else
  echo "    (no APPLE_SIGNING_IDENTITY: ad-hoc signing, development only — no peer check)"
  SIGN=(--sign -)
fi
# Apple's timestamp server occasionally does not answer ("A timestamp was
# expected but was not found", seen locally): try a signature three times.
sign() {
  local attempt
  for attempt in 1 2 3; do
    codesign --force "${SIGN[@]}" "$@" && return 0
    echo "    codesign failed (attempt $attempt), retrying" >&2
    sleep 5
  done
  return 1
}
sign --identifier "$BUNDLE_ID.agent-desktop" "$OUT/agent-desktop"
SIGNED_SHA="$(shasum -a 256 "$OUT/agent-desktop" | cut -d' ' -f1)"
echo "$SIGNED_SHA  agent-desktop, signed (built $AD_SHA from $REPOSITORY @ $COMMIT)" \
  > "$APP/Contents/Resources/agent-desktop.sha256"
sign "$APP"
codesign --verify --strict --deep "$APP"
codesign --verify --strict "$OUT/agent-desktop"
echo "    built $APP and $OUT/agent-desktop"
