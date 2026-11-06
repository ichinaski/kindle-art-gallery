#!/usr/bin/env python3
"""Build the gallery content: download, render, score, review, catalogue.

    uv run --with pillow --with numpy --with requests --with fonttools python content/build.py
    ... build.py --collection barroco          only one collection
    ... build.py --candidates                  put candidates in the catalogue too (testing)

Inputs:  content/collections.tsv, content/works/<collection>.json
Outputs: content/originals/<id>.jpg              downloads (committed)
         content/panels/<collection>/<id>.png    what the Kindle shows (committed)
         content/review/<collection>.html        review page: panel, colour original, scores
         content/review/<collection>-NN.jpg      contact sheets, e-ink grey range, best first
         content/catalog.tsv                     what the Kindle reads

A work: {"id", "title", "artist", "date", "source": {"commons": "File:..."},
{"aic": "<image id>"}, {"url": "https://..."} (WikiArt, museums) or {"file": "path under
content/"} (given by hand), "status": "candidate" | "approved" | "rejected",
optional "crop": [x, y] (0..1, which part to keep), "trim": [l, t, r, b] (fractions cut
before the automatic border trim; default 2% each side), "note"}.

Every panel fills the 1448x1072 screen with no margins (cover and crop), in 16 grey
levels without dithering.
"""

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import unicodedata

import numpy as np
import requests
from PIL import Image, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import commons  # noqa: E402

W, H = 1448, 1072
ORIGINALS = os.path.join(HERE, "originals")
PANELS = os.path.join(HERE, "panels")
REVIEW = os.path.join(HERE, "review")
FONT = os.path.join(HERE, "..", "art", "assets", "fonts", "AtkinsonHyperlegible-Regular.ttf")
BLEED = [0.02, 0.02, 0.02, 0.02]
AIC = "https://www.artic.edu/iiif/2/{id}/full/!3000,3000/0/default.jpg"
UA = {"User-Agent": "kindle-art-gallery/0.1 (personal e-ink art frame)",
      "AIC-User-Agent": "kindle-art-gallery/0.1 (personal e-ink art frame)"}
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


# ------------------------------------------------------------------ sources
def fetch(source, full=False):
    if "commons" in source:
        for attempt in range(5):
            try:
                return commons.download(source["commons"], full)
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))
    if "aic" in source:
        r = requests.get(AIC.format(id=source["aic"]), headers=UA, timeout=180)
        r.raise_for_status()
        return r.content
    if "url" in source:
        # direct image URL (WikiArt, museum sites): some refuse non-browser agents
        r = requests.get(source["url"], headers={"User-Agent": BROWSER}, timeout=180)
        r.raise_for_status()
        return r.content
    if "file" in source:
        # a file given by hand, relative to content/
        return open(os.path.join(HERE, source["file"]), "rb").read()
    raise ValueError(f"unknown source {source}")


def original(work):
    path = os.path.join(ORIGINALS, f"{work['id']}.jpg")
    if not os.path.exists(path):
        os.makedirs(ORIGINALS, exist_ok=True)
        # heavy trims (prints on big sheets) need the whole original
        full = max(work.get("trim", BLEED)) > 0.1
        im = Image.open(io.BytesIO(fetch(work["source"], full)))
        im = ImageOps.exif_transpose(im).convert("RGB")
        # keep 1.5x what a full-screen crop of the trimmed area needs: room to
        # re-crop, not more (prints on large sheets keep enough plate pixels)
        l, t, r, b = work.get("trim", BLEED)
        scale = 1.5 * max(W / (im.width * (1 - l - r)), H / (im.height * (1 - t - b)))
        if scale < 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        im.save(path, "JPEG", quality=90, optimize=True)
        time.sleep(4)  # be gentle with the image servers
    return path


# ------------------------------------------------------------------ rendering
def cut(im, fractions):
    l, t, r, b = fractions
    return im.crop((round(im.width * l), round(im.height * t),
                    round(im.width * (1 - r)), round(im.height * (1 - b))))


def trim(im, limit=0.06, tolerance=20, share=0.98):
    """Remove flat scan borders. Per side: border colour = median of the outermost
    line; move inward while `share` of each line is within `tolerance` of it."""
    a = np.asarray(im.convert("L"), dtype=np.int16)
    h, w = a.shape

    def depth(lines, cap):
        bg = np.median(lines[0])
        n = 0
        while n < cap and np.mean(np.abs(lines[n] - bg) <= tolerance) >= share:
            n += 1
        return n

    t, b = depth(a, int(h * limit)), depth(a[::-1], int(h * limit))
    l, r = depth(a.T, int(w * limit)), depth(a.T[::-1], int(w * limit))
    return im.crop((l, t, w - r, h - b))


def render(path, work):
    rgb = trim(cut(Image.open(path).convert("RGB"), work.get("trim", BLEED)))
    grey = ImageOps.autocontrast(rgb.convert("L"), cutoff=1)
    # vertical works: heads and focal points sit high, so keep the upper part by default
    default = [0.5, 0.4] if rgb.width < rgb.height * (W / H) * 0.85 else [0.5, 0.5]
    panel = ImageOps.fit(grey, (W, H), Image.LANCZOS, centering=tuple(work.get("crop", default)))
    return panel.point(lambda v: round(v / 17) * 17), rgb


# ------------------------------------------------------------------ scoring
CUTOFF = 50  # candidates below this do not go to the blind panel (see docs/content.md)


def scores(panel, rgb):
    """Numbers that predict how well a work survives 16 greys on a landscape screen.

    The score is a linear fit of three measures against 322 works rated by eye
    (1..5) on e-ink-simulated contact sheets, scaled so 0 is a 1 and 100 a 5:
    lightness share (structure that survives without colour), contrast and fit
    (how much of the work the landscape crop keeps). Correlation with the eye
    ratings is 0.78; extra measures (grey levels, local contrast, edge density,
    texture, a medium prior) added nothing in cross-validation."""
    aspect = rgb.width / rgb.height
    fit = min(W / rgb.width, H / rgb.height) / max(W / rgb.width, H / rgb.height)
    upscale = max(W / rgb.width, H / rgb.height)  # >1: fewer source pixels than screen
    p = np.asarray(panel, dtype=np.float32)
    hist = np.bincount((p // 17).astype(int).ravel(), minlength=16) / p.size
    levels = int((hist > 0.01).sum())
    contrast = float(p.std() / 255)
    # lightness share: how much of the colour image's edge strength (Delta E in L*a*b*)
    # survives in lightness alone. 1 = nothing lost in greyscale; low = the structure
    # is in hue and melts. Slight blur so JPEG chroma noise does not count.
    small = rgb.copy()
    small.thumbnail((400, 400))
    lab = np.asarray(small.filter(ImageFilter.GaussianBlur(1)).convert("LAB"), dtype=np.uint8)
    L = lab[..., 0].astype(np.float32) * 100 / 255
    a_, b_ = (lab[..., i].astype(np.int8).astype(np.float32) for i in (1, 2))  # stored signed
    ly, lx = np.gradient(L)
    ay, ax = np.gradient(a_)
    by, bx = np.gradient(b_)
    light = float(np.hypot(lx, ly).sum() / (np.sqrt(lx**2 + ly**2 + ax**2 + ay**2 + bx**2 + by**2).sum() + 1e-6))
    flags = []
    if fit < 0.75:
        flags.append(f"recorta {1 - fit:.0%}")
    if aspect < 1:
        flags.append("vertical")
    if upscale > 1.05:
        flags.append(f"amplía x{upscale:.2f}")
    if levels < 9:
        flags.append(f"solo {levels} grises")
    if contrast < 0.17:
        flags.append("poco contraste")
    if light < 0.60:
        flags.append("depende del color")
    # predicted eye rating (1..5) mapped to 0..100
    rating = 4.92 * light + 7.52 * min(contrast, 0.36) + 1.62 * fit - 3.6
    score = min(max(25 * (rating - 1), 0), 100)
    return dict(aspect=aspect, crop=1 - fit, upscale=upscale, levels=levels, contrast=contrast,
                light=light, flags=flags, score=round(score))


# ------------------------------------------------------------------ text
def clean(text):
    """Drop characters the bar's font cannot draw (e.g. kanji); keep accents."""
    from fontTools.ttLib import TTFont
    if not hasattr(clean, "cmap"):
        clean.cmap = set(TTFont(FONT).getBestCmap())
    out = []
    for ch in text or "":
        if ord(ch) in clean.cmap:
            out.append(ch)
        else:
            out.extend([c for c in unicodedata.normalize("NFKD", ch)
                        if ord(c) in clean.cmap and not unicodedata.combining(c)][:1])
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


# ------------------------------------------------------------------ review page
def review_page(cid, name, rows):
    cards = []
    for i, (w, s) in enumerate(sorted(rows, key=lambda r: -r[1]["score"]), start=1):
        flags = " · ".join(s["flags"]) or "sin avisos"
        cls = "bad" if s["score"] < CUTOFF else "ok" if s["score"] < CUTOFF + 15 else "good"
        cards.append(f"""
<div class="card {w['status']}">
  <div class="head"><b>{i}. {html.escape(w['title'])}</b> · {html.escape(w['artist'])}, {html.escape(w['date'])}
    <span class="id">{w['id']} · {w['status']}</span></div>
  <div class="imgs">
    <a href="../panels/{cid}/{w['id']}.png"><img class="panel" src="../panels/{cid}/{w['id']}.png"></a>
    <img class="thumb" src="thumbs/{w['id']}.jpg">
  </div>
  <div class="m"><span class="score {cls}">{s['score']}</span>
    contraste {s['contrast']:.2f} · {s['levels']}/16 grises · luz {s['light']:.2f} ·
    recorte {s['crop']:.0%} · formato {s['aspect']:.2f} · {flags}</div>
</div>""")
    return f"""<!doctype html><meta charset="utf-8"><title>{html.escape(name)}: revisión</title>
<style>
body{{font:14px -apple-system,sans-serif;margin:24px;background:#eee}}
.card{{background:#fff;margin:0 0 20px;padding:12px;border-radius:6px;max-width:1180px}}
.card.rejected{{opacity:.35}} .card.approved{{outline:3px solid #2a2}}
.head{{margin-bottom:8px}} .id{{color:#888;float:right}}
.imgs{{display:flex;gap:12px;align-items:flex-start}}
.panel{{width:724px;height:536px;filter:contrast(.92)}} .thumb{{max-width:420px;max-height:536px}}
.m{{margin-top:6px;color:#333}} .score{{font-weight:bold;padding:2px 8px;border-radius:4px;color:#fff}}
.good{{background:#2a2}} .ok{{background:#c90}} .bad{{background:#c33}}
</style>
<h1>{html.escape(name)}</h1>
<p>{len(rows)} obras, de mejor a peor puntuación. Izquierda: cómo se verá en el Kindle (16 grises,
pantalla completa). Derecha: original en color. Clic en el panel para verlo a tamaño real.</p>
{''.join(cards)}"""


def simulate(panel):
    """The panel roughly as the screen shows it: paper white ~205, black ~40."""
    return panel.convert("L").point(lambda v: 40 + v * 165 // 255)


def contact_sheets(cid, rows, per=12, tw=480, th=355):
    """review/<cid>-NN.jpg: 12 panels per sheet, best first, with the grey range
    as the screen shows it (see simulate), so mush shows."""
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(FONT, 18)
    for old in os.listdir(REVIEW):
        if re.fullmatch(rf"{re.escape(cid)}-\d\d\.jpg", old):
            os.remove(os.path.join(REVIEW, old))
    rows = sorted(rows, key=lambda r: -r[1]["score"])
    for k in range(0, len(rows), per):
        sheet = Image.new("L", (tw * 4, (th + 24) * 3), 255)
        draw = ImageDraw.Draw(sheet)
        for n, (w, s) in enumerate(rows[k:k + per]):
            p = simulate(Image.open(os.path.join(PANELS, cid, f"{w['id']}.png")))
            p = p.resize((tw, th), Image.LANCZOS)
            x, y = (n % 4) * tw, (n // 4) * (th + 24)
            sheet.paste(p, (x, y + 24))
            mark = "" if w["status"] == "approved" else f" [{w['status']}]"
            draw.text((x + 4, y + 2), f"{w['id']} {s['score']}{mark}", fill=0, font=font)
        sheet.save(os.path.join(REVIEW, f"{cid}-{k // per + 1:02d}.jpg"), quality=80)


# ------------------------------------------------------------------ main
def load_collections():
    out = []
    for line in open(os.path.join(HERE, "collections.tsv")):
        if line.startswith("#") or not line.strip():
            continue
        cid, name, order = line.rstrip("\n").split("\t")
        out.append((cid, name, int(order)))
    return sorted(out, key=lambda c: c[2])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--collection")
    p.add_argument("--candidates", action="store_true", help="catalogue candidates too")
    a = p.parse_args()

    catalog = []
    for cid, name, _ in load_collections():
        path = os.path.join(HERE, "works", f"{cid}.json")
        if not os.path.exists(path):
            continue
        works = json.load(open(path))
        if a.collection and cid != a.collection:
            # keep its existing panels in the catalogue
            for w in works:
                if w["status"] == "approved" or (a.candidates and w["status"] == "candidate"):
                    f = os.path.join(PANELS, cid, f"{w['id']}.png")
                    if os.path.exists(f):
                        catalog.append((w, cid, f))
            continue
        print(f"== {name}: {len(works)} works")
        os.makedirs(os.path.join(PANELS, cid), exist_ok=True)
        os.makedirs(os.path.join(REVIEW, "thumbs"), exist_ok=True)
        rows = []
        for w in works:
            if w["status"] == "rejected":
                continue
            try:
                src = original(w)
            except Exception as e:
                print(f"   ! {w['id']}: download failed: {e}")
                continue
            panel, rgb = render(src, w)
            out = os.path.join(PANELS, cid, f"{w['id']}.png")
            panel.save(out, optimize=True)
            thumb = rgb.copy()
            thumb.thumbnail((420, 536))
            thumb.save(os.path.join(REVIEW, "thumbs", f"{w['id']}.jpg"), quality=85)
            s = scores(panel, rgb)
            rows.append((w, s))
            print(f"   {s['score']:3} {w['id']:24} {' · '.join(s['flags'])}")
            if w["status"] == "approved" or (a.candidates and w["status"] == "candidate"):
                catalog.append((w, cid, out))
        with open(os.path.join(REVIEW, f"{cid}.html"), "w") as fh:
            fh.write(review_page(cid, name, rows))
        contact_sheets(cid, rows)

    with open(os.path.join(HERE, "catalog.tsv"), "w") as fh:
        fh.write("# id\tcollection\tfile\tsha256\ttitle\tartist\tdate\n")
        for w, cid, f in catalog:
            sha = hashlib.sha256(open(f, "rb").read()).hexdigest()
            fh.write("\t".join([w["id"], cid, f"{cid}/{w['id']}.png", sha, clean(w["title"]),
                                clean(w["artist"]), clean(w["date"])]) + "\n")
    print(f"catalog.tsv: {len(catalog)} works")


if __name__ == "__main__":
    main()
