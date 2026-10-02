#!/bin/bash
# Start an Arslan test instance for the bench: throwaway HOME and data under
# $BENCH_ROOT, inside the bench sandbox, model only via the metering proxy.
#   start_arslan.sh <name> <port> [native|legacy]
# BENCH_SANDBOX overrides the profile (e.g. one that also allows Arslan's
# browser its short socket dirs under /private/tmp/arslan-ab-*).
set -euo pipefail
NAME=$1; PORT=$2; PROTOCOL=${3:-native}
ROOT=${BENCH_ROOT:-/tmp/arslan-kernel-bench}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$ROOT/home/$NAME" "$ROOT/data/$NAME" "$ROOT/tmp"
cd "$REPO"
exec env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin HOME="$ROOT/home/$NAME" TMPDIR="$ROOT/tmp" \
  ARSLAN_DATA_DIR="$ROOT/data/$NAME" ARSLAN_SECRET_KEY=bench-only-not-a-real-secret ARSLAN_API_TOKEN= \
  ARSLAN_TOOL_PROTOCOL="$PROTOCOL" \
  sandbox-exec -f "${BENCH_SANDBOX:-$ROOT/sandbox.sb}" .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port "$PORT"
