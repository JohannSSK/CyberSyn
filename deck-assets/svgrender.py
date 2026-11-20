#!/usr/bin/env python3
"""Minimal SVG path rasteriser (fill only) used for the deck's brand logos.

Supports the subset simple-icons uses: M/L/H/V/C/S/Q/T/A/Z, absolute and
relative. Arc flags are read as single characters (SVG's rule), which is what
lets `0 00.186` parse as flag=0, flag=0, x=0.186. Filling follows the even-odd
rule, which is what those logos need for their counter-forms.
"""
from __future__ import annotations

import math
import re

from PIL import Image, ImageChops, ImageDraw

_NUM_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_SKIP = re.compile(r"[\s,]*")
_ARG = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2}


class Cursor:
    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def skip(self):
        m = _SKIP.match(self.s, self.i)
        self.i = m.end()

    def num(self):
        self.skip()
        m = _NUM_RE.match(self.s, self.i)
        if not m:
            raise ValueError(f"expected number at {self.s[self.i:self.i + 12]!r}")
        self.i = m.end()
        return float(m.group(0))

    def flag(self):
        self.skip()
        m = re.match(r"[01]", self.s[self.i:])
        if not m:
            raise ValueError(f"expected flag at {self.s[self.i:self.i + 12]!r}")
        self.i += 1
        return int(m.group(0))

    def has_more(self) -> bool:
        m = _SKIP.match(self.s, self.i)
        return m.end() < len(self.s)

    def peek_cmd(self):
        self.skip()
        m = re.match(r"[A-Za-z]", self.s[self.i:])
        return m.group(0) if m else None

    def cmd(self):
        self.skip()
        m = re.match(r"[A-Za-z]", self.s[self.i:])
        if not m:
            return None
        self.i += 1
        return m.group(0)


def _arc(x0, y0, rx, ry, phi, large, sweep, x1, y1):
    if rx == 0 or ry == 0:
        return [(x1, y1)]
    phi = math.radians(phi)
    dx2, dy2 = (x0 - x1) / 2, (y0 - y1) / 2
    x1p = math.cos(phi) * dx2 + math.sin(phi) * dy2
    y1p = -math.sin(phi) * dx2 + math.cos(phi) * dy2
    rx, ry = abs(rx), abs(ry)
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = math.cos(phi) * cxp - math.sin(phi) * cyp + (x0 + x1) / 2
    cy = math.sin(phi) * cxp + math.cos(phi) * cyp + (y0 + y1) / 2
    t1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    dt = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx) - t1
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    steps = max(10, int(abs(dt) / (math.pi / 20)) + 1)
    return [(cx + rx * math.cos(t1 + dt * i / steps) * math.cos(phi)
             - ry * math.sin(t1 + dt * i / steps) * math.sin(phi),
             cy + rx * math.cos(t1 + dt * i / steps) * math.sin(phi)
             + ry * math.sin(t1 + dt * i / steps) * math.cos(phi))
            for i in range(steps + 1)]


def _bez(p0, p, t, cub=True):
    mt = 1 - t
    if cub:
        return (mt ** 3 * p0[0] + 3 * mt ** 2 * t * p[0][0] + 3 * mt * t ** 2 * p[1][0] + t ** 3 * p[2][0],
                mt ** 3 * p0[1] + 3 * mt ** 2 * t * p[0][1] + 3 * mt * t ** 2 * p[1][1] + t ** 3 * p[2][1])
    return (mt ** 2 * p0[0] + 2 * mt * t * p[0][0] + t ** 2 * p[1][0],
            mt ** 2 * p0[1] + 2 * mt * t * p[0][1] + t ** 2 * p[1][1])


def polylines(d: str):
    c = Cursor(d)
    cx = cy = sx = sy = 0.0
    cmd = None
    cur: list[tuple[float, float]] = []
    out: list[list[tuple[float, float]]] = []

    while True:
        nxt = c.peek_cmd()
        if nxt is not None:
            c.cmd()
            cmd = nxt
            if cmd in "Mm":
                if cur:
                    out.append(cur)
                x, y = c.num(), c.num()
                if cmd == "m":
                    x, y = cx + x, cy + y
                cur = [(x, y)]
                cx, cy = sx, sy = x, y
                cmd = "l" if cmd == "m" else "L"
                continue
        elif cmd is None or not c.has_more():
            break
        rel, k = cmd.islower(), cmd.upper()
        if k == "Z":
            if cur:
                cur.append((sx, sy))
                out.append(cur)
            cur = []
            cx, cy = sx, sy
            cmd = None
        elif k in ("L", "M"):
            x, y = c.num(), c.num()
            if rel:
                x, y = cx + x, cy + y
            cur.append((x, y))
            cx, cy = x, y
        elif k == "H":
            x = c.num() + (cx if rel else 0)
            cur.append((x, cy))
            cx = x
        elif k == "V":
            y = c.num() + (cy if rel else 0)
            cur.append((cx, y))
            cy = y
        elif k in ("C", "S", "Q", "T"):
            n = _ARG[k]
            nums = [c.num() for _ in range(n)]
            if k == "C":
                p = [(nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])]
            elif k == "S":
                p = [cur[-2] if len(cur) > 1 else (cx, cy), (nums[0], nums[1]), (nums[2], nums[3])]
            elif k == "Q":
                p = [(nums[0], nums[1]), (nums[2], nums[3])]
            else:
                p = [cur[-2] if len(cur) > 1 else (cx, cy), (nums[0], nums[1])]
            if rel:
                p = [(cx + a, cy + b) for a, b in p]
            p0 = cur[-1] if cur else (cx, cy)
            steps = 20 if k in "CS" else 16
            for i in range(1, steps + 1):
                cur.append(_bez(p0, p, i / steps, cub=k in "CS"))
            cx, cy = p[-1]
        elif k == "A":
            rx, ry, phi = c.num(), c.num(), c.num()
            large, sweep = c.flag(), c.flag()
            x, y = c.num(), c.num()
            if rel:
                x, y = cx + x, cy + y
            cur.extend(_arc(cx, cy, rx, ry, phi, large, sweep, x, y))
            cx, cy = x, y
        else:
            break
    if cur:
        out.append(cur)
    return out


def fill_mask(paths, w: int, h: int, scale: float, ox: float, oy: float,
              rule: str = "nonzero") -> Image.Image:
    """Rasterise filled subpaths with the nonzero winding rule.

    A scanline sweep: crossings are collected per row, sorted by x, and the
    winding number is tracked so overlapping subpaths add while reversed
    subpaths punch holes — which is what the brand logos rely on.
    """
    # Nonzero winding via a scanline sweep. Each edge records the direction it
    # crosses the row, so overlapping contours add and reversed ones punch out.
    edges = []
    for pts in paths:
        p = [(ox + x * scale, oy + y * scale) for x, y in pts]
        for (x0, y0), (x1, y1) in zip(p, p[1:]):
            if y0 == y1:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, x1, 1))
            else:
                edges.append((y1, y0, x1, x0, -1))

    buckets: dict[int, list] = {}
    for e in edges:
        for row in range(max(0, int(math.floor(e[0]))), min(h, int(math.ceil(e[1])))):
            buckets.setdefault(row, []).append(e)

    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for row, bucket in buckets.items():
        yc = row + 0.5
        crossings = []
        for ylo, yhi, xlo, xhi, direction in bucket:
            if not (ylo <= yc < yhi):
                continue
            t = (yc - ylo) / (yhi - ylo)
            crossings.append((xlo + (xhi - xlo) * t, direction))
        if not crossings:
            continue
        crossings.sort()
        prev = None
        if rule == "evenodd":
            inside = False
            for x, _ in crossings:
                if inside and prev is not None:
                    draw.line([(prev, row), (x, row)], fill=255)
                inside = not inside
                prev = x
        else:
            winding = 0
            for x, d in crossings:
                if winding != 0 and prev is not None:
                    draw.line([(prev, row), (x, row)], fill=255)
                winding += d
                prev = x
    return img


def render_svg(svg_text: str, size: int, color: str, supersample: int = 2) -> Image.Image:
    """Render a single-path SVG to a transparent PNG tinted `color`."""
    vb = re.search(r'viewBox="([^"]+)"', svg_text)
    if vb:
        vx, vy, vw, vh = [float(v) for v in re.split(r"[ ,]+", vb.group(1).strip())]
    else:
        vx, vy, vw, vh = 0, 0, 24, 24
    dim = size * supersample
    scale = dim / vh
    ox = (dim - vw * scale) / 2 - vx * scale
    oy = (dim - vh * scale) / 2 - vy * scale
    paths: list = []
    for d in re.findall(r'<path[^>]*d="([^"]+)"', svg_text):
        paths.extend(polylines(d))
    mask = fill_mask(paths, dim, dim, scale, ox, oy).resize((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), color)
    img.putalpha(mask)
    return img


def render_file(path, size: int, color: str) -> Image.Image:
    with open(path) as fh:
        return render_svg(fh.read(), size, color)
