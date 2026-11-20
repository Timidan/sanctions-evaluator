#!/usr/bin/env bash
# Scores both registered packages on another contributor's published sanctions pairs (1,000 rows, not copied here).
# Run baseline/run.sh first: it fetches the kit, the Foundation Model and both packages.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=https://raw.githubusercontent.com/VishAlgoDev/praman-desk/8b315d835b53cfb4ace96a2f5f3e32774b0baacf/eval-data/pairs_sanctions_v4.jsonl
curl -fsSL "$SRC" -o baseline/pkg/published_rows.jsonl
echo "a1217d1d421327f54384428b55bd3ea36d692145a88c51502c09df649a747c82  baseline/pkg/published_rows.jsonl" | sha256sum -c -
python score_pairs.py --threads "${THREADS:-4}" --pkg reg87=baseline/pkg/reg87.safetensors --pkg reg96=baseline/pkg/reg96.safetensors \
  baseline/pkg/published_rows.jsonl
