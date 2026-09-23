# Branded drag-to-install disk image

The installer uses English copy for Arslan's international audience. The app
and Applications shortcut remain real Finder items; the arrow and instructions
are background artwork, not interactive controls.

`background.svg` is the editable source. On macOS, run
`node scripts/build_dmg_background.mjs` to export committed 1x and 2x PNGs.
The release runner uses those assets directly, avoiding font/rendering drift.

The build-only, macOS-only `dmgbuild` dependency writes Finder metadata without
AppleScript or a logged-in desktop. `build_dmg.sh` creates the branded image and
runs `verify_dmg_layout.py` before the existing signing and notarization stages.
The verifier mounts read-only, checks the actual app, Applications target,
window bounds, item positions and both Retina background frames, then detaches.

Manual acceptance: open the DMG in Finder and check the 720×440 content area,
legible English instruction, both native icons and the connecting arrow.
The OS owns the title bar and may localize its native Applications label.
