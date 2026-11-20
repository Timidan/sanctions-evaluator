"""Pairwise ordering accuracy of one or more adapter packages on JSONL pair files.

Scores every text on the released Foundation Model ONNX graph with onnxruntime (CPU), feeding
each package's LoRA tensors and reward head as graph inputs, the way the node's engine does.
Each package is truncated to its own max_tokens. A pair counts as won only when the chosen
answer scores strictly above the rejected one (the node's rule).

Run from the repo root:
  python score_pairs.py --pkg ours=baseline/pkg/reg87.safetensors --pkg canonical=baseline/pkg/reg96.safetensors \
      baseline/fixtures/provider_format.jsonl
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import PreTrainedTokenizerFast

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "kit"))
from float_runtime.lora_format import R_MAX, TARGETS, read_package  # noqa: E402

FOUNDATION = ROOT / "kit" / "foundation"
LAYERS = 22


def render(prompt, answer):
    return f"### Task:\n{prompt}\n\n### Answer:\n{answer}"


def truncate(ids, n):
    return ids if len(ids) <= n else ids[: n - 1] + [ids[-1]]


def feed_for(path):
    meta, t = read_package(path)
    r = int(meta["rank"])
    feed = {"lora.scale": np.array([float(meta["alpha"]) / r], np.float32),
            "head.weight": np.asarray(t["head.weight"], np.float32),
            "head.bias": np.asarray(t["head.bias"], np.float32)}
    for i in range(LAYERS):
        for name in TARGETS:
            a, b = np.asarray(t[f"lora.{i}.{name}.A"], np.float32), np.asarray(t[f"lora.{i}.{name}.B"], np.float32)
            pa = np.zeros((a.shape[0], R_MAX), np.float32)
            pb = np.zeros((R_MAX, b.shape[1]), np.float32)
            pa[:, :r], pb[:r, :] = a, b
            feed[f"lora.{i}.{name}.A"], feed[f"lora.{i}.{name}.B"] = pa, pb
    return feed, int(meta.get("max_tokens", 512))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", action="append", required=True, help="label=path.safetensors")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="score only the first N pairs of each file")
    ap.add_argument("--out", default=None, help="write per-pair scores here (JSONL)")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    tok = PreTrainedTokenizerFast(tokenizer_file=str(FOUNDATION / "tokenizer.json"))
    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    sess = ort.InferenceSession(str(FOUNDATION / "foundation_lora_fp32.onnx"), so, providers=["CPUExecutionProvider"])

    pairs = []
    for f in a.files:
        rows = [json.loads(l) for l in open(f) if l.strip()]
        rows = rows[: a.limit] if a.limit else rows
        pairs += [(Path(f).stem, r) for r in rows]

    out = open(a.out, "w") if a.out else None
    report = {}
    for spec in a.pkg:
        label, path = spec.split("=", 1)
        feed, max_tokens = feed_for(path)
        cache = {}

        def score(text):
            if text not in cache:
                ids = truncate(tok(text)["input_ids"], max_tokens)
                arr = np.array([ids], np.int64)
                cache[text] = float(sess.run(None, dict(feed, input_ids=arr, attention_mask=np.ones_like(arr)))[0].reshape(-1)[0])
            return cache[text]

        wins = defaultdict(lambda: [0, 0])
        for n, (fname, r) in enumerate(pairs, 1):
            c, j = score(render(r["prompt"], r["chosen"])), score(render(r["prompt"], r["rejected"]))
            ok = c > j
            for k in (fname, f"{fname}/{r.get('x_kind', '?')}"):
                wins[k][0] += ok
                wins[k][1] += 1
            if out:
                out.write(json.dumps({"pkg": label, "file": fname, "kind": r.get("x_kind"), "chosen": c,
                                      "rejected": j, "won": ok}) + "\n")
            if n % 200 == 0:
                print(f"{label}: {n}/{len(pairs)}", file=sys.stderr, flush=True)
        report[label] = {k: {"won": w, "pairs": t, "acc": round(w / t, 4)} for k, (w, t) in sorted(wins.items())}
        print(json.dumps({label: {k: v for k, v in report[label].items() if "/" not in k}}), flush=True)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
