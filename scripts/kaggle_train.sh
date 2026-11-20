#!/usr/bin/env bash
# Train on a private Kaggle T4 instead of this machine, then fetch the adapter into runs/<name>/.
# Usage: scripts/kaggle_train.sh <name> <train.jsonl> <val.jsonl> [more train_adapter args]
# Then: scripts/package.sh runs/<name>
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$1 TRAIN=$2 VAL=$3; shift 3
KUSER=${KUSER:?set KUSER to your Kaggle username} KSLUG=${KSLUG:-sanctions-eval-train-run} KDS=${KDS:-sanctions-eval-train}
DS=build/kaggle/$KSLUG/ds KN=build/kaggle/$KSLUG/kernel

rm -rf build/kaggle/$KSLUG && mkdir -p "$DS" "$KN"
rsync -a --exclude __pycache__ kit/float_runtime "$DS/"
cp "$TRAIN" "$DS/train.jsonl"; cp "$VAL" "$DS/val.jsonl"
jq -n --args '$ARGS.positional' -- "$@" > "$DS/args.json"
cat > "$DS/dataset-metadata.json" <<EOF
{"title": "$KDS", "id": "$KUSER/$KDS", "licenses": [{"name": "other"}]}
EOF
if kaggle datasets status "$KUSER/$KDS" >/dev/null 2>&1; then
  kaggle datasets version -p "$DS" -m "$NAME" --dir-mode zip -q
else
  kaggle datasets create -p "$DS" --dir-mode zip -q
fi
until [ "$(kaggle datasets status "$KUSER/$KDS" 2>/dev/null)" = ready ]; do sleep 15; done

cp scripts/kaggle_run.py "$KN/run.py"
cat > "$KN/kernel-metadata.json" <<EOF
{"id": "$KUSER/$KSLUG", "title": "$KSLUG", "code_file": "run.py",
 "language": "python", "kernel_type": "script", "is_private": true, "enable_gpu": true,
 "enable_internet": true, "machine_shape": "NvidiaTeslaT4", "dataset_sources": ["$KUSER/$KDS"]}
EOF
kaggle kernels push -p "$KN"
sleep 60
while kaggle kernels status "$KUSER/$KSLUG" | grep -qiE 'running|queued'; do sleep 120; done
kaggle kernels status "$KUSER/$KSLUG"
rm -rf "runs/$NAME" && mkdir -p "runs/$NAME"
kaggle kernels output "$KUSER/$KSLUG" -p "runs/$NAME" -q
[ -d "runs/$NAME/run/adapter" ] && mv "runs/$NAME/run/"* "runs/$NAME/" && rmdir "runs/$NAME/run"
grep -E '"verdict"' "runs/$NAME/result.json" || { echo "no result.json; see runs/$NAME/*.log"; exit 1; }
