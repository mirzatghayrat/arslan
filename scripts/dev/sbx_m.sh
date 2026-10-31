#!/bin/bash
# SBX-M in one sitting (docs/plans/0164/SBX-M-runbook.md): the SBX-2 corpus on this Mac, then the
# listener-refusal repeat loop, then a summary of ids, outcomes, versions and hashes.
#
#   scripts/dev/sbx_m.sh                       # from the repository root, in Terminal
#   SBX_M_LOOPS=50 scripts/dev/sbx_m.sh        # more loop runs (default 30)
#   SBX_M_LOOPS=0 scripts/dev/sbx_m.sh         # the corpus only
#   SBX_M_CORPUS=0 scripts/dev/sbx_m.sh        # the loop only
#
# It runs no probe of its own. Every probe is a test in tests/server/sbx (Codex's, reviewed by Astra),
# run the way tests/server/sbx/corpus/README.md says, with CI's strict xfails. pytest's conftest gives
# every child a scratch HOME, a private TMPDIR, a fake secret and no credential variables.
# Results stay on this Mac, outside the repository (SBX_M_OUT, default ~/Library/Logs/arslan-sbx-m/<UTC
# time>): the exact profile texts, the JUnit files and the terminal output hold local paths, so they are
# never committed. summary.md holds only what the report may quote.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)
PY="$REPO/.venv/bin/python"
LOOPS="${SBX_M_LOOPS:-30}"
CORPUS="${SBX_M_CORPUS:-1}"

[[ "$(uname -s)" == Darwin ]] || { echo "sbx_m.sh: SBX-M runs on macOS only" >&2; exit 2; }
[[ -x "$PY" ]] || { echo "sbx_m.sh: no .venv here; run: uv sync --frozen --extra dev --extra server --extra ocr" >&2; exit 2; }
[[ "$LOOPS" =~ ^[0-9]+$ ]] || { echo "sbx_m.sh: SBX_M_LOOPS must be a whole number" >&2; exit 2; }
[[ "$CORPUS" == 0 || "$CORPUS" == 1 ]] || { echo "sbx_m.sh: SBX_M_CORPUS is 0 or 1" >&2; exit 2; }
# The corpus calls git and swift. Without developer tools, /usr/bin/git opens macOS's install dialog.
/usr/bin/xcode-select -p >/dev/null 2>&1 || {
  echo "sbx_m.sh: no developer tools; install them first (xcode-select --install), then run this again" >&2; exit 2; }
# Keep the Mac awake for the whole run; the user may walk away.
[[ -n "${SBX_M_AWAKE:-}" ]] || exec /usr/bin/caffeinate -i /usr/bin/env SBX_M_AWAKE=1 "$0" "$@"

canon() { "$PY" -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
fold() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
OUT=$(canon "${SBX_M_OUT:-$HOME/Library/Logs/arslan-sbx-m/$(date -u +%Y%m%dT%H%M%SZ)}")
case "$(fold "$OUT")/" in       # resolved and case-folded before anything is created, as in probe.sh
  "$(fold "$REPO")/"*) echo "sbx_m.sh: results hold local paths; keep SBX_M_OUT outside the repository" >&2; exit 2 ;;
esac
mkdir -p "$OUT/loop" || exit 2
cd "$REPO"

version() { command -v "$1" >/dev/null 2>&1 && { "$@" 2>/dev/null | head -1; } || echo missing; }
{
  echo "commit: $(git rev-parse HEAD)"
  echo "changed files in the checkout: $(git status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
  echo "macos: $(sw_vers -productVersion) ($(sw_vers -buildVersion))"
  echo "hardware: $(uname -m), $(sysctl -n hw.model)"
  echo "python: $("$PY" --version 2>&1)"
  echo "git: $(version git --version)"
  echo "node: $(version node --version)"
  echo "npm: $(version npm --version)"
  echo "swift: $(version swift --version)"
  echo "brew: $(version brew --version)"
  echo "uv: $(version uv --version)"
  echo "firewall: $(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | head -1)"
  # Another suite on this Mac slows the corpus down, and a slow row can end as `timeout`.
  echo "other pytest processes at the start: $(pgrep -f pytest | wc -l | tr -d ' ')"
  echo "corpus: $([[ "$CORPUS" == 1 ]] && echo run || echo skipped), loops: $LOOPS"
} > "$OUT/preflight.txt"
cat "$OUT/preflight.txt"

if [[ "$CORPUS" == 1 ]]; then
  echo "== 1/2 the corpus (tests/server/sbx -m sbx_mac)"
  SECONDS=0
  "$PY" -m pytest tests/server/sbx -m sbx_mac -q -rfEs -o xfail_strict=true -p no:cacheprovider \
    --junitxml="$OUT/results.xml" --sbx-artifacts="$OUT/profiles" 2>&1 | tee "$OUT/pytest-corpus.txt"
  echo "corpus exit: ${PIPESTATUS[0]}, seconds: $SECONDS" >> "$OUT/preflight.txt"
fi

echo "== 2/2 the listener-refusal loop ($LOOPS runs)"
SECONDS=0
for ((i = 1; i <= LOOPS; i++)); do
  run=$(printf '%03d' "$i")
  if "$PY" -m pytest tests/server/sbx/test_sbx2_kernel.py -m sbx_mac -k listener_refusal -q -o xfail_strict=true \
      -p no:cacheprovider --junitxml="$OUT/loop/$run.xml" > "$OUT/loop/$run.txt" 2>&1; then
    printf '.'
  else
    printf 'F'
  fi
done
echo
echo "loop seconds: $SECONDS" >> "$OUT/preflight.txt"

"$PY" -I "$REPO/scripts/dev/sbx_m_summary.py" "$OUT"
