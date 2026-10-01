#!/bin/bash
# Install the outside entrants into $BENCH_ROOT only: Node 24 (checksum-verified), OpenClaw,
# DeepSeek Harness, goose. Nothing global is changed. Hermes is used from its normal install,
# run with its own HOME under $BENCH_ROOT so the user's ~/.hermes is never read or written.
set -euo pipefail
ROOT=${BENCH_ROOT:-/tmp/arslan-kernel-bench}
mkdir -p "$ROOT/pkgs" "$ROOT/tmp"
cd "$ROOT"
if [ ! -x node24/bin/node ]; then
  V=$(curl -s https://nodejs.org/dist/index.json | python3 -c "import json,sys;print([r['version'] for r in json.load(sys.stdin) if r['version'].startswith('v24.')][0])")
  curl -sSLO "https://nodejs.org/dist/$V/node-$V-darwin-arm64.tar.gz"
  curl -sSL "https://nodejs.org/dist/$V/SHASUMS256.txt" | grep "node-$V-darwin-arm64.tar.gz" | shasum -a 256 -c -
  tar xzf "node-$V-darwin-arm64.tar.gz" && mv "node-$V-darwin-arm64" node24
fi
export PATH="$ROOT/node24/bin:$PATH"
npm install --prefix "$ROOT/pkgs/openclaw" "openclaw@${OPENCLAW_VERSION:-latest}" --no-fund --no-audit
npm install --prefix "$ROOT/pkgs/dsh" "@deepseek-ai/dsh@${DSH_VERSION:-latest}" --no-fund --no-audit
mkdir -p "$ROOT/pkgs/goose" && cd "$ROOT/pkgs/goose"
gh release download "${GOOSE_VERSION:-$(gh release view --repo block/goose --json tagName -q .tagName)}" \
  --repo block/goose --pattern "goose-aarch64-apple-darwin.tar.gz" --clobber
tar xzf goose-aarch64-apple-darwin.tar.gz
# DeepSeek Harness defaults to deepseek-flash; every entrant must use the same model.
mkdir -p "$ROOT/home/dsh/.dsh/profiles/headless"
cat > "$ROOT/home/dsh/.dsh/profiles/headless/cordis.patch.yml" <<YML
- id: agent-default-model
  config:
    provider: deepseek-official
    model: ${BENCH_MODEL:-deepseek-v4-pro}
YML
echo "installed into $ROOT/pkgs"
