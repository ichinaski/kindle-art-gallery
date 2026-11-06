"""Combine the blind ratings: per-rater agreement, calibration drift, mean rating per work,
a refit of the score on the blind means, and the selection rule.

    uv run --with numpy python ~/.cache/kag-blind/aggregate.py
"""
import glob, json, os, collections
import numpy as np

PRIV = os.path.expanduser("~/.cache/kag-blind")
M = json.load(open(f"{PRIV}/map.json"))
codes, works = M["map"], M["works"]

ratings = collections.defaultdict(dict)       # rater -> id -> [ratings]
flags = collections.defaultdict(lambda: collections.Counter())
calib = collections.defaultdict(lambda: collections.defaultdict(list))  # rater -> id -> per batch
for path in glob.glob("/tmp/blind/ratings/*/*.tsv"):
    rater = path.split("/")[-2]
    for line in open(path):
        p = line.rstrip("\n").split("\t")
        if len(p) < 2 or p[0] not in codes or not p[1].strip().isdigit():
            continue
        wid, r = codes[p[0]]["id"], int(p[1])
        if codes[p[0]]["calib"]:
            calib[rater][wid].append(r)
        else:
            ratings[rater].setdefault(wid, []).append(r)
        for f in (p[2] if len(p) > 2 else ""):
            if f in "BCS":
                flags[wid][f] += 1

raters = sorted(ratings)
ids = sorted(works)
print("raters:", raters, {r: len(ratings[r]) for r in raters}, "works:", len(ids))
missing = {r: [i for i in ids if i not in ratings[r]] for r in raters}
print("missing:", {r: len(v) for r, v in missing.items()})

def col(r):
    return np.array([np.mean(ratings[r][i]) if i in ratings[r] else np.nan for i in ids])
R = np.vstack([col(r) for r in raters])
def spear(a, b):
    m = ~np.isnan(a) & ~np.isnan(b)
    ra, rb = np.argsort(np.argsort(a[m])), np.argsort(np.argsort(b[m]))
    return np.corrcoef(ra, rb)[0, 1]
for i in range(len(raters)):
    for j in range(i + 1, len(raters)):
        print(f"agreement {raters[i]} ~ {raters[j]}: spearman {spear(R[i], R[j]):.2f}")
for r in raters:   # self-consistency on the calibration sheet, shown once per batch
    sds = [np.std(v) for v in calib[r].values() if len(v) > 1]
    print(f"calibration {r}: mean sd across batches {np.mean(sds):.2f}, mean {np.mean([np.mean(v) for v in calib[r].values()]):.2f}")

mean = np.nanmean(R, axis=0)
score = np.array([works[i]["score"] for i in ids])
print("score ~ blind mean: spearman", round(spear(score, mean), 2))
rule = (mean >= 3.5) & (score >= 60)
tech = {i: f for i, f in flags.items() if max(f.values()) >= 2}
out = []
for k, i in enumerate(ids):
    out.append(dict(id=i, cid=works[i]["cid"], status=works[i]["status"], score=int(score[k]),
                    mean=round(float(mean[k]), 2), each=[None if np.isnan(R[j][k]) else float(R[j][k]) for j in range(len(raters))],
                    passes=bool(rule[k]), flags=dict(tech.get(i, {}))))
json.dump(out, open(f"{PRIV}/result.json", "w"), indent=1, ensure_ascii=False)
by = collections.Counter(o["cid"] for o in out if o["passes"])
print("passing:", int(rule.sum()), dict(by))
print("passing but flagged:", [o["id"] for o in out if o["passes"] and o["flags"]])
