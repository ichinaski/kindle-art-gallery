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
`note` saying why).

## Panels

Every panel fills the 1448x1072 screen with no margins, in 16 greys without dithering,
about 450 KB. A 2% bleed is cut from each side (ragged paper edges), any remaining flat
scan border is trimmed (at most 6% per side), then the image is scaled to cover the
screen and the overflow cropped. `trim` (left, top, right, bottom fractions) replaces
the bleed, for mounts, margins and captions. `crop` (x, y in 0..1) chooses which part
to keep; the default is the centre, or y 0.4 for works much taller than the screen.
Dark works get their shadows lifted: on the device the darkest four of the 16 greys look
the same, so when more than 35% of a panel falls there, the build applies the mildest gamma
that brings it back to 35%. Without it, tenebrist paintings and night scenes turn into
black areas with a few lit shapes. A crop that loses the subject is not acceptable: works
that lose more than 20% to the landscape crop get a hand-set `crop` checked against the
original, or leave the catalogue.
For prints on a sheet, `content/tools/plate.py` suggests a trim that keeps only the
inked plate (no paper, captions or plate mark); check it on the contact sheet.

## The score

Each work gets a 0 to 100 score that predicts how it looks on the device. It combines
three measures: how much of the image's structure survives without colour (the share of
its edges that are differences in lightness rather than hue), its contrast, and how much
of it the landscape crop keeps. The weights come from rating all 322 works of the first
catalogue by eye, 1 to 5, on contact sheets with the grey range squeezed to the Kindle's,
and fitting the three measures to those ratings (correlation 0.78; the old hand-tuned
score reached 0.67). Other measures were tried and added nothing: the number of grey
levels, local contrast, edge density, texture, and whether the work is a print or a
photo. A 5 maps to 100 and a 1 to 0.

The score is a coarse filter, not the judge. A second, blind round showed why: among
works that already score 50 or more, it barely predicts how people rate them
(rank correlation 0.07). It separates the hopeless from the plausible and nothing finer.
Candidates need 50 to be considered.

## The blind panel

The catalogue is chosen by a blind panel. Every candidate and every current work that
scores 50 or more is rendered as on the screen, shuffled across collections and printed
on anonymous contact sheets: no titles, artists, collections or scores, only codes.
Three raters score each panel 1 to 5 with the same rubric (`content/tools/blind/rater.md`):
one Claude Opus and two Claude Sonnet sessions, each in a fresh context that knows nothing
of the curation so far. A calibration sheet opens every batch to check that a rater stays
consistent. `content/tools/blind/pool.py` makes the sheets and keeps the code map out of
reach; `aggregate.py` merges the ratings.

A work's rating is the mean of the Opus rating and the mean of the two Sonnet ratings, so
each model family counts once (the two Sonnet raters agree with each other far more than
with Opus: 0.79 against 0.5). A work is in when that rating is 3.5 or more. Flags for
borders, crops and stains are fixed by hand; nothing else overrides the panel. The ratings
of the last round are in `content/blind-ratings.tsv`.

The contact sheets simulate the screen with `simulate()` in build.py: paper white ~205,
black ~40, and the darkest four greys merged. A first round used a plain linear range,
which showed shadow detail the device cannot show; on the Kindle, dark still lifes and
cropped masterpieces that the panel had liked looked bad. A second round re-rated every
changed panel (shadow lift, new crops) with the corrected simulation and with a thumbnail
of the whole original beside each panel, so a crop that loses the subject is penalised.
Forty unchanged works were mixed in as controls: they came out 0.08 lower than in round 1,
so the scale held. Ratings of the same work across rounds agree only moderately (0.44):
the panel separates good from bad well, but works near the threshold could go either way.

In the first round, 739 works went to the panel and 359 passed; after the second round
and the device check, 297 remain. By medium the
differences were small: photography and ukiyo-e rated a little above average, painting
about average, and fine-line prints a little below (fine hatching turns grey at screen
size). What predicted a good rating best was large dark masses and a clear coarse
structure; busy fine detail hurt.

The build also prints flags next to the score: `recorta N%` (the crop loses N%),
`vertical`, `poco contraste`, `solo N grises`, `depende del color` and `amplía xN`
(upscaled, the source is too small). Besides the review page it writes contact sheets,
`content/review/<collection>-NN.jpg`, twelve panels each, best first, with the grey range
squeezed like the screen's. Look at those.

## What worked

Quality over quantity, and let the blind panel decide rather than expectations about a
medium. Engravings, woodcuts, ukiyo-e and black-and-white photography are made for this
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
