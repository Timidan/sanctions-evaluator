#!/usr/bin/env bash
# Scores two registered packages on the public test files in baseline/fixtures:
#   registration 87, this adapter, and registration 96, the Canonical module for the family since 18 Nov 2026.
# Both are downloaded from the URLs in the node's registry and checked against the registered hashes.
# Needs: git, curl, jq, openssl 3.2 or newer (for keccak-256), python 3.10+ with requirements.txt installed.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE=${NODE:-https://devnode.telegraphprotocol.com}
REL=https://github.com/telegraphprotocol/telegraph-foundation/releases/download/modernbert-base-lora16-v1

# 1. Telegraph's kit (package reader) and the Foundation Model that validators run (599 MB)
[ -d kit ] || { git clone -q https://github.com/telegraphprotocol/telegraph-wasm-baseline kit && git -C kit checkout -q 1ed063e; }
mkdir -p kit/foundation
( cd kit/foundation
  for f in foundation_lora_fp32.onnx foundation.json tokenizer.json SHA256SUMS; do [ -s "$f" ] || curl -fL -O "$REL/$f"; done
  sha256sum -c --ignore-missing SHA256SUMS )

# 2. Both packages, from the registry
mkdir -p baseline/pkg
REG=$(curl -fsS "$NODE/api/wasm?intent=SANCTIONS_SCREENING_MATCH&resolve=SANCTIONS_SCREENING_MATCH_GENERAL")
for id in 87 96; do
  read -r url hash < <(jq -r --argjson id "$id" '[.. | objects | select(has("registration_id")) | select(.registration_id == $id)][0] | "\(.wasm_url) \(.wasm_hash)"' <<<"$REG")
  curl -fsSL "$url" -o "baseline/pkg/reg$id.safetensors"
  got=$(openssl dgst -keccak-256 "baseline/pkg/reg$id.safetensors" | awk '{print $NF}')
  [ "$got" = "$hash" ] || { echo "registration $id: the file hashes to $got, the registry says $hash"; exit 1; }
  echo "registration $id: $url matches the registered hash $hash"
done

# 3. Score. A pair is won only when the better answer scores strictly above the worse one, as on the node.
python score_pairs.py --threads "${THREADS:-4}" --pkg reg87=baseline/pkg/reg87.safetensors --pkg reg96=baseline/pkg/reg96.safetensors \
  --out baseline/scores.jsonl baseline/fixtures/*.jsonl > baseline/scores.log
python baseline/table.py
