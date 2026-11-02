# Curating content

Collections are listed in `content/collections.tsv` (id, display name, order). Each one
has a works file, `content/works/<collection>.json`, which is the whole curation: where
each image comes from, whether it is in, and how to crop it. `content/build.py` does the
rest.

```
uv run --with pillow --with numpy --with requests --with fonttools python content/build.py
... content/build.py --collection barroco     one collection
... content/build.py --candidates             candidates in the catalogue too (testing)
```

It downloads the originals into `content/originals/`, renders
`content/panels/<collection>/<id>.png`, scores every work, writes a review page per
collection in `content/review/` (panel next to the colour original, with the scores),
and writes `content/catalog.tsv` with the approved works. Then `deploy.py --content`, or
a push and "Actualizar galería" on the Kindle, puts them on the device.

## A work

```json
{
  "id": "hokusai-ola",
  "title": "La gran ola de Kanagawa",
  "artist": "Katsushika Hokusai",
  "date": "c. 1831",
  "source": {"commons": "File:「富嶽三十六景 神奈川沖浪裏」-Under the Wave off Kanagawa ... MET DP141042.jpg"},
  "status": "approved",
  "crop": [0.5, 0.5]
}
```

`source` is one of `{"commons": "File:..."}` (Wikimedia Commons), `{"aic": "<image
id>"}` (Art Institute of Chicago), `{"url": "https://..."}` (fetched with a browser user
agent; WikiArt and museum sites) or `{"file": "path"}` (relative to `content/`, for
images you provide). After changing a source, delete `content/originals/<id>.jpg` so it
downloads again.

`status` is `candidate`, `approved` (in the catalogue) or `rejected` (kept with a
`note` saying why). `masterpiece: true` lets a vertical work in despite the crop.

## Panels

Every panel fills the 1448x1072 screen with no margins, in 16 greys without dithering,
about 450 KB. A 2% bleed is cut from each side (ragged paper edges), any remaining flat
scan border is trimmed (at most 6% per side), then the image is scaled to cover the
screen and the overflow cropped. `trim` (left, top, right, bottom fractions) replaces
the bleed, for mounts, margins and captions. `crop` (x, y in 0..1) chooses which part
to keep; the default is the centre, or y 0.4 for works much taller than the screen.

## The score

Each work gets a rough 0 to 100 score from its contrast, the grey levels it uses, how
much of its structure survives without colour, and how much the crop loses, with a
penalty for vertical works on a landscape screen. The build prints flags next to it:
`recorta N%` (the crop loses N%), `vertical`, `poco contraste` (low contrast),
`solo N grises` (only N greys used), `depende del color` (relies on colour) and
`amplía xN` (upscaled, the source is too small). A cut-off of 50 worked well: below
that, works were rejected.

## What worked

Well-known works first, and few of them: about 30 per collection is a guide, not a
quota. Engravings, woodcuts, ukiyo-e and black-and-white photography are made for this
screen; colourist paintings often turn to mush. Landscape works, since a vertical one
loses half its height. Always check the panels yourself, on a contact sheet or the
review page, and finally on the device: e-ink differs from a monitor.

Pick source files by hand. An automatic search once chose a later copy instead of the
original, a stained-glass window and a detail crop. On Commons, prefer Google Art
Project and museum uploads (very large and clean), and avoid "detail", "cropped",
"frame", gallery photos and copies "after" the work. `content/tools/commons.py` has
`search(query)`, which returns title, pixel size and type. For works under copyright,
WikiArt's per-artist list
(`https://www.wikiart.org/en/App/Painting/PaintingsByArtist?artistUrl=<artist>&json=2`)
gives image URLs; drop the `!Large.jpg` suffix for the full size.

## Traps

- Wikimedia Commons only allows scripts to request standard thumbnail widths (3840,
  1920, ...); anything else gets HTTP 429, and so does Python `requests` for full-size
  originals, which `curl` is served. `commons.py` handles both. Pause between files.
- Pillow's LAB mode stores a\* and b\* as signed bytes; read them as `int8`.
- Titles go through the bar's font: characters it cannot draw (kanji, for example) are
  dropped or replaced by their base letter when the catalogue is written.
