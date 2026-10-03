#!/bin/bash
# Build Arslan Bridge (desktop/bridge) into a signed helper app bundle.
#   build_bridge.sh <out_dir> <version>
# Produces <out_dir>/ArslanBridge.app. With APPLE_SIGNING_IDENTITY set, signs it with
# hardened runtime and a timestamp (notarization wants both) under its own identifier.
# Step 2 ships no entitlements; iCloud/Push come with the provisioning profile (step 3).
set -euo pipefail
OUT=$1; VERSION=$2
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/../desktop/bridge"
APP="$OUT/ArslanBridge.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
sed "s/__VERSION__/$VERSION/g" "$SRC/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
swift build -c release --package-path "$SRC" --product ArslanBridge
cp "$(swift build -c release --package-path "$SRC" --show-bin-path)/ArslanBridge" "$APP/Contents/MacOS/ArslanBridge"
test -x "$APP/Contents/MacOS/ArslanBridge" || { echo "ERROR: the Bridge did not build" >&2; exit 1; }
# Step 3: with a Developer ID provisioning profile for com.arslan.desktop.bridge (iCloud +
# Push) in desktop/bridge, embed it and sign with the matching entitlements. Restricted
# entitlements without the profile would make macOS refuse to launch the app, so neither
# goes in without the other.
PROFILE="$SRC/ArslanBridge.provisionprofile"
ENTITLEMENTS=()
if [ -f "$PROFILE" ]; then
  TEAM=$(security cms -D -i "$PROFILE" | plutil -extract TeamIdentifier.0 raw -o - -)
  cp "$PROFILE" "$APP/Contents/embedded.provisionprofile"
  sed "s/__TEAM__/$TEAM/g" "$SRC/ArslanBridge.entitlements.template" > "$OUT/ArslanBridge.entitlements"
  plutil -lint "$OUT/ArslanBridge.entitlements" >/dev/null
  ENTITLEMENTS=(--entitlements "$OUT/ArslanBridge.entitlements")
fi
if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime \
    --identifier com.arslan.desktop.bridge ${ENTITLEMENTS[@]+"${ENTITLEMENTS[@]}"} "$APP"
  codesign --verify --strict "$APP"
fi
"$APP/Contents/MacOS/ArslanBridge" --selftest
