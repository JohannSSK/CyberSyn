#!/usr/bin/env python3
"""Render every presentation slide to a 1600x900 PNG.

Design language mirrors the product: src/static/css/base.css tokens, the
app's own Inter / JetBrains Mono faces, and brand logos drawn from
simple-icons via svgrender.py.

    python3 deck-assets/build_slides.py
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHOTS = ROOT / "SCREENSHOTS"

# --------------------------------------------------------------------------
# Tokens (src/static/css/base.css)
# --------------------------------------------------------------------------
BG = "#101318"
SURFACE = "#161a21"
SURFACE2 = "#1c212a"
SURFACE3 = "#232936"
SURFACE4 = "#2b3242"
BORDER = "#2c3445"
BORDER_SOFT = "#222836"
BORDER_STRONG = "#3a4358"
TEXT = "#e8eaee"
TEXT_STRONG = "#f6f7f9"
TEXT_DIM = "#b9bec9"
TEXT_MUTED = "#8d93a1"
ACCENT = "#ecebe7"
ACCENT_DEEP = "#d6d3cc"
SUCCESS = "#97ab91"
WARN = "#bfa273"
DANGER = "#bd8a80"
CODE_BG = "#0d1015"

# Author every slide at 1600x900 and render at SSx, so text and lines stay
# crisp when the slide is shown full-screen.
SS = 2
W, H = 1600, 900          # authoring space; every coordinate below is in it
DW, DH = W * SS, H * SS   # device space, what actually gets rasterised
MARGIN = 96

_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _woff_to_ttf(src: Path) -> Path:
    out = HERE / (src.stem + ".ttf")
    if not out.exists():
        from fontTools.ttLib import TTFont

        f = TTFont(str(src))
        f.flavor = None
        f.save(str(out))
    return out


SANS = {
    400: _woff_to_ttf(ROOT / "src/static/fonts/inter-latin-400-normal.woff2"),
    500: _woff_to_ttf(ROOT / "src/static/fonts/inter-latin-500-normal.woff2"),
    600: _woff_to_ttf(ROOT / "src/static/fonts/inter-latin-600-normal.woff2"),
}
MONO = {
    400: _woff_to_ttf(ROOT / "src/static/fonts/jetbrains-mono-latin-400-normal.woff2"),
    500: _woff_to_ttf(ROOT / "src/static/fonts/jetbrains-mono-latin-500-normal.woff2"),
}


def f(size: int, weight: int = 400, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Font for a size given in 1600x900 authoring space (scaled by SS)."""
    key = ("mono" if mono else "sans", weight, size)
    if key not in _fonts:
        src = MONO.get(weight, MONO[400]) if mono else SANS.get(weight, SANS[400])
        _fonts[key] = ImageFont.truetype(str(src), int(size * SS))
    return _fonts[key]


class ScaledDraw:
    """ImageDraw proxy that turns 1600x900 authoring coordinates into device px."""

    def __init__(self, draw, ss):
        self._d = draw
        self._ss = ss

    def _p(self, xy):
        return (xy[0] * self._ss, xy[1] * self._ss)

    def _box(self, b):
        return [b[0] * self._ss, b[1] * self._ss, b[2] * self._ss, b[3] * self._ss]

    def _pts(self, pts):
        return [(x * self._ss, y * self._ss) for x, y in pts]

    def _w(self, w):
        return max(1, int(round(w * self._ss)))

    def text(self, xy, s, font=None, fill=None, anchor=None, spacing=4, joint=None):
        return self._d.text(self._p(xy), s, font=font, fill=fill, anchor=anchor,
                            spacing=spacing * self._ss, joint=joint)

    def rounded_rectangle(self, b, radius=None, **kw):
        return self._d.rounded_rectangle(self._box(b), radius=radius * self._ss, **kw)

    def rectangle(self, b, **kw):
        return self._d.rectangle(self._box(b), **kw)

    def line(self, pts, **kw):
        kw["width"] = self._w(kw.get("width", 1))
        return self._d.line(self._pts(pts), **kw)

    def ellipse(self, b, **kw):
        return self._d.ellipse(self._box(b), **kw)

    def polygon(self, pts, **kw):
        return self._d.polygon(self._pts(pts), **kw)

    def __getattr__(self, name):
        return getattr(self._d, name)


# --------------------------------------------------------------------------
# Canvas
# --------------------------------------------------------------------------
RAIL_W = 20          # the cream rail, always on the left edge
RAIL_INK = ACCENT_DEEP


class Slide:
    def __init__(self, bg: str = BG):
        self.img = Image.new("RGBA", (DW, DH), bg)
        self.d = ScaledDraw(ImageDraw.Draw(self.img), SS)
        # One rail, left edge, every slide — it never alternates or moves.
        self.d.rectangle([0, 0, RAIL_W, 900], fill=RAIL_INK)

    def text(self, xy, s, size=24, color=TEXT, weight=400, mono=False, anchor="la", spacing=6):
        self.d.text(xy, s, font=f(size, weight, mono), fill=color, anchor=anchor,
                    spacing=spacing)
        return self

    def rtext(self, xy, s, size=24, color=TEXT, weight=400, mono=False, anchor="ra"):
        return self.text(xy, s, size, color, weight, mono, anchor)

    def ctext(self, xy, s, size=24, color=TEXT, weight=400, mono=False, anchor="mm"):
        return self.text(xy, s, size, color, weight, mono, anchor)

    def box(self, b, radius=18, fill=SURFACE, outline=BORDER, width=2):
        self.d.rounded_rectangle(b, radius=radius, fill=fill, outline=outline, width=width)
        return self

    def rect(self, b, fill):
        self.d.rectangle(b, fill=fill)
        return self

    def line(self, pts, fill=BORDER_STRONG, width=3):
        self.d.line(pts, fill=fill, width=width, joint="curve")
        return self

    def arrow(self, x0, y0, x1, y1, color=ACCENT_DEEP, width=4, head=18):
        self.line([(x0, y0), (x1, y1)], fill=color, width=width)
        ang = math.atan2(y1 - y0, x1 - x0)
        for a in (ang + math.radians(152), ang - math.radians(152)):
            self.line([(x1, y1), (x1 + head * math.cos(a), y1 + head * math.sin(a))],
                      fill=color, width=width)
        return self

    def paste(self, im, xy):
        self.img.paste(im, (int(xy[0] * SS), int(xy[1] * SS)), im)
        return self

    def logo(self, slug, xy, size, color=TEXT_DIM):
        import svgrender

        if not (HERE / "logos" / f"{slug}.svg").exists():
            return self
        im = svgrender.render_svg((HERE / "logos" / f"{slug}.svg").read_text(),
                                  int(size * SS), color)
        return self.paste(im, xy)

    def brand(self, xy, size):
        """The CyberSyn badge, cropped and keyed out of its tile."""
        p = HERE / "brand" / "cybersyn-mark.png"
        if not p.exists():
            return self
        im = Image.open(p).convert("RGBA")
        w = int(size * SS)
        h = int(im.height * (w / im.width))
        return self.paste(im.resize((w, h), Image.LANCZOS), xy)

    def chip(self, b, text, color=TEXT_DIM, fill=SURFACE2, size=22, weight=500,
             outline=BORDER, pad=18, radius=14, mono=False):
        x0, y0, x1, y1 = b
        self.box(b, radius=radius, fill=fill, outline=outline, width=2)
        self.ctext(((x0 + x1) / 2, (y0 + y1) / 2), text, size=size, color=color,
                   weight=weight, mono=mono)
        return self

    def kicker(self, s, y=96, color=TEXT_MUTED):
        self.d.rectangle([MARGIN, y, MARGIN + 46, y + 4], fill=ACCENT_DEEP)
        self.text((MARGIN + 62, y - 30), s, size=20, color=color, weight=500)
        return self

    def sub(self, s, y=128, color=TEXT_MUTED):
        self.text((MARGIN, y), s, size=24, color=color, weight=500)
        return self

    def save(self, name: str):
        self.img.convert("RGB").save(HERE / "slides" / f"{name}.png", quality=95)
        return name


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def wrap(d: ImageDraw.ImageDraw, s: str, font, max_w: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w * SS:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def para(sl: Slide, xy, s, size=24, color=TEXT, weight=400, max_w=1200, leading=1.5,
         mono=False):
    x, y = xy
    font = f(size, weight, mono)
    for ln in wrap(sl.d, s, font, max_w):
        sl.text((x, y), ln, size=size, color=color, weight=weight, mono=mono)
        y += int(size * leading)
    return y


# --------------------------------------------------------------------------
# Shared pieces
# --------------------------------------------------------------------------
def shot(name: str) -> Image.Image:
    return Image.open(SHOTS / name).convert("RGBA")


def framed(img: Image.Image, bw: int, bh: int, radius=20, frame=SURFACE,
           outline=BORDER, width=3) -> Image.Image:
    """Fit `img` inside a bw x bh frame (1600-space), centred, with a border."""
    bw, bh = bw * SS, bh * SS
    radius, width = radius * SS, width * SS
    s = min((bw - 2 * width) / img.width, (bh - 2 * width) / img.height)
    nw, nh = int(img.width * s), int(img.height * s)
    im = img.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=radius, fill=frame,
                        outline=outline, width=width)
    out.paste(im, ((bw - nw) // 2, (bh - nh) // 2), im)
    return out


def terminal(sl: Slide, box, lines, title="terminal", prompt="$"):
    """Draw a terminal window inside `box` = (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = box
    sl.box(box, radius=16, fill=CODE_BG, outline=BORDER, width=2)
    bar_h = 46
    sl.d.rounded_rectangle([x0, y0, x1, y0 + bar_h], radius=16, fill=SURFACE)
    sl.d.rectangle([x0, y0 + bar_h - 16, x1, y0 + bar_h], fill=SURFACE)
    for i, c in enumerate((DANGER, WARN, SUCCESS)):
        cx = x0 + 28 + i * 26
        sl.d.ellipse([cx - 8, y0 + bar_h / 2 - 8, cx + 8, y0 + bar_h / 2 + 8], fill=c)
    sl.ctext(((x0 + x1) / 2, y0 + bar_h / 2), title, size=18, color=TEXT_MUTED, mono=True)

    colors = {"cmd": TEXT_STRONG, "out": TEXT_MUTED, "ok": SUCCESS,
              "err": DANGER, "dim": TEXT_MUTED, "acc": ACCENT, "key": WARN}
    pad = 30
    y = y0 + bar_h + 26
    lh = 32
    for kind, txt in lines:
        col = colors.get(kind, TEXT)
        if kind == "cmd":
            sl.text((x0 + pad, y), prompt, size=20, color=SUCCESS, mono=True)
            sl.text((x0 + pad + 30, y), txt, size=20, color=col, mono=True)
        elif kind == "out":
            sl.text((x0 + pad, y), txt, size=19, color=col, mono=True)
        else:
            sl.text((x0 + pad, y), txt, size=20, color=col, mono=True)
        y += lh
    return y


# ==========================================================================
# Slides
# ==========================================================================
def s_title():
    sl = Slide()
    sl.brand((MARGIN, 200), 190)
    sl.text((MARGIN, 428), "NETCOMPANY ATHENS HACKATHON 2026", size=22, color=TEXT_MUTED, weight=500)
    sl.text((MARGIN, 478), "CyberSyn", size=96, color=TEXT_STRONG, weight=600)
    sl.text((MARGIN, 588), "an AI security gateway", size=30, color=TEXT_DIM)
    sl.line([(MARGIN, 668), (MARGIN + 620, 668)], fill=BORDER, width=2)
    sl.text((MARGIN, 698), "CYBERSYN ATTICA", size=20, color=TEXT_MUTED, weight=500, mono=True)
    return sl
    sl.text((MARGIN, 420), "NETCOMPANY ATHENS HACKATHON 2026", size=22, color=TEXT_MUTED, weight=500)
    sl.text((MARGIN, 470), "CyberSyn", size=96, color=TEXT_STRONG, weight=600)
    sl.text((MARGIN, 580), "an AI security gateway", size=30, color=TEXT_DIM)
    sl.line([(MARGIN, 660), (MARGIN + 620, 660)], fill=BORDER, width=2)
    sl.text((MARGIN, 690), "CYBERSYN ATTICA", size=20, color=TEXT_MUTED, weight=500, mono=True)
    return sl


def s_section(num, title, sub):
    sl = Slide()
    sl.text((MARGIN + 40, 300), num, size=150, color=SURFACE4, weight=600)
    sl.text((MARGIN + 40, 452), title, size=58, color=TEXT_STRONG, weight=600)
    sl.text((MARGIN + 40, 540), sub, size=24, color=TEXT_MUTED)
    return sl


def s_statement(big, small=None, big_size=72, accent=False):
    sl = Slide()
    y = 330
    for ln in wrap(sl.d, big, f(big_size, 600), 1300):
        sl.text((MARGIN + 40, y), ln, size=big_size,
                color=ACCENT if accent else TEXT_STRONG, weight=600)
        y += int(big_size * 1.16)
    if small:
        para(sl, (MARGIN + 40, y + 40), small, size=25, color=TEXT_MUTED, max_w=1150)
    return sl


def s_two_col(left_title, left_lines, right_title, right_lines, y=250):
    sl = Slide()
    sl.kicker("THE PROBLEM", y=96)
    col_w = 620
    for i, (title, lines, x) in enumerate((
            (left_title, left_lines, MARGIN),
            (right_title, right_lines, MARGIN + col_w + 80))):
        sl.text((x, y - 60), title, size=26, color=ACCENT, weight=600)
        yy = y
        for kind, txt in lines:
            col = {"bad": DANGER, "good": SUCCESS, "dim": TEXT_MUTED}.get(kind, TEXT)
            sl.text((x, yy), txt, size=23, color=col)
            yy += 44
    return sl


def s_image(im, caption=None, cap_color=TEXT_MUTED, y=170, h=600, bw=None):
    sl = Slide()
    s = min((W - 2 * MARGIN) / im.width, h / im.height) * SS
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    sl.paste(im, ((W - im.width / SS) // 2, y))
    if caption:
        sl.ctext((W / 2, y + im.height / SS + 44), caption, size=22, color=cap_color)
    return sl


def s_screenshot(img_name, caption, bw=1240, bh=700, y=170):
    sl = Slide()
    sl.kicker(caption[0], y=96)
    sl.sub(caption[1], y=128)
    im = framed(shot(img_name), bw, bh)
    sl.paste(im, ((W - bw) // 2, y))
    return sl


def s_card_row(cards, y=240, h=420, gap=36, x0=MARGIN):
    """cards: list of dicts with title, lines, color, icon."""
    sl = Slide()
    n = len(cards)
    cw = (W - 2 * x0 - gap * (n - 1)) / n
    for i, c in enumerate(cards):
        x = x0 + i * (cw + gap)
        sl.box([x, y, x + cw, y + h], radius=20, fill=SURFACE, outline=BORDER, width=2)
        col = c.get("color", ACCENT_DEEP)
        sl.d.rounded_rectangle([x, y, x + cw, y + 8], radius=4, fill=col)
        cy = y + 62
        if c.get("icon"):
            sl.logo(c["icon"], (x + 34, cy - 22), 44, col)
            sl.text((x + 92, cy + 2), c["title"], size=25, color=TEXT_STRONG, weight=600)
        else:
            sl.text((x + 34, cy), c["title"], size=25, color=TEXT_STRONG, weight=600)
        cy += 62
        for kind, txt in c["lines"]:
            col2 = {"ok": SUCCESS, "warn": WARN, "bad": DANGER, "dim": TEXT_MUTED}.get(kind, TEXT_DIM)
            if kind == "dot":
                sl.d.ellipse([x + 40, cy + 9, x + 50, cy + 19], fill=col2)
                sl.text((x + 66, cy), txt, size=21, color=TEXT)
            else:
                sl.text((x + 34, cy), txt, size=21, color=col2)
            cy += 40
    return sl


def s_logo_grid(title, slugs, cols=6, size=74, y=250, cw=220, ch=150, color=TEXT_DIM):
    sl = Slide()
    sl.kicker(title, y=96)
    rows = math.ceil(len(slugs) / cols)
    gw = cw * cols
    x0 = (W - gw) / 2
    for i, slug in enumerate(slugs):
        r, c = divmod(i, cols)
        x = x0 + c * cw
        yy = y + r * ch
        sl.box([x, yy, x + cw - 20, yy + ch - 20], radius=16, fill=SURFACE,
               outline=BORDER, width=2)
        sl.logo(slug, (x + (cw - 20) / 2 - size / 2, yy + 22), size, color)
        sl.ctext((x + (cw - 20) / 2, yy + ch - 58), slug, size=17, color=TEXT_MUTED)
    return sl


def s_big_number(num, label, sub=None, color=ACCENT):
    sl = Slide()
    sl.ctext((W / 2, 380), num, size=280, color=color, weight=600)
    sl.ctext((W / 2, 560), label, size=30, color=TEXT_DIM)
    if sub:
        sl.ctext((W / 2, 622), sub, size=22, color=TEXT_MUTED)
    return sl


def s_bullets(title, items, y=230, size=26, gap=60, kicker=None):
    sl = Slide()
    if kicker:
        sl.kicker(kicker, y=96)
        sl.sub(title, y=128)
    else:
        sl.text((MARGIN, 120), title, size=44, color=TEXT_STRONG, weight=600)
    yy = y
    for it in items:
        if isinstance(it, tuple):
            head, body = it
            sl.d.ellipse([MARGIN + 4, yy + 12, MARGIN + 16, yy + 24], fill=ACCENT_DEEP)
            sl.text((MARGIN + 40, yy), head, size=size, color=ACCENT, weight=600)
            sl.text((MARGIN + 40 + sl.d.textlength(head, font=f(size, 600)) + 16, yy),
                    body, size=size, color=TEXT_DIM)
        else:
            sl.d.ellipse([MARGIN + 4, yy + 12, MARGIN + 16, yy + 24], fill=ACCENT_DEEP)
            sl.text((MARGIN + 40, yy), it, size=size, color=TEXT)
        yy += gap
    return sl


def s_terminal(title, lines, kicker="RUNNING IT", h=620):
    sl = Slide()
    sl.kicker(kicker, y=96)
    sl.sub(title, y=128, color=TEXT_STRONG)
    terminal(sl, (MARGIN, 200, W - MARGIN, 200 + h), lines, title="bash")
    return sl


def s_table(title, headers, rows, y=240, col_w=None, size=23, head_size=21):
    sl = Slide()
    sl.text((MARGIN, 120), title, size=44, color=TEXT_STRONG, weight=600)
    n = len(headers)
    col_w = col_w or [620, 800]
    x = MARGIN
    xs = [MARGIN]
    for w in col_w:
        xs.append(xs[-1] + w)
    total = xs[-1]
    # header
    sl.box([MARGIN, y, total, y + 56], radius=10, fill=SURFACE3, outline=BORDER, width=2)
    for i, htxt in enumerate(headers):
        sl.text((xs[i] + 24, y + 28), htxt, size=head_size, color=TEXT_MUTED, weight=500, anchor="lm")
    yy = y + 56
    for r, row in enumerate(rows):
        rh = 58
        fill = SURFACE if r % 2 == 0 else BG
        sl.d.rectangle([MARGIN, yy, total, yy + rh], fill=fill)
        for i, cell in enumerate(row):
            col = TEXT
            if cell.startswith("!"):
                col, cell = DANGER, cell[1:]
            elif cell.startswith("+"):
                col, cell = SUCCESS, cell[1:]
            sl.text((xs[i] + 24, yy + rh / 2), cell, size=size, color=col, anchor="lm")
        sl.d.line([(MARGIN, yy + rh), (total, yy + rh)], fill=BORDER_SOFT, width=1)
        yy += rh
    sl.d.rectangle([MARGIN, y, total, yy], outline=BORDER, width=2)
    return sl


# --------------------------------------------------------------------------
# Diagrams
# --------------------------------------------------------------------------
def arch() -> Image.Image:
    """Browser <-> Flask <-> 3 scanners <-> provider, plus SQLite."""
    w, h = 1440, 700
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def node(cx, cy, rw, rh, fill, outline, label, sub=None, color=TEXT_STRONG):
        d.rounded_rectangle([cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2],
                            radius=18, fill=fill, outline=outline, width=3)
        d.text((cx, cy - (10 if sub else 0)), label, font=f(30, 600), fill=color, anchor="mm")
        if sub:
            d.text((cx, cy + 30), sub, font=f(19), fill=TEXT_MUTED, anchor="mm")

    y = 250
    node(150, y, 250, 110, SURFACE2, BORDER, "Browser")
    node(540, y, 320, 120, SURFACE3, BORDER_STRONG, "Flask app")
    node(950, y, 300, 110, SURFACE2, BORDER, "3 scanners")
    node(1300, y, 250, 110, SURFACE2, BORDER, "AI provider")
    node(540, 570, 260, 110, SURFACE2, BORDER, "SQLite")

    def arrow(x0, y0, x1, y1, color=ACCENT_DEEP, width=4, head=16):
        d.line([(x0, y0), (x1, y1)], fill=color, width=width)
        ang = math.atan2(y1 - y0, x1 - x0)
        for a in (ang + math.radians(152), ang - math.radians(152)):
            d.line([(x1, y1), (x1 + head * math.cos(a), y1 + head * math.sin(a))],
                   fill=color, width=width)

    arrow(276, y, 380, y)
    arrow(380, y + 22, 276, y + 22)
    arrow(700, y, 800, y)
    arrow(1100, y, 1176, y)
    arrow(540, y + 66, 540, 512)
    d.text((330, y - 34), "HTTP", font=f(18), fill=TEXT_MUTED)
    d.text((1120, y - 34), "LiteLLM", font=f(18), fill=TEXT_MUTED)
    d.text((560, 470), "chats · policy · logs", font=f(17), fill=TEXT_MUTED)
    return img


def flow() -> Image.Image:
    """prompt → three scanners → four outcomes."""
    w, h = 1440, 780
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 120, 330, 250], radius=18, fill=SURFACE3, outline=BORDER_STRONG, width=3)
    d.text((185, 172), "prompt", font=f(32, 600), fill=TEXT_STRONG, anchor="mm")
    d.text((185, 212), "from a member", font=f(19), fill=TEXT_MUTED, anchor="mm")

    rows = [
        ("1", "Personal & Greek identifiers", "AFM · AMKA · passports · IBAN · names"),
        ("2", "Confidential company context", "secrets · contracts · payroll · code"),
        ("3", "Prompt injection", "overrides · obfuscation · hidden instructions"),
    ]
    ys = [90, 320, 550]
    for (num, name, det), y in zip(rows, ys):
        d.rounded_rectangle([470, y, 880, y + 150], radius=18, fill=SURFACE2, outline=BORDER, width=3)
        d.ellipse([496, y + 34, 552, y + 90], fill=SURFACE4, outline=BORDER_STRONG, width=2)
        d.text((524, y + 62), num, font=f(28, 600), fill=ACCENT, anchor="mm")
        d.text((578, y + 48), name, font=f(24, 600), fill=TEXT_STRONG)
        d.text((578, y + 86), det, font=f(18), fill=TEXT_MUTED)
        d.line([(330, 185), (470, y + 75)], fill=BORDER_STRONG, width=3)

    outs = [("BLOCK", DANGER, "never sent"), ("WARN", WARN, "review first"),
            ("REDACT", ACCENT_DEEP, "masked, then sent"), ("ALLOW", SUCCESS, "sent as-is")]
    for i, (name, col, sub) in enumerate(outs):
        x = 1000 + i * 108
        d.rounded_rectangle([x, 290, x + 92, 470], radius=16, fill=SURFACE2, outline=col, width=3)
        d.text((x + 46, 344), name, font=f(19, 600), fill=col, anchor="mm")
        d.text((x + 46, 392), sub, font=f(13), fill=TEXT_MUTED, anchor="mm")
        d.line([(880, 405), (x + 46, 405)], fill=col, width=2)
    d.text((1000, 230), "the four outcomes", font=f(20), fill=TEXT_MUTED)
    return img


def s_end():
    sl = Slide()
    sl.brand((W / 2 - 84, 240), 168)
    sl.ctext((W / 2, 480), "Thanks.", size=88, color=ACCENT, weight=600)
    sl.ctext((W / 2, 600), "Made for NETCOMPANY ATHENS HACKATHON 2026",
             size=24, color=TEXT_DIM)
    sl.ctext((W / 2, 644), "by CYBERSYN ATTICA", size=24, color=TEXT_MUTED)
    return sl


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build():
    out = HERE / "slides"
    out.mkdir(exist_ok=True)
    made = []

    def add(name, fn, *a, **k):
        made.append(fn(*a, **k).save(name))

    # ---- cover --------------------------------------------------------
    add("01_title", s_title)

    # ---- problem ------------------------------------------------------
    add("02_section_problem", s_section, "01", "The problem",
        "shadow AI, and the data that walks out with it")
    add("03_already_using", s_statement,
        "Your employees are already using AI.",
        "The question is whether you can see it.", big_size=62)
    add("04_data_leaves", s_statement,
        "Prompt by prompt, client data leaves the building.", None, big_size=58)
    add("05_two_col", s_two_col,
        "The old answer", [("bad", "regex: too dumb for context"),
                           ("bad", "cloud AI security: a privacy paradox"),
                           ("dim", "and either way, the data is gone")],
        "What actually happens", [("dim", "a member pastes a client list"),
                                  ("dim", "into a chatbot they found themselves"),
                                  ("bad", "it is trained on, cached, exported")])

    # ---- why ----------------------------------------------------------
    add("06_section_why", s_section, "02", "Why local ML",
        "not regex, and not the cloud")
    add("07_not_regex", s_bullets, "Why not just regex?",
        ["Regex cannot read context.", "It matches shapes, not meaning.",
         "So it misses the clever payloads", "and cries wolf on the innocent ones."],
        kicker="02 · WHY MLS")
    add("08_not_cloud", s_bullets, "Why not the cloud?",
        ["Cloud AI security is a privacy paradox.", "You would ship the secret",
         "to the very service you are trying to keep it from."],
        kicker="02 · WHY MLS")
    add("09_local_ml", s_statement,
        "Local ML reads the prompt like a person would.",
        "Then it decides — on your own hardware.", big_size=52, accent=True)

    # ---- scanners -----------------------------------------------------
    add("10_section_scanners", s_section, "03", "Three scanners",
        "every prompt, locally, before it leaves")
    add("11_three_cards", s_card_row, [
        dict(title="1 · Personal & Greek", color=ACCENT_DEEP,
             lines=[("dot", "AFM, checksum-validated"), ("dot", "AMKA · passports · ID cards"),
                    ("dot", "phones · emails · IBANs"), ("dot", "names")]),
        dict(title="2 · Company context", color=ACCENT_DEEP,
             lines=[("dot", "credentials and secrets"), ("dot", "contracts and NDAs"),
                    ("dot", "financials · payroll · CRM"), ("dot", "source code")]),
        dict(title="3 · Prompt injection", color=ACCENT_DEEP,
             lines=[("dot", "instruction overrides"), ("dot", "obfuscated payloads"),
                    ("dot", "attacks hidden in comments")]),
    ], y=250, h=430)
    add("12_how_each_thinks", s_bullets, "How each one thinks",
        [("Scanner 1 — ", "regex rules plus English and Greek language models."),
         ("Scanner 2 — ", "regex rules plus a zero-shot classifier."),
         ("Scanner 3 — ", "attack patterns plus a zero-shot classifier.")],
        kicker="03 · THREE SCANNERS")

    # ---- actions ------------------------------------------------------
    add("16_section_actions", s_section, "04", "Four actions",
        "block, warn, redact, allow")
    add("17_four_cards", s_card_row, [
        dict(title="Block", color=DANGER, lines=[("bad", "never sent"), ("dim", "admin can release")]),
        dict(title="Warn", color=WARN, lines=[("warn", "member reviews"), ("dim", "confirm re-runs checks")]),
        dict(title="Redact", color=ACCENT_DEEP, lines=[("ok", "masked, then sent"), ("dim", "only masked text stored")]),
        dict(title="Allow", color=SUCCESS, lines=[("ok", "sent as-is"), ("dim", "destination still checked")]),
    ], y=270, h=380)
    add("18_small_print", s_bullets, "Small print",
        ["Repeated values share one token.", "Overlapping matches are masked together.",
         "Prompt injection cannot be redacted.", "Admins set defaults; members override."],
        kicker="05 · FOUR ACTIONS")

    # ---- running ------------------------------------------------------
    add("19_section_running", s_section, "05", "Running it", "Docker, or native")
    add("20_docker", s_terminal, "Docker, the recommended way",
        [("cmd", "git clone https://github.com/JohannSSK/CyberSyn.git"),
         ("cmd", "cd CyberSyn"),
         ("cmd", "docker compose up --build"),
         ("out", "  ✔ Container cybersyn-app-1  Started"),
         ("acc", "→ http://localhost:5000")], h=430)
    add("21_native", s_terminal, "Native, from source",
        [("cmd", "./setup.sh"),
         ("out", "  ==> Python 3.11–3.13"),
         ("out", "  ==> dependencies installed"),
         ("cmd", "./run.sh"),
         ("acc", "→ serving on http://localhost:5000")], h=430)
    add("22_seed", s_terminal, "Create the first administrator",
        [("cmd", "./run.sh seed admin"),
         ("out", "  administrator created"),
         ("ok", "  done")], h=300)
    add("23_login", s_screenshot, "Login-Page.png", ("06 · RUNNING IT", "the sign-in page"))

    # ---- backend ------------------------------------------------------
    add("24_section_backend", s_section, "06", "Under the hood",
        "Flask, Gunicorn, SQLite, Fernet")
    add("25_arch", s_image, arch(), None, y=190, h=620)
    add("26_backend_cards", s_card_row, [
        dict(title="Web app", color=ACCENT_DEEP, lines=[("dot", "Flask, UI and JSON API"), ("dim", "one process")]),
        dict(title="Server", color=ACCENT_DEEP, lines=[("dot", "Gunicorn 1 worker × 8 threads"), ("dim", "models stay warm")]),
        dict(title="Storage", color=ACCENT_DEEP, lines=[("dot", "SQLite, no external DB"), ("dim", "chats · policy · logs")]),
        dict(title="Secrets", color=ACCENT_DEEP, lines=[("dot", "Fernet, separate key file"), ("dim", "keys never shown again")]),
    ], y=250, h=400)
    add("27_warm", s_bullets, "Models load once, in the background",
        ["Warm at start-up, stay warm.", "The worker keeps them in memory.",
         "Threads share the scanner locks."],
        kicker="07 · UNDER THE HOOD")

    # ---- providers ----------------------------------------------------
    add("28_section_providers", s_section, "07", "Bring your own model",
        "LiteLLM, twelve providers")
    add("29_provider_logos", s_logo_grid, "08 · PROVIDERS",
        ["anthropic", "deepseek", "googlegemini", "mistralai", "ollama",
         "openrouter", "x", "flask"])
    add("30_byok", s_statement, "You bring the key. CyberSyn brings the guardrail.",
        None, big_size=50)
    add("31_seat_model", s_bullets, "How a seat gets a model",
        ["Settings → paste an API key.", "Pick a model from the provider's list.",
         "Save. The key is encrypted at rest."],
        kicker="08 · PROVIDERS")

    # ---- team ---------------------------------------------------------
    add("32_section_team", s_section, "08", "How a team uses it",
        "administrators and members")
    add("33_roles", s_card_row, [
        dict(title="Administrator", color=ACCENT,
             lines=[("dot", "adds and removes members"), ("dot", "sets workspace policy"),
                    ("dot", "approves keys and releases"), ("dot", "reads statistics and reports")]),
        dict(title="Team member", color=ACCENT_DEEP,
             lines=[("dot", "chats through the gateway"), ("dot", "sees findings and reasons"),
                    ("dot", "sets their own model"), ("dot", "manages chats and account")]),
    ], y=270, h=420)
    add("34_workspace", s_statement, "One administrator, one workspace.",
        "Members sign in with username, password and workspace name.", big_size=54)
    add("35_typical_chat", s_screenshot, "Typical-chat.png",
        ("09 · A DAY IN THE LIFE", "a normal conversation, screened"))
    add("36_new_chat", s_screenshot, "New-chat.png",
        ("09 · A DAY IN THE LIFE", "a fresh chat"))
    add("37_blocked", s_screenshot, "Blocked-message.png",
        ("05 · FOUR ACTIONS", "when a prompt is blocked"))

    # ---- shadow AI ----------------------------------------------------
    add("38_section_shadow", s_section, "09", "Shadow AI discovery",
        "CSV, proxy and DNS logs")
    add("39_what_if", s_statement, "What if they just… use the website?",
        "Import the logs. See who talked to what.", big_size=52)
    add("40_shadow_dash", s_screenshot, "Shadow-Ai.png",
        ("10 · SHADOW AI", "the discovery dashboard"))
    add("41b_tool_inventory", s_table, "The tool inventory",
        ["Tool", "Vendor", "Risk", "Status"],
        [["OpenAI / ChatGPT", "OpenAI", "48", "+approved"],
         ["Anthropic / Claude", "Anthropic", "44", "+approved"],
         ["Google Gemini", "Google", "55", "+approved"],
         ["DeepSeek", "DeepSeek", "91", "!unapproved"],
         ["xAI Grok", "xAI", "82", "!unapproved"],
         ["Ollama (local)", "Ollama", "10", "+approved"]],
        y=230, col_w=[420, 320, 160, 440], size=23)
    add("41c_reports", s_bullets, "Reports",
        ["Filter by 7 days, 30 days or all time.",
         "Narrow by status, team or data category.",
         "Export as CSV or JSON.",
         "Ranked team view answers: who sent client data?"],
        kicker="10 · SHADOW AI")
    add("41_statuses", s_card_row, [
        dict(title="Approved", color=SUCCESS, lines=[("ok", "reachable through the gateway")]),
        dict(title="Restricted", color=WARN, lines=[("warn", "reachable, direct use flagged")]),
        dict(title="Unapproved", color=DANGER, lines=[("bad", "blocked unless approved")]),
    ], y=280, h=340)
    add("42_parser_keeps", s_bullets, "What the parser keeps",
        ["destination host · team · actor", "method · bytes · data category",
         "never the message contents"],
        kicker="10 · SHADOW AI")
    add("43_sample_week", s_statement, "A synthetic sample week is built in.",
        "No real data needed for the demo.", big_size=48)

    # ---- statistics ---------------------------------------------------
    add("44_section_stats", s_section, "10", "Statistics and audit",
        "metadata, never message text")
    add("45_team_stats", s_screenshot, "Team-stats.png",
        ("11 · STATISTICS", "the team view"))
    add("46_what_admins_see", s_bullets, "What admins can see",
        ["Per member: sent, blocked, overridden.",
         "Trends: 30 days of blocks and overrides.",
         "Activity log: sign-ins, sends, warnings.", "Exports as CSV or JSON."],
        kicker="11 · STATISTICS")
    add("47_metadata_only", s_statement, "Audit is metadata-only.",
        "Stage, reason, actor, time. Never the prompt.", big_size=50)
    add("48_append_only", s_bullets, "Append-only",
        ["Block and override decisions are never pruned.",
         "Deleting a chat does not remove them."],
        kicker="11 · STATISTICS")

    # ---- proxy --------------------------------------------------------
    add("49_section_proxy", s_section, "11", "An OpenAI-compatible proxy",
        "any client, one base URL")
    add("50_proxy_term", s_terminal, "Point any client at /v1",
        [("cmd", "curl http://localhost:5000/v1/chat/completions \\"),
         ("cmd", "  -H \"Authorization: Bearer <seat-token>\" \\"),
         ("cmd", "  -d '{\"model\":\"default\",\"messages\":[...]}'"),
         ("ok", "  200 OK"),
         ("out", "  screened · redacted · audited")], h=430)
    add("51_why_proxy", s_bullets, "Why it matters",
        ["Screened under the member's own policy.", "Redacted on the way out.",
         "Reply restored on the way back.", "Audited like any other send."],
        kicker="12 · PROXY")

    # ---- security -----------------------------------------------------
    add("52_section_security", s_section, "12", "Security and privacy",
        "fail-closed by default")
    add("53_security_table", s_table, "How CyberSyn handles it",
        ["Area", "What it does"],
        [["Secrets", "Fernet-encrypted, key stored separately"],
         ["Passwords", "salted hashes; uniform errors; rate-limited"],
         ["Sessions", "HttpOnly, SameSite, hashed, revoked on change"],
         ["Fail-closed", "!a scanner failure refuses the prompt"],
         ["Audit", "metadata only — never the prompt"],
         ["Isolation", "+members see only their own chats"]],
        y=230, col_w=[280, 1060], size=22)
    add("54_fail_closed", s_statement,
        "If a check cannot run, the prompt is refused.",
        "Not sent. Never sent.", big_size=50, accent=True)

    # ---- extras -------------------------------------------------------
    add("55_section_extras", s_section, "13", "And the extras",
        "bilingual, responsive, searchable")
    add("56_also_in_box", s_bullets, "Also in the box",
        ["English and Greek, switched at runtime.",
         "Dates and numbers follow the locale.",
         "Responsive and minimal, on any screen.", "Multiple chats per member.",
         "Keyword search inside a chat."],
        kicker="14 · EXTRAS")
    add("57_honest_limits", s_bullets, "Honest limits",
        ["It is not perfect. It can never be.",
         "Blocks can be released by an administrator.",
         "Context per member is capped."],
        kicker="14 · EXTRAS")

    # ---- links --------------------------------------------------------
    add("58_section_links", s_section, "14", "Good to know", "where to look next")
    add("59_useful_places", s_table, "Useful places",
        ["Link", "What is there"],
        [["API_Examples.md", "the full JSON API, with runnable examples"],
         ["includes/constants.json", "route registry and feature flags"],
         ["src/templates/help.html", "in-app help and third-party licences"],
         ["LICENSE", "MIT — CyberSyn Attica 2026"]],
        y=250, col_w=[380, 960], size=23)
    add("60_end", s_end)

    print(f"{len(made)} slides written to {out}")
    for m in made:
        print("  ", m)


if __name__ == "__main__":
    build()
