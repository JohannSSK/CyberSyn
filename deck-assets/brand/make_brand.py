#!/usr/bin/env python3
"""Key the CyberSyn badge out of its tile and crop it to the mark.

    python3 brand/make_brand.py [source.png]
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cybersyn-source.png"
OUT = HERE / "cybersyn-mark.png"

im = Image.open(SRC).convert("RGB")
w, h = im.size
px = im.load()
bg = px[2, 2]


def dist(c):
    return max(abs(c[i] - bg[i]) for i in range(3))


minx, miny, maxx, maxy = w, h, 0, 0
for y in range(h):
    for x in range(w):
        if dist(px[x, y]) > 12:
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)

out = Image.new("RGBA", (maxx - minx + 1, maxy - miny + 1))
op = out.load()
for y in range(miny, maxy + 1):
    for x in range(minx, maxx + 1):
        c = px[x, y]
        d = dist(c)
        a = 0 if d <= 14 else (255 if d >= 40 else int((d - 14) * 255 / 26))
        op[x - minx, y - miny] = (c[0], c[1], c[2], a)

out = out.crop(out.getbbox())
out.save(OUT)
print(f"{OUT.name}: {out.size}")
