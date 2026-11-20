#!/usr/bin/env bash
# Export a trained adapter dir to a node package and check it. Run from a checkout that has Telegraph's kit in ./kit.
# Usage: scripts/package.sh runs/r4e1   (expects <dir>/adapter/)
set -euo pipefail
cd "$(dirname "$0")/../kit"
RUN="../$1"
cp foundation/tokenizer.json "$RUN/adapter/tokenizer.json"
"${PYTHON:-python3}" -m float_runtime.export_adapter --adapter "$RUN/adapter" --intent SANCTIONS_SCREENING_MATCH \
  --class judgment --foundation foundation/foundation.json --out "$RUN/SANCTIONS_SCREENING_MATCH.safetensors"
go run ./cmd/adapterbuild lora --intent SANCTIONS_SCREENING_MATCH --node-class judgment \
  --package "$RUN/SANCTIONS_SCREENING_MATCH.safetensors" --foundation foundation/foundation.json \
  > "$RUN/adapterbuild.json" 2> "$RUN/adapterbuild.err"
jq -r '"keccak256 \(.keccak256)  stage1 \(.manifest.verification.stage1)"' "$RUN/adapterbuild.json"
