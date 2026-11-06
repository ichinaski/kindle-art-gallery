"""Blind rating pool: every work (approved, candidate, rejected for taste), rendered as on
the device, shuffled onto anonymous contact sheets in batches. The code->work map goes
to ~/.cache/kag-blind/map.json, away from the raters.

    uv run --with pillow --with numpy --with requests --with fonttools python /tmp/blind/pool.py
"""
import json, os, random, sys, glob, re
REPO = "/Users/inigo.lopezdeheredia/projects/kindle-art-gallery/content"
sys.path.insert(0, REPO)
import build
from PIL import Image, ImageDraw, ImageFont

OUT = "/tmp/blind"
PRIV = os.path.expanduser("~/.cache/kag-blind")
SHEET, PER_BATCH = 12, 12          # 12 panels a sheet, 12 sheets a batch (+1 calibration)
TW, TH = 480, 355

def skip(w):
    n = w.get("note", "")
    return w["status"] == "rejected" and (n.startswith("técnico") or "fuente no encontrada" in n
                                          or "idéntica" in n)

works = []
for f in sorted(glob.glob(f"{REPO}/works/*.json")):
    for w in json.load(open(f)):
        if not skip(w):
            works.append((os.path.basename(f)[:-5], w))

rng = random.Random(20261105)
rng.shuffle(works)
font = ImageFont.truetype(f"{REPO}/../art/assets/fonts/AtkinsonHyperlegible-Bold.ttf", 22)
os.makedirs(PRIV, exist_ok=True)
for d in ("sheets",):
    os.makedirs(f"{OUT}/{d}", exist_ok=True)
for old in glob.glob(f"{OUT}/sheets/*.jpg"):
    os.remove(old)

panels, failed, lowscore = {}, [], []
for cid, w in works:
    try:
        p, rgb = build.render(build.original(w), w)
    except Exception as e:
        failed.append((w["id"], str(e)[:80])); continue
    s = build.scores(p, rgb)
    if s["score"] < 50:          # the same objective pre-filter for every work
        lowscore.append(w["id"]); continue
    panels[w["id"]] = (cid, w, p, s)
ids = [w["id"] for _, w in works if w["id"] in panels]
calib = rng.sample(ids, SHEET)           # same 12 works open every batch, under new codes

def draw(items, path):
    sheet = Image.new("L", (TW * 4, (TH + 30) * 3), 255)
    d = ImageDraw.Draw(sheet)
    for n, (code, wid) in enumerate(items):
        p = panels[wid][2].resize((TW, TH), Image.LANCZOS).point(lambda v: 40 + v * 165 // 255)
        x, y = (n % 4) * TW, (n // 4) * (TH + 30)
        sheet.paste(p, (x, y + 30))
        d.text((x + 6, y + 3), code, fill=0, font=font)
    sheet.save(path, quality=82)

mapping, batches = {}, []
chunks = [ids[i:i + SHEET] for i in range(0, len(ids), SHEET)]
for b in range(0, len(chunks), PER_BATCH):
    bn = b // PER_BATCH + 1
    sheets = []
    cal = calib[:]; rng.shuffle(cal)
    group = [cal] + chunks[b:b + PER_BATCH]
    for k, chunk in enumerate(group):
        items = []
        for n, wid in enumerate(chunk):
            code = f"{bn}{chr(65 + k)}{n + 1:02d}"      # e.g. 3C07: batch 3, sheet C, panel 7
            mapping[code] = {"id": wid, "calib": k == 0}
            items.append((code, wid))
        path = f"{OUT}/sheets/b{bn:02d}-{chr(65 + k)}.jpg"
        draw(items, path); sheets.append(path)
    batches.append(sheets)

json.dump({"map": mapping, "works": {i: {"cid": panels[i][0], "status": panels[i][1]["status"],
           "score": panels[i][3]["score"]} for i in ids}}, open(f"{PRIV}/map.json", "w"), indent=1)
json.dump(batches, open(f"{OUT}/batches.json", "w"), indent=1)
print(f"{len(ids)} works, {len(batches)} batches, below 50: {len(lowscore)}, failed: {failed}")
