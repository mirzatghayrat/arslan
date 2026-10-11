#!/bin/bash
# Start the metering proxy. The key comes from ARSLAN_SPIKE_DEEPSEEK_KEY in your shell profile;
# only this process ever holds it. Caps are priced at DeepSeek PEAK rates (off-peak is half).
set -euo pipefail
ROOT=${BENCH_ROOT:-/tmp/arslan-kernel-bench}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$ROOT"
# An interactive zsh may print things first (Terminal's "Restored session: …" line, a profile's own
# echo); 2026-10-11 that line became part of the key and every request failed with an illegal header.
# So the key is marked, only the marked line is taken, and a key with whitespace in it is refused.
KEY=$(zsh -i -c 'printf "\n__ARSLAN_KEY__%s\n" "$ARSLAN_SPIKE_DEEPSEEK_KEY"' 2>/dev/null </dev/null \
  | sed -n 's/^__ARSLAN_KEY__//p' | tail -n 1)
[ -n "$KEY" ] || { echo "ARSLAN_SPIKE_DEEPSEEK_KEY is not set"; exit 1; }
case "$KEY" in
  *[[:space:]]*) echo "ARSLAN_SPIKE_DEEPSEEK_KEY has spaces or line breaks in it; fix it in your shell profile"; exit 1 ;;
esac
cd "$REPO"
exec env BENCH_REAL_KEY="$KEY" BENCH_CAP_USD="${BENCH_CAP_USD:-5}" BENCH_RUN_CAP_USD="${BENCH_RUN_CAP_USD:-0.45}" \
  BENCH_LOG="$ROOT/usage.jsonl" .venv/bin/uvicorn scripts.kernel_bench.meter:app --host 127.0.0.1 --port 8900 --log-level warning
