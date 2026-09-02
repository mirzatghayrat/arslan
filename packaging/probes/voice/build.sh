#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/VoiceProbe.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.arslantest.voiceprobe</string>
  <key>CFBundleName</key><string>VoiceProbe</string>
  <key>CFBundleExecutable</key><string>voiceprobe</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>VoiceProbe measures echo cancellation for Arslan's voice mode.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>VoiceProbe measures speech recognition under echo cancellation.</string>
</dict></plist>
PLIST
swiftc -O -o "$APP/Contents/MacOS/voiceprobe" "$HERE/voiceprobe.swift"
codesign --force --sign - "$APP"
echo "built $APP"
