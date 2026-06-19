#!/usr/bin/env bash
#
# Run Vite (dev/build/preview) for arslan/web from a clean staging directory
# OUTSIDE the repo tree, with src + node_modules SYMLINKED back here.
#
# Why: Tailwind v4's oxide content-scanner generates ZERO utility classes when
# the project is built inside this big nested git tree (aralem_dev → arslan,
# with .venv/, data/, and .claude/worktrees/...). See tailwindcss#18957 / #15452.
# The exact same files build fully (87 KB, all utilities) in a clean directory.
# oxide does not follow the symlinks back into the git tree, so it scans the
# staging dir cleanly. Source of record stays in arslan/web; edits hot-reload
# through the src symlink. In a clean context (Docker/CI) plain `vite` also works,
# and this script is still harmless there.
#
# Usage: scripts/clean-vite.sh [dev|build|preview] [extra vite args...]
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${TMPDIR:-/tmp}/arslan-web-stage"

mkdir -p "$STAGE"
# Refresh config files (cheap; keeps staging in sync with the repo).
cp "$WEB_DIR/package.json" "$WEB_DIR/vite.config.ts" "$WEB_DIR/tsconfig.json" "$WEB_DIR/index.html" "$STAGE/"
# (Re)create symlinks to the real source + installed deps.
ln -sfn "$WEB_DIR/src" "$STAGE/src"
ln -sfn "$WEB_DIR/node_modules" "$STAGE/node_modules"

cd "$STAGE"
npx vite "$@"

# For builds, copy the produced dist/ back into the repo (Docker/release expect web/dist).
if [ "${1:-}" = "build" ]; then
  rm -rf "$WEB_DIR/dist"
  cp -R "$STAGE/dist" "$WEB_DIR/dist"
fi
