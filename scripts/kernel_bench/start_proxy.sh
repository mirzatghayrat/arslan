#!/bin/bash
# Start a metering proxy. Only this process ever holds the real key; caps are priced at peak rates.
#   start_proxy.sh              DeepSeek on :8900, key from ARSLAN_SPIKE_DEEPSEEK_KEY
#   start_proxy.sh anthropic    Claude models on :8901, key from ARSLAN_SPIKE_ANTHROPIC_KEY
# Both log to the same usage.jsonl; each has its own caps (BENCH_CAP_USD, BENCH_RUN_CAP_USD).
set -euo pipefail
ROOT=${BENCH_ROOT:-/tmp/arslan-kernel-bench}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$ROOT"
if [ "${1:-deepseek}" = "anthropic" ]; then
  KEYVAR=ARSLAN_SPIKE_ANTHROPIC_KEY PORT=8901 UPSTREAM=https://api.anthropic.com CAP=${BENCH_CAP_USD:-10} RUN_CAP=${BENCH_RUN_CAP_USD:-1}
else
  KEYVAR=ARSLAN_SPIKE_DEEPSEEK_KEY PORT=8900 UPSTREAM=https://api.deepseek.com CAP=${BENCH_CAP_USD:-5} RUN_CAP=${BENCH_RUN_CAP_USD:-0.45}
fi
# An interactive zsh may print things first (Terminal's "Restored session: …" line, a profile's own
# echo); 2026-10-11 that line became part of the key and every request failed with an illegal header.
# So the key is marked, only the marked line is taken, and a key with whitespace in it is refused.
KEY=$(KEYVAR="$KEYVAR" zsh -i -c 'printf "\n__ARSLAN_KEY__%s\n" "${(P)KEYVAR}"' 2>/dev/null </dev/null \
  | sed -n 's/^__ARSLAN_KEY__//p' | tail -n 1)
[ -n "$KEY" ] || { echo "$KEYVAR is not set"; exit 1; }
case "$KEY" in
  *[[:space:]]*) echo "$KEYVAR has spaces or line breaks in it; fix it in your shell profile"; exit 1 ;;
esac
cd "$REPO"
exec env BENCH_REAL_KEY="$KEY" BENCH_UPSTREAM="$UPSTREAM" BENCH_CAP_USD="$CAP" BENCH_RUN_CAP_USD="$RUN_CAP" \
  BENCH_LOG="$ROOT/usage.jsonl" .venv/bin/uvicorn scripts.kernel_bench.meter:app --host 127.0.0.1 --port "$PORT" --log-level warning
