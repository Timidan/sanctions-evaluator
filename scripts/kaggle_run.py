"""Runs inside the Kaggle notebook pushed by scripts/kaggle_train.sh: train with the kit, leave run/ as output.

Kaggle-specific choices:
- fp16, not bf16. The T4 has no bf16 hardware, but torch reports bf16 as supported and the kit then picks it,
  so training runs on slow emulation. We make torch report no bf16 so the kit takes its fp16 + grad-scaler path.
- r6's hyperparameters, stated explicitly. Without them the kit falls back to batch 1 x 16, rank 8, 3 epochs.
- No gradient checkpointing: the T4 has 16 GB, checkpointing only saves memory at ~30% extra time.
- The training log streams to stdout so progress shows in Kaggle's log viewer.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers==5.23.0", "peft==0.21.3"], check=True)
# Kaggle's image ships torchao 0.10, which peft 0.21 rejects on import; LoRA here does not use it.
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"], check=False)
src = os.path.dirname(glob.glob("/kaggle/input/**/train_adapter.py", recursive=True)[0])
data = os.path.dirname(glob.glob("/kaggle/input/**/args.json", recursive=True)[0])
work = "/kaggle/temp"
shutil.copytree(src, f"{work}/float_runtime", dirs_exist_ok=True)
args = json.load(open(f"{data}/args.json"))
HYPER = ["--batch-size", "8", "--grad-accum", "2", "--lora-rank", "16", "--lora-alpha", "32", "--lora-dropout", "0.1",
         "--epochs", "2", "--lr", "0.0001", "--weight-decay", "0.01", "--no-grad-checkpointing"]
boot = ("import sys, runpy, torch; torch.cuda.is_bf16_supported = lambda *a, **k: False; "
        "sys.argv = ['train_adapter'] + sys.argv[1:]; runpy.run_module('float_runtime.train_adapter', run_name='__main__')")
cmd = [sys.executable, "-c", boot, "--intent", "SANCTIONS_SCREENING_MATCH", "--data", f"{data}/train.jsonl",
       "--val-data", f"{data}/val.jsonl", "--out", "/kaggle/working/run", *HYPER, *args]
print(" ".join(cmd), flush=True)
with open("/kaggle/working/train.log", "w") as log:
    p = subprocess.Popen(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        log.write(line)
        log.flush()
        print(line, end="", flush=True)
    rc = p.wait()
print("exit", rc, "(the kit exits 1 after a passing run; judge by run/result.json)")
