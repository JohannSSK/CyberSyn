#!/usr/bin/env python3
"""Build the CyberSyn project deck (6 slides, 16:9) as a real .pptx.

Structure follows the example deck supplied with the brief:
cover -> problem -> how it works -> in action -> why it holds up -> stack + team + thanks.

Run:  .venv-deck/bin/python presentation/build_deck.py
      .venv-deck/bin/python presentation/build_deck.py --preview   # rough PNG proof
"""

from __future__ import annotations

import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt
from pptx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "CyberSyn_Project_Deck.pptx")

# --- palette, lifted from src/static/css/base.css -------------------------
BG = "1B1917"
SURFACE = "242220"
SURFACE_2 = "2C2A27"
SURFACE_3 = "33312E"
BORDER = "3F3D39"
BORDER_SOFT = "312F2C"
TEXT = "ECEBE7"
TEXT_STRONG = "FAFAF9"
DIM = "B3AEA6"
MUTED = "85817A"
SAGE = "97AB91"
WARN = "BFA273"
DANGER = "BD8A80"
ACCENT = "D9D5CD"

# soft fills (solid approximations of the app's alpha tints over BG)
SAGE_TINT = "232B23"
DANGER_TINT = "2A211E"
WARN_TINT = "2A2620"

SANS = "Inter"
SERIF = "Georgia"
MONO = "Consolas"

W, H = 13.333, 7.5
ML, MR = 0.85, 12.48

prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)

SPECS: list[list[dict]] = []  # display list for the PNG proof renderer


def rgb(hexstr: str) -> RGBColor:
    return RGBColor.from_string(hexstr)


def _track(run, points: float):
    """Letter-spacing, in points (python-pptx has no API for it)."""
    if points:
        run.font._rPr.set("spc", str(int(round(points * 100))))


def _noshadow(shape):
    shape.shadow.inherit = False


def rect(slide, i, x, y, w, h, fill, line=None, lw=0.75, radius=None, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius / min(w, h) if min(w, h) else radius
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(lw)
    _noshadow(s)
    if s.has_text_frame:
        s.text_frame.text = ""
    SPECS[i].append(dict(k="rect", x=x, y=y, w=w, h=h, fill=fill, line=line, lw=lw,
                         radius=radius or 0, shape="round" if shape == MSO_SHAPE.ROUNDED_RECTANGLE else "rect"))
    return s


def line(slide, i, x1, y1, x2, y2, color=BORDER, lw=1.0, arrow=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(lw)
    if arrow:
        ln = c.line._get_or_add_ln()
        tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
        ln.append(tail)
    SPECS[i].append(dict(k="line", x1=x1, y1=y1, x2=x2, y2=y2, color=color, lw=lw, arrow=arrow))
    return c


def text(slide, i, x, y, w, h, paras, anchor="top", margins=(0, 0, 0, 0), wrap=True):
    """paras: list of dicts: runs=[(txt, style)], align, space_after, line_spacing, space_before.

    style keys: size, color, bold, italic, font, tracking, caps.
    """
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.margin_left, tf.margin_right, tf.margin_top, tf.margin_bottom = [Inches(m) for m in margins]
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}[anchor]

    for pi, para in enumerate(paras):
        p = tf.paragraphs[0] if pi == 0 else tf.add_paragraph()
        p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                       "right": PP_ALIGN.RIGHT}[para.get("align", "left")]
        if para.get("space_after") is not None:
            p.space_after = Pt(para["space_after"])
        if para.get("space_before") is not None:
            p.space_before = Pt(para["space_before"])
        ls = para.get("line_spacing")
        if ls:
            p.line_spacing = ls
        for txt, st in para["runs"]:
            r = p.add_run()
            r.text = txt.upper() if st.get("caps") else txt
            f = r.font
            f.name = st.get("font", SANS)
            f.size = Pt(st.get("size", 12))
            f.bold = st.get("bold", False)
            f.italic = st.get("italic", False)
            f.color.rgb = rgb(st.get("color", TEXT))
            _track(r, st.get("tracking", 0))
            if st.get("font") == MONO:
                # keep code snippets from inheriting theme kerning quirks
                pass
    SPECS[i].append(dict(k="text", x=x, y=y, w=w, h=h, paras=paras, anchor=anchor))
    return box


def P(txt, size=12, color=TEXT, bold=False, italic=False, font=SANS,
      tracking=0, caps=False, align="left", space_after=None, line_spacing=None,
      space_before=None):
    style = dict(size=size, color=color, bold=bold, italic=italic, font=font,
                 tracking=tracking, caps=caps)
    return dict(runs=[(txt, style)], align=align, space_after=space_after,
                line_spacing=line_spacing, space_before=space_before)


def runs_para(runs, align="left", space_after=None, line_spacing=None, space_before=None):
    return dict(runs=runs, align=align, space_after=space_after,
                line_spacing=line_spacing, space_before=space_before)


# --- text measuring for chips / overflow sanity ---------------------------
from PIL import ImageFont

_FONTS = {
    ("sans", False): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ("sans", True): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ("serif", True): "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ("serif", False): "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ("mono", False): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ("mono", True): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
}
_cache: dict = {}


def _font(family, bold, px):
    kind = "mono" if family == MONO else ("serif" if family == SERIF else "sans")
    key = (kind, bold, px)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(_FONTS[(kind, bold)], px)
    return _cache[key]


def text_width(txt, size, family=SANS, bold=False, tracking=0):
    """Width in inches, approximated with DejaVu at 96 dpi."""
    px = max(1, int(round(size * 96 / 72)))
    f = _font(family, bold, px)
    w = f.getlength(txt) / 96.0
    w += tracking / 72.0 * max(0, len(txt) - 1)
    return w


def chip(slide, i, x, y, label, color=DIM, fill=SURFACE_2, border=BORDER_SOFT,
         size=8.5, pad=0.16, h=0.28, bold=False, tracking=0.02, font=MONO):
    w = text_width(label.upper(), size, font, bold, tracking) + 2 * pad
    rect(slide, i, x, y, w, h, fill, border, 0.75, radius=0.10, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(slide, i, x, y, w, h,
         [P(label, size=size, color=color, bold=bold, font=font, tracking=tracking, caps=True, align="center")],
         anchor="middle")
    return w


def chrome(slide, i, page, eyebrow=None, title=None, lede=None, lede_w=8.2,
           title_size=28, title_w=11.6, title_top=1.02, lede_top=1.62):
    rect(slide, i, -0.1, -0.1, W + 0.2, H + 0.2, BG)
    if eyebrow:
        rect(slide, i, ML, 0.755, 0.075, 0.075, SAGE)
        text(slide, i, ML + 0.19, 0.69, 7.6, 0.24,
             [P(eyebrow, size=9, color=DIM, font=MONO, tracking=0.16, caps=True)])
    if title:
        text(slide, i, ML, title_top, title_w, 0.52,
             [P(title, size=title_size, color=TEXT_STRONG, bold=True, line_spacing=1.0)])
    if lede:
        text(slide, i, ML, lede_top, lede_w, 0.66,
             [P(lede, size=12, color=DIM, line_spacing=1.24)])
    # footer
    rect(slide, i, ML, 6.99, MR - ML, 0.008, BORDER_SOFT)
    text(slide, i, ML, 7.09, 6.0, 0.22,
         [P("CYBERSYN  ·  AI SECURITY GATEWAY", size=7.5, color=MUTED, font=MONO, tracking=0.14)])
    text(slide, i, MR - 1.4, 7.09, 1.4, 0.22,
         [P(f"{page:02d} / 06", size=7.5, color=MUTED, font=MONO, tracking=0.14, align="right")])


def notes(slide, txt):
    slide.notes_slide.notes_text_frame.text = txt


def blank(i):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    SPECS.append([])
    return s


# =========================================================================
# 1 — COVER
# =========================================================================
i = 0
s = blank(i)
rect(s, i, -0.1, -0.1, W + 0.2, H + 0.2, BG)

# faint dot grid, right half
for gx in range(0, 10):
    for gy in range(0, 9):
        rect(s, i, 7.55 + gx * 0.52, 1.05 + gy * 0.52, 0.018, 0.018, "2E2C29")

# top chrome
s.shapes.add_picture(os.path.join(os.path.dirname(HERE), "assets/icons/shield.png"),
                     Inches(ML), Inches(0.72), height=Inches(0.34))
text(s, i, ML + 0.46, 0.745, 3.0, 0.25,
     [P("CYBERSYN", size=9.5, color=TEXT, font=MONO, tracking=0.26)])
text(s, i, 9.2, 0.745, 3.28, 0.25,
     [P("NETCOMPANY HACKATHON ATHENS 2026", size=8.5, color=MUTED, font=MONO,
        tracking=0.1, align="right", caps=True)])

# eyebrow chip
chip(s, i, ML, 1.62, "Challenge 3 · Shadow AI & data protection", color=SAGE, fill=SAGE_TINT,
     border="39443A", size=8.5, h=0.32, tracking=0.06)

# title: serif italic + bold sans
text(s, i, ML - 0.03, 2.06, 6.6, 1.45,
     [runs_para([("Cyber", dict(size=78, color=TEXT_STRONG, italic=True, font=SERIF)),
                 ("Syn", dict(size=78, color=TEXT_STRONG, bold=True, font=SANS))],
                line_spacing=0.92)])

rect(s, i, ML, 3.62, 1.15, 0.035, SAGE)

text(s, i, ML, 3.92, 5.9, 0.95,
     [P("The gate every AI prompt passes through.", size=23, color=TEXT, line_spacing=1.06)])

text(s, i, ML, 4.86, 5.75, 1.1,
     [P("Shadow-AI protection and data privacy for teams. Every prompt is screened "
        "on your own machine — before it ever reaches the model.", size=12.5, color=DIM,
        line_spacing=1.32)])

text(s, i, ML, 6.12, 5.9, 0.25,
     [P("LOCAL-FIRST      FAIL-CLOSED      AUDITABLE", size=8.5, color=ACCENT,
        font=MONO, tracking=0.16)])

# right panel — screening path
px, py, pw, ph = 7.55, 1.8, 4.6, 4.42
rect(s, i, px, py, pw, ph, SURFACE, BORDER_SOFT, 1.0, radius=0.18, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, px + 0.32, py + 0.26, 3.6, 0.22,
     [P("THE SCREENING PATH", size=8, color=MUTED, font=MONO, tracking=0.16)])

# prompt card
cx, cy, cw = px + 0.32, py + 0.62, pw - 0.64
rect(s, i, cx, cy, cw, 0.78, SURFACE_2, BORDER, 0.75, radius=0.10, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, cx + 0.2, cy + 0.13, cw - 0.4, 0.5,
     [P("PROMPT  ·  09:41", size=7, color=MUTED, font=MONO, tracking=0.12),
      P("\u201cΑΦΜ 123456789 — fix this invoice\u201d", size=9, color=TEXT, font=MONO)])

line(s, i, px + pw / 2, cy + 0.78, px + pw / 2, cy + 0.98, BORDER, 1.0, arrow=True)

gates = [("01", "PII & Greek IDs", DIM), ("02", "Confidential context", DIM), ("03", "Prompt injection", DANGER)]
gy = cy + 0.98
for n, label, col in gates:
    rect(s, i, cx, gy, cw, 0.52, SURFACE_2, col if col == DANGER else BORDER_SOFT, 1.0,
         radius=0.09, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, i, cx + 0.2, gy, 0.42, 0.52, [P(n, size=8, color=MUTED, font=MONO)], anchor="middle")
    text(s, i, cx + 0.62, gy, cw - 1.1, 0.52, [P(label, size=10, color=TEXT, bold=True)], anchor="middle")
    text(s, i, cx + cw - 0.62, gy, 0.5, 0.52,
         [P("PASS" if col != DANGER else "HIT", size=6.5, color=SAGE if col != DANGER else DANGER,
            font=MONO, tracking=0.1, align="right")], anchor="middle")
    gy += 0.64

line(s, i, px + pw / 2, gy - 0.12, px + pw / 2, gy + 0.08, DANGER, 1.0, arrow=True)
rect(s, i, cx, gy + 0.08, cw, 0.62, DANGER_TINT, "5A4038", 1.0, radius=0.10, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, cx + 0.2, gy + 0.08, cw - 0.4, 0.62,
     [P("BLOCKED  ·  line 4  ·  AFM", size=8.5, color=DANGER, font=MONO, tracking=0.08),
      P("reason shown  ·  decision logged", size=7.5, color=MUTED, font=MONO)], anchor="middle")

text(s, i, ML, 6.62, 6.2, 0.25,
     [P("Flask  ·  spaCy EN/EL  ·  distilbart-MNLI  ·  LiteLLM", size=8.5, color=MUTED, font=MONO,
        tracking=0.04)])
text(s, i, MR - 1.4, 7.09, 1.4, 0.22,
     [P("01 / 06", size=7.5, color=MUTED, font=MONO, tracking=0.14, align="right")])

notes(s, "CyberSyn is our answer to the challenge: employees paste code, contracts and customer data "
         "into public AI tools, and nobody can see it. CyberSyn sits between the person and the model, "
         "screens every prompt on the machine that runs it, and either forwards it or blocks it with an "
         "explanation. This deck walks the process: the problem, the three gates, one request end to end, "
         "the rules that make it trustworthy, and what it is built on.")

# =========================================================================
# 2 — PROBLEM
# =========================================================================
i = 1
s = blank(i)
chrome(s, i, 2, eyebrow="01 — the problem",
       title="Shadow AI is already inside the building.",
       lede="Code, contracts and client data go into public chat tools every day — usually without IT "
            "knowing, and always without a record of what left.",
       lede_w=7.4, title_w=9.9, title_top=1.0, lede_top=1.58)

cards = [
    ("PROMPT 01", "\u201cFix the ΑΦΜ 123456789 on this client invoice\u201d", "PERSONAL IDENTIFIER",
     "Greek tax ID, unvalidated, now in someone else's inference logs."),
    ("PROMPT 02", "\u201cconnect with password=Hunter2! to prod-db\u201d", "CREDENTIAL",
     "A live credential, pasted to debug a connection string."),
    ("PROMPT 03", "\u201csummarise clause 7 of the NDA for the client\u201d", "CONFIDENTIAL CONTEXT",
     "Client contract text, sent to a model with unknown retention."),
]
cw, gap = 3.56, 0.28
for n, (tag, prompt, cat, desc) in enumerate(cards):
    x = ML + n * (cw + gap)
    y = 2.62
    rect(s, i, x, y, cw, 2.25, SURFACE, BORDER_SOFT, 1.0, radius=0.16, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, i, x + 0.28, y + 0.26, cw - 0.56, 0.22,
         [P(tag, size=7.5, color=MUTED, font=MONO, tracking=0.16)])
    text(s, i, x + 0.28, y + 0.56, cw - 0.56, 1.0,
         [P(prompt, size=9.5, color=TEXT, font=MONO, line_spacing=1.28)])
    chip(s, i, x + 0.28, y + 1.44, cat, color=DANGER, fill=DANGER_TINT, border="4A352F",
         size=7, pad=0.12, h=0.24, tracking=0.08)
    text(s, i, x + 0.28, y + 1.76, cw - 0.56, 0.36,
         [P(desc, size=8.5, color=MUTED, line_spacing=1.12)])

# stat row
sy = 5.22
rect(s, i, ML, sy, MR - ML, 0.008, BORDER_SOFT)
stats = [
    ("0", "visibility for IT into what was pasted"),
    ("1 paste", "is all it takes to move client data out"),
    ("3", "hand-offs: device → provider → unknown retention"),
]
for n, (num, desc) in enumerate(stats):
    x = ML + n * 3.9
    text(s, i, x, sy + 0.2, 3.6, 0.62, [P(num, size=34, color=TEXT_STRONG, bold=True, line_spacing=0.95)])
    text(s, i, x, sy + 0.82, 3.4, 0.5, [P(desc, size=9.5, color=DIM, line_spacing=1.2)])

notes(s, "The problem is not that people are careless; it is that the helpful path is the unsafe one. "
         "Three real examples of prompts we screen: a Greek tax ID, a database password, a contract clause. "
         "Each is a normal thing to ask an assistant, and each is a data transfer nobody approved. "
         "IT has zero visibility, one paste is enough, and the data changes hands three times before "
         "anyone could notice.")

# =========================================================================
# 3 — HOW IT WORKS (three gates)
# =========================================================================
i = 2
s = blank(i)
chrome(s, i, 3, eyebrow="02 — how it works",
       title="One prompt. Three gates. No leaks.",
       lede="Cheap, precise rules fire first; a local classifier only reads the lines the rules could not "
            "explain. Every verdict names its stage, its line and its reason.",
       lede_w=8.4)

# input / output labels
text(s, i, ML, 2.36, 3.0, 0.22,
     [P("IN  ·  MEMBER PROMPT", size=7.5, color=SAGE, font=MONO, tracking=0.14)])
text(s, i, MR - 3.0, 2.36, 3.0, 0.22,
     [P("OUT  ·  MODEL ANSWER", size=7.5, color=SAGE, font=MONO, tracking=0.14, align="right")])

stages = [
    ("01", "PII & Greek IDs", ["AFM + checksum", "AMKA · phones", "Names EN / EL", "Keys · IBAN"],
     "regex + spaCy NER"),
    ("02", "Confidential context", ["Contracts & NDAs", "Financials · payroll", "Credentials", "Source code"],
     "rules + zero-shot MNLI"),
    ("03", "Prompt injection", ["Instruction override", "Payloads in comments", "Multi-line merge", "Jailbreak phrasing"],
     "regex + zero-shot MNLI"),
]
cw, gap = 3.52, 0.34
cy, ch = 2.64, 2.22
for n, (num, name, chips, tech) in enumerate(stages):
    x = ML + n * (cw + gap)
    rect(s, i, x, cy, cw, ch, SURFACE, BORDER_SOFT, 1.0, radius=0.16, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, i, x + 0.28, cy + 0.24, 0.6, 0.4, [P(num, size=17, color=SAGE, font=MONO, tracking=0.06)])
    text(s, i, x + 0.28, cy + 0.68, cw - 0.56, 0.28, [P(name, size=13.5, color=TEXT_STRONG, bold=True)])
    # chips, two per row
    cxp, cyp = x + 0.28, cy + 1.08
    for cn, label in enumerate(chips):
        if cn % 2 == 0 and cn:
            cxp = x + 0.28
            cyp += 0.33
        cxp += chip(s, i, cxp, cyp, label, color=DIM, fill=SURFACE_2, border=BORDER_SOFT,
                    size=6.8, pad=0.11, h=0.25, tracking=0.04) + 0.08

    text(s, i, x + 0.28, cy + ch - 0.4, cw - 0.56, 0.22,
         [P(tech, size=7.5, color=MUTED, font=MONO, tracking=0.04)])
    if n < 2:
        line(s, i, x + cw + 0.06, cy + ch / 2, x + cw + gap - 0.03, cy + ch / 2, MUTED, 1.2, arrow=True)

# verdict bands
by, bh = 5.06, 1.34
lw_ = 7.45
rect(s, i, ML, by, lw_, bh, DANGER_TINT, "4A352F", 1.0, radius=0.14, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, ML + 0.3, by + 0.22, lw_ - 0.6, 0.24,
     [P("ANY GATE FIRES  →  BLOCKED BEFORE SEND", size=8.5, color=DANGER, font=MONO, tracking=0.12)])
text(s, i, ML + 0.3, by + 0.54, lw_ - 0.6, 0.6,
     [P("stage · cause · line · offset · snippet returned to the member, written to BLOCK_LOG "
        "and attributed.", size=10.5, color=TEXT, line_spacing=1.25)])

rx = ML + lw_ + 0.28
rw = MR - rx
rect(s, i, rx, by, rw, bh, SAGE_TINT, "36423A", 1.0, radius=0.14, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, rx + 0.28, by + 0.22, rw - 0.56, 0.24,
     [P("ALL CLEAR  →  FORWARDED", size=8.5, color=SAGE, font=MONO, tracking=0.12)])
text(s, i, rx + 0.28, by + 0.54, rw - 0.56, 0.6,
     [P("via LiteLLM to the chosen provider; the exchange is saved to chat history.",
        size=10.5, color=TEXT, line_spacing=1.25)])

text(s, i, ML, 6.62, 9.5, 0.24,
     [P("FAIL CLOSED — a scanner that crashes, times out (60 s) or prints no verdict blocks the request.",
        size=8.5, color=MUTED, font=MONO, tracking=0.02)])

notes(s, "This is the heart of the product. Gate one handles personal data, including Greek identifiers — "
         "AFM with checksum validation, AMKA, phone numbers, and person names in both English and Greek "
         "with two spaCy models. Gate two looks for confidential company context: contracts, financials, "
         "credentials, source code. Gate three catches prompt injection, including attacks split across "
         "code comments, which we merge before classifying. Rules run first because they are cheap and "
         "precise; the zero-shot model only sees what the rules could not explain. A hit stops the prompt "
         "before it is sent, and if the scanner itself fails, we refuse rather than forward.")

# =========================================================================
# 4 — IN ACTION
# =========================================================================
i = 3
s = blank(i)
chrome(s, i, 4, eyebrow="03 — in action",
       title="From keystroke to verdict, inside one request.",
       lede="No generic refusal: the member sees the exact line, the rule that fired, and a way forward.",
       lede_w=8.0)

# chat mock
mx, my, mw, mh = ML, 2.42, 7.5, 4.1
rect(s, i, mx, my, mw, mh, SURFACE, BORDER_SOFT, 1.0, radius=0.16, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
rect(s, i, mx, my, mw, 0.46, SURFACE_2, None, radius=0.16, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
rect(s, i, mx, my + 0.2, mw, 0.26, SURFACE_2, None)
for d in range(3):
    rect(s, i, mx + 0.24 + d * 0.16, my + 0.19, 0.07, 0.07, BORDER, None,
         shape=MSO_SHAPE.OVAL)
text(s, i, mx + 0.85, my, 3.4, 0.46, [P("CyberSyn · workspace", size=8.5, color=DIM, font=MONO)],
     anchor="middle")
text(s, i, mx + mw - 2.6, my, 2.36, 0.46,
     [P("screening on host", size=7.5, color=SAGE, font=MONO, tracking=0.08, align="right")],
     anchor="middle")

# user bubble
ux, uy, uw, uh = mx + 2.62, my + 0.7, 4.62, 0.86
rect(s, i, ux, uy, uw, uh, SURFACE_3, BORDER, 0.75, radius=0.12, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, ux + 0.02, uy + 0.02, uw - 0.04, uh - 0.04,
     [P("\u201cRefresh the invoice for ΑΦΜ 123456789", size=8.5, color=TEXT, font=MONO,
        line_spacing=1.3, align="right"),
      P("and send it to the model.\u201d", size=8.5, color=TEXT, font=MONO,
        line_spacing=1.3, align="right")],
     anchor="middle", margins=(0.18, 0.18, 0, 0))

# block card
bx, by, bw, bh = mx + 0.26, my + 1.78, mw - 0.52, 1.9
rect(s, i, bx, by, bw, bh, DANGER_TINT, "4A352F", 1.0, radius=0.12, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
rect(s, i, bx, by + 0.12, 0.05, bh - 0.24, DANGER, None)
text(s, i, bx + 0.28, by + 0.2, bw - 0.56, 0.24,
     [P("BLOCKED  ·  CHECK 1 — PERSONAL IDENTIFIERS", size=8.5, color=DANGER, font=MONO, tracking=0.1)])
text(s, i, bx + 0.28, by + 0.52, bw - 0.56, 0.26,
     [P("Greek tax ID (AFM)  ·  checksum matched  ·  strict policy", size=8, color=DIM, font=MONO)])
text(s, i, bx + 0.28, by + 0.84, bw - 0.56, 0.34,
     [runs_para([("\u2026 invoice for ΑΦΜ ", dict(size=10, color=TEXT, font=MONO)),
                 ("123456789", dict(size=10, color=DANGER, font=MONO, bold=True)),
                 (" \u2192 send \u2026", dict(size=10, color=TEXT, font=MONO))])])
cxp = bx + 0.28
for label in ["GREEK_AFM", "LINE 4  ·  OFFSET 21", "SCORE 0.92"]:
    cxp += chip(s, i, cxp, by + 1.28, label, color=MUTED, fill="332B28", border="4A3D38",
                size=6.8, pad=0.11, h=0.24, tracking=0.06) + 0.08
text(s, i, bx + bw - 1.62, by + 1.66, 1.34, 0.22,
     [P("Nothing was sent.", size=8, color=SAGE, font=MONO, align="right")])

# steps
steps = [
    ("01", "Authenticate", "The member's own session token; policy and checks resolved for them."),
    ("02", "Screen locally", "Three scanners, separate processes, 60 s cap, fail closed."),
    ("03", "Explain or forward", "A block with line, snippet and stage — or a clean send to the provider."),
    ("04", "Log & attribute", "Stage, reason, member, timestamp. No prompt text for overrides."),
]
sx = 8.68
sy = 2.42
for n, (num, name, body) in enumerate(steps):
    y = sy + n * 1.03
    text(s, i, sx, y + 0.02, 0.42, 0.24, [P(num, size=8.5, color=SAGE, font=MONO, tracking=0.08)])
    text(s, i, sx + 0.5, y, 3.3, 0.26, [P(name, size=12, color=TEXT_STRONG, bold=True)])
    text(s, i, sx + 0.5, y + 0.3, 3.28, 0.55, [P(body, size=9, color=DIM, line_spacing=1.2)])
    if n < 3:
        rect(s, i, sx + 0.5, y + 0.94, MR - sx - 0.5, 0.006, BORDER_SOFT)

text(s, i, sx, 6.55, 3.85, 0.22,
     [P("Interface shown is illustrative.", size=7.5, color=MUTED, font=MONO, tracking=0.02)])

notes(s, "One request, end to end. The member writes a normal message. The browser posts it with their "
         "session token. The server resolves their policy, runs the enabled scanners as separate processes, "
         "and gets JSON back. If gate one hits, the UI shows this card: check, category, line, offset, the "
         "snippet itself, and the option to ask an administrator for an override. The prompt never reaches "
         "the provider, and the block is written to the audit log with the member and the stage. If "
         "everything passes, the answer comes back and the exchange is saved to chat history.")

# =========================================================================
# 5 — WHY IT HOLDS UP
# =========================================================================
i = 4
s = blank(i)
chrome(s, i, 5, eyebrow="04 — why it holds up",
       title="Four rules we refused to break.",
       lede="What makes a gateway trustworthy rather than just another blocker in the way.",
       lede_w=8.0, title_w=8.6)

principles = [
    ("01", "Local first", "Scanning runs on the machine serving CyberSyn. No third-party DLP sees the "
                          "prompt — that would only move the leak."),
    ("02", "Fail closed", "A scanner that crashes, times out or prints nothing parseable refuses the "
                          "request. A broken gate is never an open gate."),
    ("03", "Explain, don't just block", "Every block names the stage, category, line, offsets and "
                                       "snippet, so people learn the rule instead of fighting it."),
    ("04", "Humans stay in control", "An administrator can approve a real exception — verified "
                                     "server-side and recorded in the audit trail, attributed."),
]
cw, ch = 5.69, 1.34
for n, (num, name, body) in enumerate(principles):
    col = n % 2
    row = n // 2
    x = ML + col * (cw + 0.25)
    y = 2.34 + row * (ch + 0.24)
    rect(s, i, x, y, cw, ch, SURFACE, BORDER_SOFT, 1.0, radius=0.14, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, i, x + 0.3, y + 0.22, 0.4, 0.22, [P(num, size=8, color=SAGE, font=MONO, tracking=0.08)])
    text(s, i, x + 0.72, y + 0.18, cw - 1.0, 0.3, [P(name, size=13.5, color=TEXT_STRONG, bold=True)])
    text(s, i, x + 0.72, y + 0.58, cw - 1.02, 0.85, [P(body, size=9.5, color=DIM, line_spacing=1.28)])

# proof strip
sy = 5.8
rect(s, i, ML, sy, MR - ML, 0.5, SURFACE_2, BORDER_SOFT, 1.0, radius=0.10,
     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, ML, sy, MR - ML, 0.5,
     [runs_para([("21 authorisation tests    ·    ", dict(size=8.5, color=DIM, font=MONO, tracking=0.04)),
                 ("EN / EL interface", dict(size=8.5, color=DIM, font=MONO, tracking=0.04)),
                 ("    ·    Fernet-encrypted keys    ·    SHA-256 session hashes    ·    ",
                  dict(size=8.5, color=DIM, font=MONO, tracking=0.04)),
                 ("0 prompts inspected by a third party", dict(size=8.5, color=SAGE, font=MONO, tracking=0.04))],
                align="center")],
     anchor="middle")

text(s, i, ML, 6.55, 9.8, 0.22,
     [P("Evidence: tools/test_auth.py  ·  README → Security & privacy design", size=7.5,
        color=MUTED, font=MONO, tracking=0.04)])

notes(s, "Four decisions define the product. Local first: if we shipped prompts to a cloud DLP, we would "
         "have moved the leak, not closed it. Fail closed: an unavailable scanner is a refusal, because a "
         "gate that silently opens is worse than no gate. Explain: the reason is part of the response, "
         "which is why people correct the prompt instead of retrying. And humans stay in control: an "
         "administrator can release a genuine exception, with their session checked on the server and the "
         "override attributed in the log. The strip underneath is the evidence: authorisation tests, "
         "bilingual UI, encrypted keys, hashed sessions, and nothing inspected off-box.")

# =========================================================================
# 6 — STACK + TEAM + THANKS
# =========================================================================
i = 5
s = blank(i)
chrome(s, i, 6, eyebrow="05 — under the hood",
       title="Boring where it counts. Sharp where it shows.",
       title_w=11.2, lede=None)

groups = [
    ("SCREENING", ["spaCy en + el", "distilbart-mnli", "PyTorch", "bilingual rules"]),
    ("PLATFORM", ["Flask", "SQLite", "LiteLLM", "Docker"]),
    ("TRUST", ["Fernet keys", "Werkzeug hashes", "SHA-256 sessions", "EN / EL UI"]),
]
gy = 2.18
for label, items in groups:
    text(s, i, ML, gy, 1.9, 0.22, [P(label, size=7.5, color=MUTED, font=MONO, tracking=0.16)])
    cxp = ML
    for item in items:
        w = text_width(item.upper(), 8, MONO, False, 0.03) + 0.3
        if cxp + w > 6.35:
            cxp = ML
            gy += 0.36
        chip(s, i, cxp, gy + 0.28, item, color=TEXT, fill=SURFACE, border=BORDER,
             size=8, pad=0.15, h=0.32, tracking=0.03)
        cxp += w + 0.1
    gy += 0.82

text(s, i, ML, 4.92, 5.6, 0.26,
     [runs_para([("$ ", dict(size=9, color=SAGE, font=MONO)),
                 ("docker compose up --build", dict(size=9, color=DIM, font=MONO)),
                 ("   one command, no external database", dict(size=8.5, color=MUTED, font=MONO))])])

# team panel
tx, ty, tw, th = 7.35, 2.18, MR - 7.35, 3.1
rect(s, i, tx, ty, tw, th, SURFACE, BORDER_SOFT, 1.0, radius=0.16, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
text(s, i, tx + 0.3, ty + 0.26, tw - 0.6, 0.22,
     [P("TEAM CYBERSYN", size=8, color=MUTED, font=MONO, tracking=0.16)])
roles = [
    ("Machine learning & security", "Scanners, thresholds, evaluation harness"),
    ("Backend & platform", "Auth, encryption, provider routing, Docker"),
    ("Product & front-end", "Bilingual UI, chat history, team dashboard"),
]
for n, (role, body) in enumerate(roles):
    y = ty + 0.68 + n * 0.78
    rect(s, i, tx + 0.3, y + 0.06, 0.05, 0.5, SAGE if n == 0 else BORDER, None)
    text(s, i, tx + 0.52, y, tw - 0.8, 0.26, [P(role, size=11, color=TEXT_STRONG, bold=True)])
    text(s, i, tx + 0.52, y + 0.28, tw - 0.8, 0.3, [P(body, size=8.5, color=MUTED, line_spacing=1.1)])

# closing
rect(s, i, ML, 5.72, MR - ML, 0.008, BORDER_SOFT)
text(s, i, ML, 5.95, 5.8, 0.85,
     [runs_para([("Thank you", dict(size=40, color=TEXT_STRONG, italic=True, font=SERIF)),
                 (".", dict(size=40, color=SAGE, bold=True))], line_spacing=0.95)])
text(s, i, ML, 6.62, 6.4, 0.24,
     [P("Questions & discussion", size=11, color=DIM)])

text(s, i, 8.6, 6.12, 3.88, 0.7,
     [P("github.com/JohannSSK/CyberSyn", size=9, color=TEXT, font=MONO, align="right"),
      P("Netcompany Hackathon Athens 2026 · Challenge 3", size=8, color=MUTED, font=MONO, align="right")])

notes(s, "Under the hood: three scanners built on spaCy for English and Greek names and a distilled "
         "BART zero-shot classifier, with PyTorch and curated bilingual rules. Flask and SQLite on the "
         "platform side, LiteLLM for bring-your-own-model, Docker for one-command deployment. Trust is "
         "engineering too: Fernet-encrypted provider keys, Werkzeug password hashes, SHA-256 session "
         "hashes. The team split across ML and security, backend and platform, and product and "
         "front-end. Thank you — happy to take questions, or show a live block.")

prs.save(OUT)
print("wrote", OUT, f"({os.path.getsize(OUT)/1024:.0f} KB, {len(prs.slides.__iter__.__self__._sldIdLst)} slides)")

# =========================================================================
# rough PNG proof (not shipped) — catches overflow and collisions
# =========================================================================
if "--preview" in sys.argv:
    from PIL import Image, ImageDraw

    SC = 96  # px per inch
    os.makedirs(os.path.join(HERE, "_preview"), exist_ok=True)
    wrap_warnings: list[str] = []

    def hexrgb(h):
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))

    def pil_font(family, bold, italic, size):
        kind = "mono" if family == MONO else ("serif" if family == SERIF else "sans")
        px = max(6, int(round(size * SC / 72)))
        key = (kind, bold, px, italic)
        if key not in _cache:
            path = _FONTS[(kind, bold)]
            _cache[key] = ImageFont.truetype(path, px)
        return _cache[key]

    def wrap(txt, font, maxw):
        out, linebuf = [], ""
        for word in txt.split(" "):
            trial = word if not linebuf else linebuf + " " + word
            if font.getlength(trial) <= maxw * SC or not linebuf:
                linebuf = trial
            else:
                out.append(linebuf)
                linebuf = word
        out.append(linebuf)
        return out

    for idx, spec in enumerate(SPECS):
        img = Image.new("RGB", (int(W * SC), int(H * SC)), hexrgb(BG))
        d = ImageDraw.Draw(img)
        for el in spec:
            if el["k"] == "rect":
                box = [el["x"] * SC, el["y"] * SC, (el["x"] + el["w"]) * SC, (el["y"] + el["h"]) * SC]
                fill = hexrgb(el["fill"]) if el["fill"] else None
                outline = hexrgb(el["line"]) if el["line"] else None
                if el["shape"] == "round":
                    d.rounded_rectangle(box, radius=min(el["w"], el["h"]) * SC * 0.25,
                                        fill=fill, outline=outline, width=max(1, int(el["lw"])))
                elif el["w"] < 0.04 and el["h"] < 0.04:
                    d.ellipse(box, fill=fill)
                else:
                    d.rectangle(box, fill=fill, outline=outline, width=max(1, int(el["lw"])))
            elif el["k"] == "line":
                d.line([el["x1"] * SC, el["y1"] * SC, el["x2"] * SC, el["y2"] * SC],
                       fill=hexrgb(el["color"]), width=max(1, int(el["lw"])))
            elif el["k"] == "text":
                # compute block height first for vertical anchoring
                rendered = []
                for para in el["paras"]:
                    runs = para["runs"]
                    style0 = runs[0][1]
                    size = max(r[1].get("size", 12) for r in runs)
                    fnt = pil_font(style0.get("font", SANS), style0.get("bold", False),
                                   style0.get("italic", False), size)
                    plain = "".join(r[0] for r in runs)
                    lines = wrap(plain, fnt, el["w"])
                    lh = size * 1.32 * SC / 72
                    rendered.append((para, runs, fnt, lines, lh))
                total = sum(len(r[3]) * r[4] for r in rendered)
                y = el["y"] * SC
                if total > el["h"] * SC + 2:
                    wrap_warnings.append(f"slide {idx+1}: text overflow {total/SC:.2f}in > box {el['h']:.2f}in :: {plain[:50]}")
                if el["anchor"] == "middle":
                    y += (el["h"] * SC - total) / 2
                elif el["anchor"] == "bottom":
                    y += el["h"] * SC - total
                for para, runs, fnt, lines, lh in rendered:
                    align = para.get("align", "left")
                    for ln in lines:
                        tw_ = fnt.getlength(ln)
                        x = el["x"] * SC
                        if align == "center":
                            x += (el["w"] * SC - tw_) / 2
                        elif align == "right":
                            x += el["w"] * SC - tw_
                        color = hexrgb(runs[0][1].get("color", TEXT))
                        d.text((x, y), ln, font=fnt, fill=color)
                        y += lh
        img.save(os.path.join(HERE, "_preview", f"slide{idx+1}.png"))
    for w in wrap_warnings:
        print("WARN", w)
    print("previews ->", os.path.join(HERE, "_preview"))
