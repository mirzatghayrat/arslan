#!/bin/bash
# Start the Arslan test instance for L3: this checkout's code (Hands P2), a throwaway HOME and data dir
# under $L3_ROOT, the development Arslan Hands, the model only through the metering proxy.
#   start_instance.sh [name] [port]
# Not inside sandbox-exec: Hands drives the user's real apps by design (L3 plan), and its own
# folder is found from the account database, not HOME. Test content only: ~/Documents/Arslan L3 and
# the Notes folder "Arslan L3" (scripts/hands_l3/tasks.py).
set -euo pipefail
NAME=${1:-l3}; PORT=${2:-8764}
ROOT=${L3_ROOT:-/tmp/arslan-hands-l3}
HANDS_APP=${ARSLAN_HANDS_APP:-$HOME/Applications/Arslan Hands Dev/Arslan Hands DEV.app}
[ -f "$HANDS_APP/Contents/Info.plist" ] || { echo "no Arslan Hands at $HANDS_APP"; exit 1; }
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$ROOT/home/$NAME" "$ROOT/data/$NAME" "$ROOT/tmp"
cd "$REPO"
exec env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin HOME="$ROOT/home/$NAME" TMPDIR="$ROOT/tmp" \
  ARSLAN_DATA_DIR="$ROOT/data/$NAME" ARSLAN_SECRET_KEY=l3-only-not-a-real-secret ARSLAN_API_TOKEN= \
  ARSLAN_HANDS_APP="$HANDS_APP" \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port "$PORT"
