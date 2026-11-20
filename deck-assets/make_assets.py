#!/usr/bin/env python3
"""Render the presentation's visual assets as PNGs.

Reuses the app's own icon paths (src/static/js/core/icons.js) and the design
tokens from src/static/css/base.css so the deck cannot drift from the product.

    python3 deck-assets/make_assets.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Design tokens — mirrored from src/static/css/base.css
# --------------------------------------------------------------------------
BG = "#101318"
SURFACE = "#161a21"
SURFACE2 = "#1c212a"
SURFACE3 = "#232936"
SURFACE4 = "#2b3242"
BORDER = "#2c3445"
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

# --------------------------------------------------------------------------
# Fonts — the app's own bundled faces, decompressed from woff2 to ttf
# --------------------------------------------------------------------------
_INTER = ROOT / "src/static/fonts/inter-latin-600-normal.woff2"
_MONO = ROOT / "src/static/fonts/jetbrains-mono-latin-400-normal.woff2"

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _load_woff(path: Path) -> Path:
    """Convert a bundled woff2 to ttf once, next to this script."""
    out = OUT / (path.stem + ".ttf")
    if out.exists():
        return out
    from fontTools.ttLib import TTFont

    font = TTFont(str(path))
    font.flavor = None
    font.save(str(out))
    return out


def font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    key = ("mono" if mono else "sans", size)
    if key not in _cache:
        src = _MONO if mono else _INTER
        _cache[key] = ImageFont.truetype(str(_load_woff(src)), size)
    return _cache[key]


# --------------------------------------------------------------------------
# Icon paths — parsed out of src/static/js/core/icons.js
# --------------------------------------------------------------------------
def icon_paths() -> dict[str, str]:
    js = (ROOT / "src/static/js/core/icons.js").read_text()
    table: dict[str, str] = {}
    for name, body in re.findall(r'^\s{8}(\w+):\s*\'(.+?)\',\s*$', js, re.M):
        table[name] = body
    return table


# A tiny SVG-path subset renderer: M, L, H, V, C, Q, A, Z (absolute and
# relative), plus circle/rect. Enough for the app's icon set.
import math

_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


_NUM = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"


def _tokenize(d: str):
    return re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM, d)


def _arc_points(x0, y0, rx, ry, phi, large, sweep, x1, y1):
    """Endpoint -> centre parameterisation, per SVG spec F.6.5."""
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
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = math.cos(phi) * cxp - math.sin(phi) * cyp + (x0 + x1) / 2
    cy = math.sin(phi) * cxp + math.cos(phi) * cyp + (y0 + y1) / 2
    theta1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    dtheta = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx) - theta1
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    steps = max(12, int(abs(dtheta) / (math.pi / 24)) + 1)
    pts = []
    for i in range(steps + 1):
        t = theta1 + dtheta * i / steps
        pts.append((cx + rx * math.cos(t) * math.cos(phi) - ry * math.sin(t) * math.sin(phi),
                    cy + rx * math.cos(t) * math.sin(phi) + ry * math.sin(t) * math.cos(phi)))
    return pts


def path_polylines(d: str, scale=1.0, ox=0.0, oy=0.0):
    """Return a list of polylines for an SVG path string."""
    toks = _tokenize(d)
    i = 0
    cx = cy = sx = sy = 0.0
    cmd = None
    out: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []

    def pt(x, y):
        return (ox + x * scale, oy + y * scale)

    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = float(toks[i]), float(toks[i + 1])
            i += 2
            if rel:
                x, y = cx + x, cy + y
            if cur:
                out.append(cur)
            cur = [pt(x, y)]
            cx, cy = x, y
            sx, sy = x, y
            cmd = "l" if rel else "L"
        elif c == "L":
            x, y = float(toks[i]), float(toks[i + 1])
            i += 2
            if rel:
                x, y = cx + x, cy + y
            cur.append(pt(x, y))
            cx, cy = x, y
        elif c == "H":
            x = float(toks[i])
            i += 1
            if rel:
                x = cx + x
            cur.append(pt(x, cy))
            cx = x
        elif c == "V":
            y = float(toks[i])
            i += 1
            if rel:
                y = cy + y
            cur.append(pt(cx, y))
            cy = y
        elif c in ("C", "S", "Q", "T"):
            n = {"C": 6, "S": 4, "Q": 4, "T": 2}[c]
            nums = [float(t) for t in toks[i:i + n]]
            i += n
            if c == "C":
                p = [(nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])]
            elif c == "S":
                p = [cur[-2] if len(cur) > 1 else (cx, cy), (nums[0], nums[1]), (nums[2], nums[3])]
            elif c == "Q":
                p = [(nums[0], nums[1]), (nums[2], nums[3])]
            else:
                p = [cur[-2] if len(cur) > 1 else (cx, cy), (nums[0], nums[1])]
            if rel:
                p = [(cx + a, cy + b) for a, b in p]
            # subdivide as a polyline
            if c in ("C", "S"):
                p0 = cur[-1] if cur else (cx, cy)
                steps = 24
                for k in range(1, steps + 1):
                    t = k / steps
                    mt = 1 - t
                    x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p[0][0] + 3 * mt * t ** 2 * p[1][0] + t ** 3 * p[2][0]
                    y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p[0][1] + 3 * mt * t ** 2 * p[1][1] + t ** 3 * p[2][1]
                    cur.append(pt(x, y))
            else:
                p0 = cur[-1] if cur else (cx, cy)
                steps = 20
                for k in range(1, steps + 1):
                    t = k / steps
                    mt = 1 - t
                    x = mt ** 2 * p0[0] + 2 * mt * t * p[0][0] + t ** 2 * p[1][0]
                    y = mt ** 2 * p0[1] + 2 * mt * t * p[0][1] + t ** 2 * p[1][1]
                    cur.append(pt(x, y))
            cx, cy = p[-1]
        elif c == "A":
            nums = [float(t) for t in toks[i:i + 7]]
            i += 7
            rx, ry, phi, large, sweep, x, y = nums
            if rel:
                x, y = cx + x, cy + y
            for px, py in _arc_points(cx, cy, rx, ry, phi, large, sweep, x, y):
                cur.append(pt(px, py))
            cx, cy = x, y
        elif c == "Z":
            if cur:
                cur.append(pt(sx, sy))
                out.append(cur)
            cur = []
            cx, cy = sx, sy
        else:
            i += 1
    if cur:
        out.append(cur)
    return out


def parse_svg(body: str):
    """Return (polylines, filled_rects, filled_circles) for an icon body."""
    strokes: list[list[tuple[float, float]]] = []
    fills: list[tuple[float, float, float, float]] = []
    circles: list[tuple[float, float, float]] = []
    for d in re.findall(r'<path[^>]*d="([^"]+)"', body):
        strokes.extend(path_polylines(d))
    for tag in re.findall(r'<rect[^>]*>', body):
        def g(k, default=None):
            m = re.search(k + r'="([^"]+)"', tag)
            return float(m.group(1)) if m else default
        fills.append((g("x", 0), g("y", 0), g("width", 0), g("height", 0)))
    for tag in re.findall(r'<circle[^>]*>', body):
        def g(k, default=None):
            m = re.search(k + r'="([^"]+)"', tag)
            return float(m.group(1)) if m else default
        circles.append((g("cx", 0), g("cy", 0), g("r", 0)))
    return strokes, fills, circles


# --------------------------------------------------------------------------
# Canvas helpers
# --------------------------------------------------------------------------
def canvas(w: int, h: int, bg: str = BG) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), bg)
    return img, ImageDraw.Draw(img)


def rounded(draw, box, radius, **kw):
    draw.rounded_rectangle(box, radius=radius, **kw)


def stroke_polylines(draw, lines, color, width, scale=1.0, ox=0.0, oy=0.0, joint="curve"):
    for pts in lines:
        p = [(ox + x * scale, oy + y * scale) for x, y in pts]
        if len(p) > 1:
            draw.line(p, fill=color, width=max(1, int(width)), joint=joint)


def fill_shapes(draw, fills, circles, color, scale=1.0, ox=0.0, oy=0.0):
    for x, y, w, h in fills:
        draw.rectangle([ox + x * scale, oy + y * scale, ox + (x + w) * scale, oy + (y + h) * scale],
                       fill=color)
    for cx, cy, r in circles:
        draw.ellipse([ox + (cx - r) * scale, oy + (cy - r) * scale,
                      ox + (cx + r) * scale, oy + (cy + r) * scale], fill=color)


def icon(name: str, size: int, color: str, filled: bool = False) -> Image.Image:
    """Render an app icon to a transparent PNG of `size` pixels."""
    table = icon_paths()
    body = table.get(name, table["help"])
    ss = 8
    dim = size * ss
    img = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = dim / 24
    strokes, fills, circles = parse_svg(body)
    if filled:
        fill_shapes(d, fills, circles, color, scale)
    stroke_polylines(d, strokes, color, 1.8 * ss * (size / dim) * (dim / size) * 1.0,
                     scale=scale, joint="curve")
    # stroke width was authored for a 24 grid at 1.8; scale with the render
    img = img.resize((size, size), Image.LANCZOS)
    return img


def icon_stroke(name: str, size: int, color: str, width: float = 1.8) -> Image.Image:
    table = icon_paths()
    body = table.get(name, table["help"])
    ss = 8
    dim = size * ss
    img = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = dim / 24
    strokes, fills, circles = parse_svg(body)
    stroke_polylines(d, strokes, color, width * ss, scale=scale, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------------------
# Terminal mockups
# --------------------------------------------------------------------------
def terminal(lines: list[tuple[str, str]], w=1180, title="terminal") -> Image.Image:
    """lines: (kind, text) where kind in prompt/cmd/out/ok/err/dim."""
    colors = {
        "prompt": TEXT_DIM,
        "cmd": TEXT_STRONG,
        "out": TEXT_MUTED,
        "ok": SUCCESS,
        "err": DANGER,
        "dim": TEXT_MUTED,
        "accent": ACCENT,
    }
    pad = 34
    line_h = 34
    top = 54
    h = top + pad + line_h * len(lines) + pad
    img, d = canvas(w, h, CODE_BG)
    # title bar
    d.rectangle([0, 0, w, top], fill=SURFACE)
    for i, c in enumerate(("#bd8a80", "#bfa273", "#97ab91")):
        cx = 26 + i * 24
        d.ellipse([cx - 7, top // 2 - 7, cx + 7, top // 2 + 7], fill=c)
    d.text((w // 2, top // 2), title, font=font(17, mono=True), fill=TEXT_MUTED, anchor="mm")
    y = top + pad
    for kind, text in lines:
        color = colors.get(kind, TEXT)
        if kind == "prompt":
            d.text((pad, y), "$", font=font(19, mono=True), fill=SUCCESS)
            d.text((pad + 30, y), text, font=font(19, mono=True), fill=color)
        elif kind == "cmd":
            d.text((pad, y), text, font=font(19, mono=True), fill=color)
        else:
            d.text((pad, y), text, font=font(18, mono=True), fill=color)
        y += line_h
    return img


# --------------------------------------------------------------------------
# Generic visual pieces
# --------------------------------------------------------------------------
def logo(size: int = 200) -> Image.Image:
    """CyberSyn mark: shield + check, cream on transparent."""
    return icon_stroke("shield", size, ACCENT, width=1.6)


def diagram_arch(w=1500, h=760) -> Image.Image:
    """Browser <-> Flask <-> 3 scanners <-> provider, plus SQLite."""
    img, d = canvas(w, h, BG)
    # node geometry
    bw, bh = 250, 108
    fw, fh = 300, 118
    sw, sh = 300, 108
    pw, ph = 260, 108
    dw, dh = 230, 118

    def node(cx, cy, rw, rh, fill, outline, label, sub=None, icon_name=None):
        box = [cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2]
        rounded(d, box, 18, fill=fill, outline=outline, width=2)
        if icon_name:
            ic = icon_stroke(icon_name, 40, ACCENT)
            img.paste(ic, (int(cx - rw / 2 + 22), int(cy - 20)), ic)
            d.text((cx + 14, cy), label, font=font(28), fill=TEXT_STRONG, anchor="lm")
        else:
            d.text((cx, cy - (8 if sub else 0)), label, font=font(28), fill=TEXT_STRONG, anchor="mm")
        if sub:
            d.text((cx, cy + 26), sub, font=font(19), fill=TEXT_MUTED, anchor="mm")

    by = h * 0.36
    fy = h * 0.36
    sy = h * 0.36
    py = h * 0.36
    dy = h * 0.78

    node(170, by, bw, bh, SURFACE2, BORDER, "Browser", icon_name="menu")
    node(560, fy, fw, fh, SURFACE3, BORDER_STRONG, "Flask app", icon_name="settings")
    node(950, sy, sw, sh, SURFACE2, BORDER, "3 scanners", icon_name="shield")
    node(1320, py, pw, ph, SURFACE2, BORDER, "AI provider", icon_name="spark")
    node(560, dy, dw, dh, SURFACE2, BORDER, "SQLite", icon_name="download")

    def arrow(x0, y0, x1, y1, color=ACCENT_DEEP, width=3):
        d.line([(x0, y0), (x1, y1)], fill=color, width=width)
        ang = math.atan2(y1 - y0, x1 - x0)
        for a in (ang + math.radians(150), ang - math.radians(150)):
            d.line([(x1, y1), (x1 + 16 * math.cos(a), y1 + 16 * math.sin(a))], fill=color, width=width)

    arrow(296, by, 410, fy)
    arrow(410, by, 296, fy)
    arrow(710, fy, 800, sy)
    arrow(1090, sy, 1190, py)
    arrow(560, fy + fh / 2 + 6, 560, dy - dh / 2 - 6)
    d.text((430, by + 4), "HTTP", font=font(17), fill=TEXT_MUTED)
    d.text((1040, sy - 70), "LiteLLM", font=font(17), fill=TEXT_MUTED)
    return img


def flowchart_three(w=1500, h=820) -> Image.Image:
    """Prompt -> 3 scanners -> 4 outcomes."""
    img, d = canvas(w, h, BG)
    # prompt box
    rounded(d, [60, 90, 380, 200], 18, fill=SURFACE3, outline=BORDER_STRONG, width=2)
    d.text((220, 145), "prompt", font=font(30), fill=TEXT_STRONG, anchor="mm")
    d.text((220, 180), "from a member", font=font(19), fill=TEXT_MUTED, anchor="mm")

    scanners = [
        ("1", "Personal & Greek", "identifiers", "AFM · AMKA · IBAN", "#8d93a1"),
        ("2", "Company context", "confidential", "secrets · contracts · code", "#8d93a1"),
        ("3", "Prompt injection", "attack patterns", "override · obfuscation", "#8d93a1"),
    ]
    ys = [90, 330, 570]
    for (num, name, sub, det, col), y in zip(scanners, ys):
        rounded(d, [520, y, 900, y + 150], 18, fill=SURFACE2, outline=BORDER, width=2)
        d.ellipse([544, y + 34, 596, y + 86], fill=SURFACE4, outline=BORDER_STRONG, width=2)
        d.text((570, y + 60), num, font=font(26), fill=ACCENT, anchor="mm")
        d.text((620, y + 50), name, font=font(25), fill=TEXT_STRONG)
        d.text((620, y + 86), sub, font=font(18), fill=TEXT_MUTED)
        d.text((620, y + 114), det, font=font(17, mono=True), fill=TEXT_DIM)
        d.line([(380, 145), (520, y + 75)], fill=BORDER_STRONG, width=3)

    outcomes = [
        ("BLOCK", DANGER, "never sent"),
        ("WARN", WARN, "review first"),
        ("REDACT", ACCENT_DEEP, "masked, then sent"),
        ("ALLOW", SUCCESS, "sent as-is"),
    ]
    for i, (name, col, sub) in enumerate(outcomes):
        x = 1010 + i * 118
        rounded(d, [x, 300, x + 104, 470], 16, fill=SURFACE2, outline=col, width=2)
        d.text((x + 52, 352), name, font=font(19), fill=col, anchor="mm")
        d.text((x + 52, 400), sub, font=font(13), fill=TEXT_MUTED, anchor="mm")
        d.line([(900, 405), (x + 52, 405)], fill=col, width=2)
    return img


def shadow_map(w=1500, h=780) -> Image.Image:
    """Shadow AI: who is talking to which AI tool, from proxy/DNS logs."""
    img, d = canvas(w, h, BG)
    d.text((80, 70), "shadow AI", font=font(34), fill=TEXT_STRONG)
    d.text((80, 116), "the tools people use without asking", font=font(20), fill=TEXT_MUTED)
    # left: gateway
    rounded(d, [80, 300, 420, 440], 18, fill=SURFACE3, outline=BORDER_STRONG, width=2)
    d.text((250, 362), "CyberSyn", font=font(26), fill=TEXT_STRONG, anchor="mm")
    d.text((250, 398), "gateway", font=font(18), fill=TEXT_MUTED, anchor="mm")
    # right: tools
    tools = [("ChatGPT", "#97ab91"), ("Claude", "#bfa273"), ("Gemini", "#97ab91"),
             ("Copilot", "#bfa273"), ("DeepSeek", "#bd8a80"), ("Grok", "#bd8a80")]
    for i, (name, col) in enumerate(tools):
        x = 560 + (i % 3) * 300
        y = 220 + (i // 3) * 190
        rounded(d, [x, y, x + 260, y + 130], 18, fill=SURFACE2, outline=col, width=2)
        d.text((x + 130, y + 56), name, font=font(24), fill=TEXT_STRONG, anchor="mm")
        d.text((x + 130, y + 92), "unapproved", font=font(16), fill=col, anchor="mm")
    return img


def stat_bars(w=980, h=560, values=(62, 38, 27, 19, 12)) -> Image.Image:
    img, d = canvas(w, h, BG)
    d.text((70, 60), "blocks by reason", font=font(28), fill=TEXT_STRONG)
    base = h - 80
    for i, v in enumerate(values):
        x = 90 + i * 170
        bh = int((base - 140) * v / 100)
        col = [DANGER, WARN, ACCENT_DEEP, TEXT_DIM, TEXT_MUTED][i]
        rounded(d, [x, base - bh, x + 96, base], 10, fill=col)
        d.text((x + 48, base - bh - 26), f"{v}%", font=font(22), fill=TEXT_STRONG, anchor="mm")
        d.text((x + 48, base + 30), ["AFM", "AMKA", "code", "secrets", "inject"][i],
               font=font(17), fill=TEXT_MUTED, anchor="mm")
    return img


def logo_grid(w=1500, h=420) -> Image.Image:
    img, d = canvas(w, h, BG)
    names = ["OpenAI", "Anthropic", "Gemini", "OpenRouter", "Groq", "Mistral",
             "Together", "DeepSeek", "xAI", "Cohere", "Ollama", "OpenAI-compatible"]
    cols = 6
    cw, ch = w // cols, h // 2
    for i, name in enumerate(names):
        x = (i % cols) * cw
        y = (i // cols) * ch
        rounded(d, [x + 26, y + 26, x + cw - 26, y + ch - 26], 16, fill=SURFACE2, outline=BORDER, width=2)
        d.text((x + cw / 2, y + ch / 2), name, font=font(22), fill=TEXT_DIM, anchor="mm")
    return img


def big_number(num: str, label: str, w=1500, h=700) -> Image.Image:
    img, d = canvas(w, h, BG)
    d.text((w / 2, h / 2 - 50), num, font=font(230), fill=ACCENT, anchor="mm")
    d.text((w / 2, h / 2 + 100), label, font=font(26), fill=TEXT_MUTED, anchor="mm")
    return img


def check_row(items: list[str], w=1300, h=None, color=SUCCESS) -> Image.Image:
    h = h or 90 + 74 * len(items)
    img, d = canvas(w, h, BG)
    y = 54
    for it in items:
        ic = icon_stroke("check", 34, color)
        img.paste(ic, (60, y - 17), ic)
        d.text((120, y), it, font=font(27), fill=TEXT)
        y += 74
    return img


def screenshot_card(path: Path, w=1500) -> Image.Image:
    """Screenshot with a device frame and caption space."""
    shot = Image.open(path).convert("RGBA")
    sw, sh = shot.size
    scale = (w - 120) / sw
    nw, nh = int(sw * scale), int(sh * scale)
    shot = shot.resize((nw, nh), Image.LANCZOS)
    pad = 60
    title_h = 74
    img = Image.new("RGBA", (w, nh + pad * 2 + title_h), BG)
    d = ImageDraw.Draw(img)
    rounded(d, [pad - 14, title_h - 14, w - pad + 14, nh + pad + title_h + 14], 22,
            fill=SURFACE, outline=BORDER, width=2)
    img.paste(shot, (pad, title_h + pad - 14), shot)
    return img


def paste_icon(img, name, x, y, size, color):
    ic = icon_stroke(name, size, color)
    img.paste(ic, (int(x), int(y)), ic)


def section_slash(index: str, title: str, sub: str, w=1500, h=900) -> Image.Image:
    img, d = canvas(w, h, BG)
    d.rectangle([0, 0, 22, h], fill=ACCENT_DEEP)
    d.text((110, 330), index, font=font(150), fill=SURFACE4)
    d.text((110, 470), title, font=font(58), fill=TEXT_STRONG)
    d.text((110, 548), sub, font=font(23), fill=TEXT_MUTED)
    return img


def title_card(kicker: str, title: str, sub: str, w=1500, h=900) -> Image.Image:
    img, d = canvas(w, h, BG)
    ic = logo(190)
    img.paste(ic, (150, 200), ic)
    d.text((150, 420), kicker, font=font(22), fill=TEXT_MUTED)
    d.text((150, 470), title, font=font(76), fill=TEXT_STRONG)
    d.text((150, 560), sub, font=font(24), fill=TEXT_DIM)
    return img


ASSETS = {
    "logo.png": lambda: logo(240),
    "arch.png": lambda: diagram_arch(),
    "flow.png": lambda: flowchart_three(),
    "shadow.png": lambda: shadow_map(),
    "bars.png": lambda: stat_bars(),
    "providers.png": lambda: logo_grid(),
    "title.png": lambda: title_card(kicker="NETCOMPANY ATHENS HACKATHON 2026",
                                    title="CyberSyn",
                                    sub="an AI security gateway"),
    "sec_problem.png": lambda: section_slash(index="01", title="The problem",
                                             sub="shadow AI, and the data that walks out with it"),
    "sec_why.png": lambda: section_slash(index="02", title="Why local ML",
                                          sub="not regex, and not the cloud"),
    "sec_scanners.png": lambda: section_slash(index="03", title="Three scanners",
                                              sub="every prompt, locally, before it leaves"),
    "sec_run.png": lambda: section_slash(index="04", title="Running it",
                                         sub="Docker, or native"),
    "sec_backend.png": lambda: section_slash(index="05", title="Under the hood",
                                             sub="Flask, Gunicorn, SQLite, Fernet"),
    "sec_providers.png": lambda: section_slash(index="06", title="Bring your own model",
                                               sub="LiteLLM, twelve providers"),
    "sec_team.png": lambda: section_slash(index="07", title="How a team uses it",
                                          sub="administrators and members"),
    "sec_policy.png": lambda: section_slash(index="08", title="Four actions",
                                            sub="block, warn, redact, allow"),
    "sec_shadow.png": lambda: section_slash(index="09", title="Shadow AI discovery",
                                            sub="CSV, proxy and DNS logs"),
    "sec_stats.png": lambda: section_slash(index="10", title="Statistics and audit",
                                           sub="metadata, never message text"),
    "sec_proxy.png": lambda: section_slash(index="11", title="OpenAI-compatible proxy",
                                           sub="any client, one base URL"),
    "sec_security.png": lambda: section_slash(index="12", title="Security and privacy",
                                              sub="fail-closed by default"),
    "sec_extras.png": lambda: section_slash(index="13", title="And the extras",
                                            sub="bilingual, responsive, searchable"),
    "term_docker.png": lambda: terminal([
        ("cmd", "git clone https://github.com/JohannSSK/CyberSyn.git"),
        ("cmd", "cd CyberSyn"),
        ("cmd", "docker compose up --build"),
        ("out", "  [+] Building 41.2s"),
        ("out", "  [+] Running 2/2"),
        ("ok", "  ✔ Container cybersyn-app-1  Started"),
        ("dim", ""),
        ("accent", "→ http://localhost:5000"),
    ]),
    "term_native.png": lambda: terminal([
        ("cmd", "./setup.sh"),
        ("out", "==> 1. Looking for Python 3.11–3.13..."),
        ("out", "==> 2. .venv ready"),
        ("ok", "==> dependencies installed"),
        ("cmd", "./run.sh"),
        ("accent", "→ serving on http://localhost:5000"),
    ]),
    "term_seed.png": lambda: terminal([
        ("cmd", "./run.sh seed admin"),
        ("out", "administrator created"),
        ("ok", "done"),
    ]),
    "term_proxy.png": lambda: terminal([
        ("cmd", "curl http://localhost:5000/v1/chat/completions \\"),
        ("cmd", "  -H \"Authorization: Bearer <seat-token>\" \\"),
        ("cmd", "  -d '{\"model\":\"default\",\"messages\":[...]}'"),
        ("ok", "  200 OK"),
        ("out", "  screened · redacted · audited"),
    ]),
    "numbers.png": lambda: big_number("3", "local scanners, always on"),
}

if __name__ == "__main__":
    for name, fn in ASSETS.items():
        img = fn()
        img.save(OUT / name)
        print(f"{name:22s} {img.size[0]}x{img.size[1]}")
    for shot in sorted((ROOT / "SCREENSHOTS").glob("*.png")):
        out = OUT / f"shot_{shot.stem.lower().replace('-', '_')}.png"
        screenshot_card(shot).save(out)
        print(f"{out.name:22s} saved")
    print("done")
