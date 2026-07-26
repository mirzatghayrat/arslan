#!/usr/bin/env bash
# Stage the frozen sidecar into Tauri's resources slot, and refuse to proceed
# if the result cannot be signed correctly.
#
#   packaging/stage_sidecar.sh <dist/arslan-server> <src-tauri/binaries/sidecar>
#
# Split out of build_dmg.sh so these two guards can be exercised on their own.
# Buried mid-script they were only reachable after a five-minute web build and
# PyInstaller run, which is long enough that "I'll verify the guard later"
# becomes "the guard is untested".
set -euo pipefail

SRC="${1:?usage: stage_sidecar.sh <src> <dest>}"
DEST="${2:?usage: stage_sidecar.sh <src> <dest>}"

[ -d "$SRC" ] || { echo "ERROR: no sidecar at $SRC" >&2; exit 1; }

mkdir -p "$(dirname "$DEST")"
# rm -rf FIRST: cp writes THROUGH a symlink at the destination, so a leftover
# link here could clobber whatever it points at.
rm -rf "$DEST"

# -L dereferences. Tauri's resource bundler flattens symlinks into duplicate
# REAL files, so without this what we sign and what Tauri copies are different
# bytes — and the copies arrive unsigned.
cp -RL "$SRC" "$DEST"

if [ -n "$(find "$DEST" -type l | head -1)" ]; then
  echo "ERROR: symlinks survived staging — Tauri would flatten them into unsigned copies:" >&2
  find "$DEST" -type l | head -5 >&2
  exit 1
fi

# Any file under a *.framework/ path triggers codesign's bundle inference,
# which can never validate a flattened layout. Our PyInstaller output has no
# framework today; this guard is what stops a future dependency introducing
# one silently (openworker took three Invalid notarization verdicts on exactly
# this before removing theirs).
if [ -n "$(find "$DEST" -type d -name '*.framework' | head -1)" ]; then
  echo "ERROR: a .framework appeared in the sidecar — it cannot pass notarization:" >&2
  find "$DEST" -type d -name '*.framework' | head -5 >&2
  exit 1
fi

chmod +x "$DEST/arslan-server"
echo "staged $(find "$DEST" -type f | wc -l | tr -d ' ') files into $DEST"
