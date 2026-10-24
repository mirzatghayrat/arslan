#!/bin/bash
# Run a Python probe against this checkout's code with none of the user's real state handed to it.
#
#   scripts/dev/probe.sh path/to/probe.py [args]      or      scripts/dev/probe.sh -c "python code"
#
# For review and debugging scripts that run product code outside pytest (incident 2026-10-24,
# docs/incidents/2026-10-24-dev-secret-read.md: a probe run with the real HOME and an explicit
# ARSLAN_SECRET_KEY made the secret bootstrap read ~/.arslan/secret_key to compare it). pytest's
# conftest pins the same things for the suite; this gives a plain script:
#   - an empty environment (env -i) plus PATH, TMPDIR, LANG, TERM, USER and LOGNAME: no token, key,
#     ARSLAN_* or PYTHON* variable of the calling shell reaches it;
#   - HOME is a scratch folder, so ~/.arslan, ~/Arslan and the app's data folder are never resolved;
#   - ARSLAN_SECRET_KEY_FILE is set but empty: no secret file is ever stat'ed, read or written;
#   - ARSLAN_SECRET_KEY is a fake value, ARSLAN_DATA_DIR a scratch folder, the MCP supervisor off;
#   - PYTHONPATH is this checkout, so a probe script anywhere can import server.
# PROBE_SCRATCH picks the scratch folder (default: a fresh one under $TMPDIR). It is resolved
# physically (links, "..", missing folders, a trailing slash) before anything is created, and may
# not be the real home or inside the real ~/.arslan, in any letter case. Use fake tokens and keys.
# NOT covered: what the probe itself reads by an absolute path or starts. A clean start, not a sandbox.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)
PY="$REPO/.venv/bin/python"
canon() { "$PY" -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
fold() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
REAL_HOME=$(canon "$HOME")
SECRET_DIR=$(canon "$REAL_HOME/.arslan")
SCRATCH=$(canon "${PROBE_SCRATCH:-$(mktemp -d "${TMPDIR:-/tmp}/arslan-probe.XXXXXX")}")
case "$(fold "$SCRATCH")/" in
  "$(fold "$REAL_HOME")/"|"$(fold "$REAL_HOME/.arslan")/"*|"$(fold "$SECRET_DIR")/"*)
    echo "probe.sh: the scratch folder ($SCRATCH) may not be the real home or inside ~/.arslan" >&2; exit 2 ;;
esac
mkdir -p "$SCRATCH/home" "$SCRATCH/data"
cd "$REPO"
exec env -i PATH="${PATH:-/usr/bin:/bin}" TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-en_US.UTF-8}" \
  TERM="${TERM:-dumb}" USER="${USER:-}" LOGNAME="${LOGNAME:-}" \
  HOME="$SCRATCH/home" PYTHONPATH="$REPO" \
  ARSLAN_SECRET_KEY_FILE="" ARSLAN_SECRET_KEY="probe-fake-secret-not-a-real-key" \
  ARSLAN_DATA_DIR="$SCRATCH/data" ARSLAN_MCP_SUPERVISOR=0 \
  "$PY" "$@"
