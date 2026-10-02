#!/bin/bash
# Start the metering proxy. The key comes from ARSLAN_SPIKE_DEEPSEEK_KEY in your shell profile;
# only this process ever holds it. Caps are priced at DeepSeek PEAK rates (off-peak is half).
set -euo pipefail
ROOT=${BENCH_ROOT:-/tmp/arslan-kernel-bench}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$ROOT"
KEY=$(zsh -i -c 'printf %s "$ARSLAN_SPIKE_DEEPSEEK_KEY"' 2>/dev/null)
[ -n "$KEY" ] || { echo "ARSLAN_SPIKE_DEEPSEEK_KEY is not set"; exit 1; }
cd "$REPO"
exec env BENCH_REAL_KEY="$KEY" BENCH_CAP_USD="${BENCH_CAP_USD:-5}" BENCH_RUN_CAP_USD="${BENCH_RUN_CAP_USD:-0.45}" \
  BENCH_LOG="$ROOT/usage.jsonl" .venv/bin/uvicorn scripts.kernel_bench.meter:app --host 127.0.0.1 --port 8900 --log-level warning
