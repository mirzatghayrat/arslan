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
# (Re)create symlinks to the real source + installed deps + public assets.
link_stage() {
  ln -sfn "$WEB_DIR/src" "$STAGE/src"
  ln -sfn "$WEB_DIR/node_modules" "$STAGE/node_modules"
  ln -sfn "$WEB_DIR/public" "$STAGE/public"
}
# Verify each link RESOLVES to the current repo — not merely exists. The stage
# dir outlives the repo path ($TMPDIR persists across renames/moves), and a
# stale entry is worse than a missing one: `ln -sfn` onto a path that has
# become a REAL directory creates the new link INSIDE it, so $STAGE/src keeps
# serving old sources and vite builds a page with the right title and a white
# screen — this repo's move to Arslan/arslan produced exactly that. Resolution
# via `pwd -P` catches both the shadowed-directory case and a dangling link.
stage_ok() {
  for name in src node_modules public; do
    [ "$(cd "$STAGE/$name" 2>/dev/null && pwd -P)" =       "$(cd "$WEB_DIR/$name" && pwd -P)" ] || return 1
  done
}
link_stage
if ! stage_ok; then
  echo "clean-vite: stage at $STAGE is stale — rebuilding it from scratch" >&2
  rm -rf "$STAGE"
  mkdir -p "$STAGE"
  cp "$WEB_DIR/package.json" "$WEB_DIR/vite.config.ts" "$WEB_DIR/tsconfig.json" "$WEB_DIR/index.html" "$STAGE/"
  link_stage
  stage_ok || { echo "clean-vite: stage still broken after a rebuild — refusing to build from stale sources" >&2; exit 1; }
fi

cd "$STAGE"
npx vite "$@"

# For builds, copy the produced dist/ back into the repo (Docker/release expect web/dist).
if [ "${1:-}" = "build" ]; then
  rm -rf "$WEB_DIR/dist"
  cp -R "$STAGE/dist" "$WEB_DIR/dist"
fi
