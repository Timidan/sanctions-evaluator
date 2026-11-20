"""Prints the comparison table from baseline/scores.jsonl (written by baseline/run.sh)."""
import collections
import glob
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = {Path(f).stem: [json.loads(l) for l in open(f)] for f in sorted(glob.glob(str(HERE / "fixtures/*.jsonl")))}
won = collections.defaultdict(dict)  # (pkg, file) -> {row index: won}
seen = collections.Counter()
for line in open(HERE / "scores.jsonl"):
    s = json.loads(line)
    key = (s["pkg"], s["file"])
    c, r = float(s["chosen"]), float(s["rejected"])
    if not (math.isfinite(c) and math.isfinite(r)):
        raise SystemExit(f"non-finite score for {key}")
    won[key][seen[key]] = c > r  # strictly higher, as on the node
    seen[key] += 1
pkgs = ["reg87", "reg96"]  # both registrations must be present
for p in pkgs:  # every package must have exactly one score per fixture row, no more and no fewer
    for name, rs in rows.items():
        if seen[(p, name)] != len(rs):
            raise SystemExit(f"{p} has {seen[(p, name)]} scores for {name}, expected {len(rs)}")
if set(seen) != {(p, name) for p in pkgs for name in rows}:
    raise SystemExit("scores.jsonl names a file that is not in baseline/fixtures")


def cell(pkg, name, keep=lambda r: True):
    w = [won[(pkg, name)][i] for i, r in enumerate(rows[name]) if keep(r)]
    return f"{sum(w)}/{len(w)}"


def both(pkg, name, group):  # twins: the same two answers, only the subject changes; a group counts when both rows are won
    g = collections.defaultdict(list)
    for i, r in enumerate(rows[name]):
        g[r[group]].append(won[(pkg, name)][i])
    return f"{sum(all(v) for v in g.values())}/{len(g)}"


print("| test file | pairs | " + " | ".join(pkgs) + " |\n|---|---:|" + "---:|" * len(pkgs))
tot = collections.Counter()
for name, rs in rows.items():
    print(f"| {name} | {len(rs)} | " + " | ".join(cell(p, name) for p in pkgs) + " |")
    for p in pkgs:
        tot[p] += sum(won[(p, name)].values())
print(f"| all files | {sum(len(r) for r in rows.values())} | " + " | ".join(str(tot[p]) for p in pkgs) + " |")
print("\nTwin groups (same two answers, only the queried name changes) where both rows are won:")
for name, group in (("astra_subject_twins", "x_group"), ("astra_short_forms", "x_group")):
    print(f"- {name}: " + ", ".join(f"{p} {both(p, name, group)}" for p in pkgs))
