# Blind rating: pictures for an e-ink frame

You are one of three independent raters. You will see contact sheets of images exactly as
they will appear full screen on an e-ink picture frame: 16 shades of grey, low contrast
(the paper white is a light grey, the black a dark grey). Each sheet has 12 panels, each
labelled with a code like `3C07`.

Rate every panel 1 to 5 for one question: **how good is this as a picture to hang on the
wall, shown like this, on this screen?**

- 5: outstanding. Striking from across a room; clear, strong structure of light and dark;
  crisp; a composition that fills the frame well. You would want to see it again.
- 4: good. Clearly works on this screen; pleasant to live with.
- 3: acceptable but unremarkable: a bit flat, grey or busy, or the subject reads only up close.
- 2: weak: muddy, washed out, mostly mid-grey, confusing, hard to read, or awkwardly cropped.
- 1: bad: unreadable, broken, or plainly unsuitable.

Judge only what you see in the panel. Do not try to identify the work or the artist, and
do not reward fame, age, subject or medium: a photograph, a print and a painting are judged
by the same standard. Use the whole scale; aim to spread your ratings rather than giving
everything 3 or 4.

Also flag technical defects, only when clearly visible:
- `B`: border, paper margin, mount, caption, frame, film edge or stereo seam shows
- `C`: the crop cuts the subject badly (heads, the main object)
- `S`: stain, damage, heavy scan noise or watermark

## How

Read the batch's sheets with the read tool, in order. The first sheet of every batch is a
calibration sheet: rate it like any other. Look at each sheet once carefully, then write
your ratings. Do not open any other file on the machine besides the sheets listed in your
task and your output file (no scripts, no maps, no repos).

Write your output file as plain text, one line per panel, tab-separated:

```
3A01	4
3A02	2	B
3A03	5
```

Every code on every sheet must appear exactly once. Finish with a one-line reply: the
number of lines written.
