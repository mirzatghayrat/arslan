#!/bin/bash
# Run a Python probe against this checkout's code with none of the user's real state in reach.
#
#   scripts/dev/probe.sh path/to/probe.py [args]      or      scripts/dev/probe.sh -c "python code"
#
# For review and debugging scripts that run product code outside pytest (incident 2026-10-24,
# docs/incidents/2026-10-24-dev-secret-read.md: a probe run with the real HOME and an explicit
# ARSLAN_SECRET_KEY made the secret bootstrap read ~/.arslan/secret_key to compare it). pytest's
# conftest already does all of this; this gives a plain script the same:
#   - HOME is a scratch folder, so ~/.arslan, ~/Arslan and the app's data folder are never resolved;
#   - ARSLAN_SECRET_KEY_FILE is set but empty: no secret file is ever stat'ed, read or written;
#   - ARSLAN_SECRET_KEY is a fake value, ARSLAN_DATA_DIR a scratch folder, the MCP supervisor off;
#   - every other ARSLAN_* variable from the calling shell is dropped.
# PROBE_SCRATCH picks the scratch folder (default: a fresh one under $TMPDIR); it may not be inside
# the real ~/.arslan. Use fake tokens and keys only.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
REAL_HOME=${HOME}
SCRATCH=${PROBE_SCRATCH:-$(mktemp -d "${TMPDIR:-/tmp}/arslan-probe.XXXXXX")}
case "$(cd "$(dirname "$SCRATCH")" 2>/dev/null && pwd)/$(basename "$SCRATCH")/" in
  "$REAL_HOME/.arslan/"*|"$REAL_HOME/") echo "probe.sh: the scratch folder may not be the real home or inside ~/.arslan" >&2; exit 2 ;;
esac
mkdir -p "$SCRATCH/home" "$SCRATCH/data"
for name in $(env | sed -n 's/^\(ARSLAN_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$name"; done
export HOME="$SCRATCH/home"
export ARSLAN_SECRET_KEY_FILE=""
export ARSLAN_SECRET_KEY="probe-fake-secret-not-a-real-key"
export ARSLAN_DATA_DIR="$SCRATCH/data"
export ARSLAN_MCP_SUPERVISOR=0
cd "$REPO"
exec "$REPO/.venv/bin/python" "$@"
