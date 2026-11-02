#!/usr/bin/env python3
"""Render the README pictures: real panels and the gallery's own screens (same layout
and fonts as art/artd.lua), inside a drawn landscape Kindle Paperwhite 4.

  uv run --with pillow python tools/screenshots.py     writes docs/images/*.jpg
"""
import csv, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PANELS = os.path.join(ROOT, "content", "panels")
FONTS = os.path.join(ROOT, "art", "assets", "fonts")
OUT = os.path.join(ROOT, "docs", "images")
W, H = 1448, 1072

# e-ink: black is a soft dark grey, white is the paper's light warm grey
INK, PAPER = (34, 34, 36), (228, 226, 219)


def font(px, bold=False):
    name = "AtkinsonHyperlegible-Bold.ttf" if bold else "AtkinsonHyperlegible-Regular.ttf"
    return ImageFont.truetype(os.path.join(FONTS, name), px)


def catalog():
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(ROOT, "content", "catalog.tsv"))
            if not l.startswith("#")]
    works = {r[0]: dict(id=r[0], coll=r[1], file=r[2], title=r[4], artist=r[5], date=r[6]) for r in rows}
    names, order = {}, {}
    for l in open(os.path.join(ROOT, "content", "collections.tsv")):
        if not l.startswith("#"):
            cid, name, o = l.rstrip("\n").split("\t")
            names[cid], order[cid] = name, int(o)
    counts = {}
    for w in works.values():
        counts[w["coll"]] = counts.get(w["coll"], 0) + 1
    colls = sorted(counts, key=lambda c: order.get(c, 1000))
    return works, [(c, names.get(c, c), counts[c]) for c in colls]


WORKS, COLLS = catalog()


# ------------------------------------------------------------------ screens (greyscale)
class Screen:
    """A 1448x1072 greyscale canvas with artd.lua's drawing primitives."""

    def __init__(self, panel=None):
        self.im = Image.open(os.path.join(PANELS, panel)).convert("L") if panel else Image.new("L", (W, H), 255)
        self.d = ImageDraw.Draw(self.im)

    def fill(self, x, y, w, h, color):
        self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=0 if color == "BLACK" else 255)

    def width(self, s, px, bold=False):
        return font(px, bold).getlength(s)

    def fit(self, s, mx, mn, w, bold=False):  # as fit() in artd.lua
        for px in range(mx, mn - 1, -1):
            if self.width(s, px, bold) * 1.05 <= w:
                return s, px
        while len(s) > 1 and self.width(s + "...", mn, bold) * 1.05 > w:
            s = s[:-1]
        return s.rstrip() + "...", mn

    def text(self, s, px, x, y, w, h, bold=False, center=False, invert=False):
        f = font(px, bold)
        top = y + max(0, round((h - px * 1.3) / 2))
        tx = x + (w - f.getlength(s)) / 2 if center else x
        self.d.text((tx, top), s, font=f, fill=255 if invert else 0)


def box(scr, x, y, w, h, label, px, primary=False):  # draw_box() in artd.lua
    scr.fill(x, y, w, h, "BLACK")
    if not primary:
        scr.fill(x + 3, y + 3, w - 6, h - 6, "WHITE")
    s, size = scr.fit(label, px, max(24, px - 10), w - 24, True)
    scr.text(s, size, x + 6, y + 6, w - 12, h - 12, bold=True, center=True, invert=primary)


def bar(scr, work, pos, total, batt=77):
    BAR_H = 300
    BAR_Y = H - BAR_H
    BTN_Y, BTN_H = BAR_Y + 186, 96
    scr.fill(0, BAR_Y, W, BAR_H, "BLACK")
    scr.fill(0, BAR_Y + 3, W, BAR_H - 3, "WHITE")
    s, px = scr.fit(work["title"], 50, 34, W - 64, True)
    scr.text(s, px, 32, BAR_Y + 16, W - 64, 76, bold=True)
    sub = work["artist"] + (", " + work["date"] if work["date"] else "")
    s, px = scr.fit(sub, 36, 26, W - 64)
    scr.text(s, px, 32, BAR_Y + 96, W - 64, 62)
    meta_x = 160 + 120 + 24
    meta_w = W - 24 - 300 - 24 - meta_x
    name = dict((c, n) for c, n, _ in COLLS)[work["coll"]]
    s, px = scr.fit(f"{name} · {pos}/{total}   ·   Batería {batt}%", 32, 24, meta_w)
    scr.text(s, px, meta_x, BTN_Y, meta_w, BTN_H, center=True)
    for x, w, label in ((24, 120, "«"), (160, 120, "»"), (W - 24 - 300, 300, "Ajustes")):
        box(scr, x, BTN_Y, w, BTN_H, label, 38)


def settings_screen(off=(), interval="1 h"):
    scr = Screen()
    CL_TOP, CL_ROW, CL_W, CL_X = 150, 80, 640, (60, 760)
    scr.text("Ajustes", 52, 0, 20, W, 80, bold=True, center=True)
    scr.text("Colecciones", 36, 60, 96, 600, 50, bold=True)
    for i, (cid, name, n) in enumerate(COLLS):
        x, y = CL_X[i % 2], CL_TOP + (i // 2) * CL_ROW
        on = cid not in off
        scr.fill(x, y + 12, 56, 56, "BLACK")
        scr.fill(x + 5, y + 17, 46, 46, "WHITE")
        if on:
            scr.fill(x + 13, y + 25, 30, 30, "BLACK")
        label, px = scr.fit(f"{name}  ({n})", 36, 28, CL_W - 80, True)
        scr.text(label, px, x + 80, y, CL_W - 80, 80, bold=on)
    SEG_X, SEG_Y, SEG_W, SEG_H, GAP = 400, 742, 150, 80, 14
    scr.text("Cambiar cada", 36, 60, SEG_Y, SEG_X - 80, SEG_H, bold=True)
    for k, label in enumerate(("1 min", "1 h", "3 h", "6 h", "24 h")):
        box(scr, SEG_X + k * (SEG_W + GAP), SEG_Y, SEG_W, SEG_H, label, 34, label == interval)
    box(scr, 60, 930, 480, 100, "Salir de la galería", 34)
    box(scr, W - 60 - 400, 930, 400, 100, "Listo", 44, True)
    return scr


def confirm_screen():
    scr = Screen()
    scr.text("¿Salir de la galería?", 60, 0, 250, W, 110, bold=True, center=True)
    scr.text("Volverás a la biblioteca del Kindle.", 38, 0, 420, W, 60, center=True)
    scr.text("Para volver a la galería, abre «1. Galería de arte».", 38, 0, 490, W, 60, center=True)
    box(scr, 214, 690, 500, 120, "No, seguir aquí", 40, True)
    box(scr, 734, 690, 500, 120, "Sí, salir", 40)
    return scr


def low_battery(scr, pct=14):
    label = f"Batería baja · {pct}%"
    bw = round(scr.width(label, 30, True) * 1.05) + 48
    bx, by, bh = W - bw - 24, H - 24 - 64, 64
    scr.fill(bx - 3, by - 3, bw + 6, bh + 6, "WHITE")
    scr.fill(bx, by, bw, bh, "BLACK")
    scr.text(label, 30, bx + 6, by + 4, bw - 12, bh - 8, bold=True, center=True, invert=True)


# ------------------------------------------------------------------ the device
def eink(gray):
    """Greyscale screen -> RGB with e-ink's limited contrast."""
    lut = [tuple(round(INK[c] + (PAPER[c] - INK[c]) * v / 255) for c in range(3)) for v in range(256)]
    r, g, b = (gray.point([l[c] for l in lut]) for c in range(3))
    return Image.merge("RGB", (r, g, b))


def device(scr):
    """Landscape Paperwhite 4: 167 x 116 mm body, 122 x 91 mm screen, the thick bezel
    (portrait bottom, with the logo) on the right. 11.87 px per mm at 1:1."""
    mm = W / 122
    bw, bh = round(167 * mm), round(116 * mm)
    sx, sy = round(16 * mm), (bh - H) // 2
    body = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    r = round(7 * mm)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], r, fill=(22, 22, 24))
    d.rounded_rectangle([3, 3, bw - 4, bh - 4], r - 3, outline=(48, 48, 52), width=2)  # edge light
    d.rectangle([sx - 3, sy - 3, sx + W + 2, sy + H + 2], fill=(12, 12, 13))
    body.paste(eink(scr.im), (sx, sy))
    logo = Image.new("RGBA", (400, 90), (0, 0, 0, 0))
    ImageDraw.Draw(logo).text((200, 45), "kindle", font=font(56), fill=(95, 95, 98), anchor="mm")
    logo = logo.rotate(90, expand=True)
    rx = sx + W + (bw - sx - W - logo.width) // 2
    body.alpha_composite(logo, (rx, (bh - logo.height) // 2))
    # glass: a faint diagonal sheen over the whole front
    sheen = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(sheen).polygon([(0, 0), (bw * 0.55, 0), (bw * 0.25, bh), (0, bh)], fill=14)
    sheen = sheen.filter(ImageFilter.GaussianBlur(120))
    white = Image.new("RGBA", (bw, bh), (255, 255, 255, 0))
    white.putalpha(Image.composite(sheen, Image.new("L", (bw, bh), 0), body.getchannel("A")))
    return Image.alpha_composite(body, white)


def stage(devices, cols=1, gap=120, margin=140, scale=0.5):
    """Devices on a soft background with shadows, scaled for the README."""
    dw, dh = devices[0].size
    rows = (len(devices) + cols - 1) // cols
    cw, ch = margin * 2 + cols * dw + (cols - 1) * gap, margin * 2 + rows * dh + (rows - 1) * gap
    bg = Image.new("RGB", (cw, ch), (238, 236, 231))
    grad = Image.linear_gradient("L").resize((cw, ch))
    bg = Image.composite(Image.new("RGB", (cw, ch), (226, 223, 216)), bg, grad)
    for i, dev in enumerate(devices):
        x = margin + (i % cols) * (dw + gap)
        y = margin + (i // cols) * (dh + gap)
        shadow = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(shadow).rounded_rectangle([x + 10, y + 40, x + dw - 10, y + dh + 30], 80, fill=120)
        shadow = shadow.filter(ImageFilter.GaussianBlur(45))
        bg = Image.composite(Image.new("RGB", (cw, ch), (150, 146, 138)), bg, shadow)
        bg.paste(dev, (x, y), dev)
    return bg.resize((round(cw * scale), round(ch * scale)), Image.LANCZOS)


def save(im, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    im.save(path, quality=88, optimize=True, progressive=True)
    print(f"{path}: {im.size[0]}x{im.size[1]}, {os.path.getsize(path) // 1024} KB")


def work_screen(wid):
    return Screen(WORKS[wid]["file"])


if __name__ == "__main__":
    save(stage([device(work_screen("hokusai-ola"))], scale=0.6), "hero.jpg")

    scr = work_screen("rembrandt-ronda")
    bar(scr, WORKS["rembrandt-ronda"], 12, len(WORKS))
    save(stage([device(scr)], scale=0.5), "bar.jpg")

    save(stage([device(settings_screen(off={"fotografia", "ukiyoe", "cubismo"}))], scale=0.5),
         "settings.jpg")
    save(stage([device(confirm_screen())], scale=0.5), "exit.jpg")

    grid = ["bruegel-cazadores", "adams-tetons", "durero-rinoceronte", "hiroshige-kanbara",
            "vermeer-delft", "dore-londres"]
    save(stage([device(work_screen(w)) for w in grid], cols=2, scale=0.3), "gallery.jpg")

    scr = work_screen("turner-temerario")
    low_battery(scr)
    save(stage([device(scr)], scale=0.5), "battery.jpg")
