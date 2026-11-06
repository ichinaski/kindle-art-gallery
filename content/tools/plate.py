"""Suggest a "trim" for a print on a sheet: find the inked plate, drop paper margins,
captions and plate marks.

    uv run --with pillow --with numpy python content/tools/plate.py content/originals/<id>.jpg ...

Paper colour is the median of the outer 2% of the image; a pixel is ink when it is 30
levels darker. The plate is the longest run of rows (then columns) with at least 4% ink,
allowing small gaps, so a caption separated by blank paper falls outside it. Prints the
suggested [l, t, r, b], with a 1.2% inset to lose the plate mark. Drawings that fill the
sheet have no margin to find: the result is then the default bleed. Check it on the sheet.
"""
import sys

import numpy as np
from PIL import Image, ImageFilter


def _run(mask, gap):
    best, start, last = (0, len(mask) - 1), None, None
    found = False
    for i, v in enumerate(mask):
        if v:
            if start is None or i - last > gap:
                start = i
            last = i
            if not found or last - start > best[1] - best[0]:
                best, found = (start, last), True
    return best


def plate(path, inset=0.012):
    im = Image.open(path).convert("L")
    im.thumbnail((900, 900))
    a = np.asarray(im.filter(ImageFilter.MedianFilter(3)), np.float32)
    h, w = a.shape
    e = max(2, min(h, w) // 50)
    paper = np.median(np.concatenate([a[:e].ravel(), a[-e:].ravel(), a[:, :e].ravel(), a[:, -e:].ravel()]))
    ink = a < paper - 30
    r0, r1 = _run(ink.mean(1) > 0.04, int(h * 0.012))
    c0, c1 = _run(ink[r0:r1 + 1].mean(0) > 0.04, int(w * 0.012))
    t = [c0 / w + inset, r0 / h + inset, 1 - (c1 + 1) / w + inset, 1 - (r1 + 1) / h + inset]
    if min(t) < 0 or t[0] + t[2] > 0.6 or t[1] + t[3] > 0.6:
        return [0.02, 0.02, 0.02, 0.02]  # no clear plate: keep the default bleed
    return [round(x, 3) for x in t]


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p.rsplit("/", 1)[-1], plate(p))
