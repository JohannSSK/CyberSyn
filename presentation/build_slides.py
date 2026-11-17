#!/usr/bin/env python3
"""Emit Google Slides batchUpdate payloads for the CyberSyn deck.

Google Slides are 10 x 5.625 in, so every coordinate is the pptx layout scaled by
0.75. Run with --write to drop compact JSON files next to this script.

    python3 presentation/build_slides.py --write
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

BG = "1B1917"
SURFACE = "242220"
SURFACE_2 = "2C2A27"
SURFACE_3 = "33312E"
BORDER = "3F3D39"
BORDER_SOFT = "312F2C"
TEXT = "ECEBE7"
STRONG = "FAFAF9"
DIM = "B3AEA6"
MUTED = "85817A"
SAGE = "97AB91"
DANGER = "BD8A80"
ACCENT = "D9D5CD"
SAGE_TINT = "232B23"
DANGER_TINT = "2A211E"
DANGER_LINE = "5A4038"

SANS = "Inter"
SERIF = "Instrument Serif"
MONO = "JetBrains Mono"

EMU = 914400
ML, MR = 0.64, 9.36


def rgb(h):
    return {"rgbColor": {"red": round(int(h[0:2], 16) / 255, 3),
                         "green": round(int(h[2:4], 16) / 255, 3),
                         "blue": round(int(h[4:6], 16) / 255, 3)}}


def emu(v):
    return {"magnitude": int(round(v * EMU)), "unit": "EMU"}


class Deck:
    def __init__(self):
        self.slides: dict[str, list] = {}

    def add(self, sid, body):
        self.slides[sid].append(body)

    def bg(self, sid):
        self.add(sid, {"updatePageProperties": {
            "objectId": sid,
            "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": rgb(BG)}}},
            "fields": "pageBackgroundFill.solidFill.color"}})

    def rect(self, sid, oid, x, y, w, h, fill, outline=None, rounded=False):
        oid = oid if len(oid) >= 5 else "cs_" + oid
        self.add(sid, {"createShape": {
            "objectId": oid,
            "shapeType": "ROUND_RECTANGLE" if rounded else "RECTANGLE",
            "elementProperties": {
                "pageObjectId": sid,
                "size": {"width": emu(w), "height": emu(h)},
                "transform": {"scaleX": 1, "scaleY": 1, "unit": "EMU",
                              "translateX": int(round(x * EMU)),
                              "translateY": int(round(y * EMU))}}}})
        self.add(sid, {"updateShapeProperties": {
            "objectId": oid,
            "shapeProperties": {
                "shapeBackgroundFill": {"solidFill": {"color": rgb(fill)}},
                "outline": {"outlineFill": {"solidFill": {"color": rgb(outline or fill)}},
                            "weight": {"magnitude": 1, "unit": "PT"}}},
            "fields": "shapeBackgroundFill.solidFill.color,outline.outlineFill.solidFill.color,"
                      "outline.weight"}})

    def text(self, sid, oid, x, y, w, h, paras, align="START", anchor=None):
        oid = oid if len(oid) >= 5 else "cs_" + oid
        """paras: list of {runs: [(txt, style)], space_before, line_spacing, align}."""
        bx, by, bw, bh = x - 0.1, y - 0.05, w + 0.2, h + 0.1
        self.add(sid, {"createShape": {
            "objectId": oid, "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": sid,
                "size": {"width": emu(bw), "height": emu(bh)},
                "transform": {"scaleX": 1, "scaleY": 1, "unit": "EMU",
                              "translateX": int(round(bx * EMU)),
                              "translateY": int(round(by * EMU))}}}})
        full = "\n".join("".join(r[0] for r in p["runs"]) for p in paras)
        self.add(sid, {"insertText": {"objectId": oid, "text": full, "insertionIndex": 0}})

        if anchor:
            self.add(sid, {"updateShapeProperties": {
                "objectId": oid,
                "shapeProperties": {"contentAlignment": anchor},
                "fields": "contentAlignment"}})

        idx = 0
        for p in paras:
            pstart = idx
            for txt, st in p["runs"]:
                n = len(txt)
                style = {"fontFamily": st.get("font", SANS),
                         "fontSize": {"magnitude": st.get("size", 9), "unit": "PT"},
                         "foregroundColor": {"opaqueColor": rgb(st.get("color", TEXT))}}
                fields = "fontFamily,fontSize,foregroundColor"
                if st.get("bold"):
                    style["bold"] = True
                    fields += ",bold"
                if st.get("italic"):
                    style["italic"] = True
                    fields += ",italic"
                self.add(sid, {"updateTextStyle": {
                    "objectId": oid, "style": style,
                    "textRange": {"type": "FIXED_RANGE", "startIndex": idx, "endIndex": idx + n},
                    "fields": fields}})
                idx += n
            pend = max(pstart + 1, idx)
            palign = p.get("align", align)
            if palign != "START" or p.get("space_before") or p.get("line_spacing"):
                pstyle, pfields = {"alignment": palign}, "alignment"
                if p.get("line_spacing"):
                    pstyle["lineSpacing"] = p["line_spacing"]
                    pfields += ",lineSpacing"
                if p.get("space_before"):
                    pstyle["spaceAbove"] = {"magnitude": p["space_before"], "unit": "PT"}
                    pfields += ",spaceAbove"
                self.add(sid, {"updateParagraphStyle": {
                    "objectId": oid, "style": pstyle,
                    "textRange": {"type": "FIXED_RANGE", "startIndex": pstart, "endIndex": pend},
                    "fields": pfields}})
            idx += 1  # the newline between paragraphs

    def chrome(self, sid, page, eyebrow, title, lede=None, lede_w=6.8):
        self.bg(sid)
        paras = [dict(runs=[(eyebrow.upper(), dict(size=7, color=DIM, font=MONO))]),
                 dict(runs=[(title, dict(size=21, color=STRONG, bold=True))], space_before=8)]
        if lede:
            paras.append(dict(runs=[(lede, dict(size=9, color=DIM))], space_before=8,
                              line_spacing=120))
        self.text(sid, f"{sid}_h", ML, 0.5, max(6.8, lede_w), 1.05, paras)
        self.text(sid, f"{sid}_ft", ML, 5.24, 4.0, 0.18,
                  [dict(runs=[("CYBERSYN  ·  AI SECURITY GATEWAY", dict(size=6, color=MUTED, font=MONO))])])
        self.text(sid, f"{sid}_pg", MR - 1.0, 5.24, 1.0, 0.18,
                  [dict(runs=[(f"{page:02d} / 06", dict(size=6, color=MUTED, font=MONO))],
                        align="END")])


d = Deck()


# --------------------------------------------------------------------- cover
s = "cs_s1"
d.slides[s] = []
d.bg(s)
d.text(s, "s1a01", 0.64, 0.32, 3.0, 0.2,
       [dict(runs=[("CYBERSYN", dict(size=7.5, color=TEXT, font=MONO))])])
d.text(s, "s1a02", 5.9, 0.32, 3.46, 0.2,
       [dict(runs=[("NETCOMPANY HACKATHON ATHENS 2026", dict(size=6.5, color=MUTED, font=MONO))],
             align="END")])

d.text(s, "s1a03", 0.64, 1.0, 4.7, 1.9,
       [dict(runs=[("CHALLENGE 3  ·  SHADOW AI & DATA PROTECTION",
                    dict(size=6.8, color=SAGE, font=MONO))]),
        dict(runs=[("Cyber", dict(size=58, color=STRONG, font=SERIF, italic=True)),
                   ("Syn", dict(size=56, color=STRONG, bold=True))], space_before=6),
        dict(runs=[("The gate every AI prompt passes through.", dict(size=17, color=TEXT))],
             space_before=14, line_spacing=105)])

d.rect(s, "s1a04", 0.64, 2.62, 0.86, 0.028, SAGE)

d.text(s, "s1a05", 0.64, 2.76, 4.6, 0.62,
       [dict(runs=[("Shadow-AI protection and data privacy for teams. Every prompt is screened "
                    "on your own machine — before it ever reaches the model.",
                    dict(size=9, color=DIM))], line_spacing=125)])

d.text(s, "s1a06", 0.64, 4.16, 4.9, 0.2,
       [dict(runs=[("LOCAL-FIRST      FAIL-CLOSED      AUDITABLE",
                    dict(size=6.5, color=ACCENT, font=MONO))])])
d.text(s, "s1a07", 0.64, 4.5, 5.0, 0.2,
       [dict(runs=[("Flask · spaCy EN/EL · distilbart-MNLI · LiteLLM",
                    dict(size=6.5, color=MUTED, font=MONO))])])

d.rect(s, "s1a08", 5.42, 1.0, 3.54, 3.42, SURFACE, BORDER_SOFT, rounded=True)
d.text(s, "s1a09", 5.68, 1.14, 2.6, 0.18,
       [dict(runs=[("THE SCREENING PATH", dict(size=6, color=MUTED, font=MONO))])])

d.rect(s, "s1a10", 5.68, 1.4, 3.02, 0.6, SURFACE_2, BORDER, rounded=True)
d.text(s, "s1a11", 5.8, 1.47, 2.8, 0.46,
       [dict(runs=[("PROMPT · 09:41", dict(size=5.5, color=MUTED, font=MONO))]),
        dict(runs=[("“ΑΦΜ 123456789 — fix this invoice”", dict(size=6.5, color=TEXT, font=MONO))],
             space_before=2)])

gates = [("PII & Greek IDs", BORDER_SOFT), ("Confidential context", BORDER_SOFT),
         ("Prompt injection", DANGER_LINE)]
gy = 2.14
for n, (label, line) in enumerate(gates):
    d.rect(s, f"s1a{12+n*2}", 5.68, gy, 3.02, 0.34, SURFACE_2, line, rounded=True)
    d.text(s, f"s1a{13+n*2}", 5.84, gy + 0.07, 2.7, 0.2,
           [dict(runs=[(f"0{n+1}   ", dict(size=6.5, color=MUTED, font=MONO)),
                       (label, dict(size=7.5, color=TEXT, bold=True))])])
    gy += 0.4

d.rect(s, "s1a18", 5.68, 3.5, 3.02, 0.54, DANGER_TINT, DANGER_LINE, rounded=True)
d.text(s, "s1a19", 5.84, 3.57, 2.7, 0.42,
       [dict(runs=[("BLOCKED · line 4 · AFM", dict(size=6.5, color=DANGER, font=MONO))]),
        dict(runs=[("reason shown · decision logged", dict(size=6, color=MUTED, font=MONO))],
             space_before=2)])
d.text(s, "s1a20", MR - 1.0, 5.24, 1.0, 0.18,
       [dict(runs=[("01 / 06", dict(size=6, color=MUTED, font=MONO))], align="END")])


# ------------------------------------------------------------------- problem
s = "cs_s2"
d.slides[s] = []
d.chrome(s, 2, "01 — the problem", "Shadow AI is already inside the building.",
         "Code, contracts and client data go into public chat tools every day — usually without IT "
         "knowing, and always without a record of what left.", lede_w=6.6)

cards = [
    ("s2c1", 0.64, "PROMPT 01", "“Fix the ΑΦΜ 123456789 on this client invoice”",
     "PERSONAL IDENTIFIER", "A Greek tax ID, unvalidated, now in someone else’s inference logs."),
    ("s2c2", 3.6, "PROMPT 02", "“connect with password=Hunter2! to prod-db”",
     "CREDENTIAL", "A live credential, pasted to debug a connection string."),
    ("s2c3", 6.56, "PROMPT 03", "“summarise clause 7 of the NDA for the client”",
     "CONFIDENTIAL CONTEXT", "Client contract text, sent to a model with unknown retention."),
]
for oid, x, tag, prompt, cat, desc in cards:
    d.rect(s, oid, x, 1.86, 2.76, 1.68, SURFACE, BORDER_SOFT, rounded=True)
    d.text(s, oid + "t", x + 0.18, 2.0, 2.4, 1.42,
           [dict(runs=[(tag, dict(size=5.8, color=MUTED, font=MONO))]),
            dict(runs=[(prompt, dict(size=7.2, color=TEXT, font=MONO))], space_before=7,
                 line_spacing=125),
            dict(runs=[(cat, dict(size=5.8, color=DANGER, font=MONO))], space_before=9),
            dict(runs=[(desc, dict(size=6.4, color=MUTED))], space_before=3, line_spacing=118)])

d.rect(s, "s2r", ML, 3.76, MR - ML, 0.008, BORDER_SOFT)
stats = [(0.64, "0", "visibility for IT into what was pasted"),
         (3.6, "1 paste", "is all it takes to move client data out"),
         (6.56, "3", "hand-offs: device → provider → unknown retention")]
for n, (x, num, desc) in enumerate(stats):
    d.text(s, f"s2s{n}", x, 3.9, 2.5, 0.82,
           [dict(runs=[(num, dict(size=26, color=STRONG, bold=True))]),
            dict(runs=[(desc, dict(size=7, color=DIM))], space_before=6, line_spacing=120)])


# --------------------------------------------------------------------- gates
s = "cs_s3"
d.slides[s] = []
d.chrome(s, 3, "02 — how it works", "One prompt. Three gates. No leaks.",
         "Cheap, precise rules fire first; a local classifier only reads the lines the rules could "
         "not explain. Every verdict names its stage, its line and its reason.", lede_w=7.0)

d.text(s, "s3in", ML, 1.62, 3.0, 0.18,
       [dict(runs=[("IN  ·  MEMBER PROMPT", dict(size=6, color=SAGE, font=MONO))])])
d.text(s, "s3out", MR - 3.0, 1.62, 3.0, 0.18,
       [dict(runs=[("OUT  ·  MODEL ANSWER", dict(size=6, color=SAGE, font=MONO))], align="END")])

stages = [
    ("s3g1", 0.64, "01", "PII & Greek IDs",
     "AFM + checksum · AMKA · phones · names EN/EL · keys · IBAN", "regex + spaCy NER"),
    ("s3g2", 3.6, "02", "Confidential context",
     "Contracts & NDAs · financials · credentials · source code", "rules + zero-shot MNLI"),
    ("s3g3", 6.56, "03", "Prompt injection",
     "Instruction override · payloads in comments · jailbreak phrasing", "regex + zero-shot MNLI"),
]
for oid, x, num, name, detects, tech in stages:
    d.rect(s, oid, x, 1.78, 2.76, 1.66, SURFACE, BORDER_SOFT, rounded=True)
    d.text(s, oid + "t", x + 0.18, 1.92, 2.4, 1.44,
           [dict(runs=[(num, dict(size=12, color=SAGE, font=MONO))]),
            dict(runs=[(name, dict(size=9, color=STRONG, bold=True))], space_before=3),
            dict(runs=[(detects, dict(size=6.4, color=DIM))], space_before=8, line_spacing=120),
            dict(runs=[(tech, dict(size=5.6, color=MUTED, font=MONO))], space_before=9)])

d.rect(s, "s3bad", 0.64, 3.62, 5.62, 0.98, DANGER_TINT, "4A352F", rounded=True)
d.text(s, "s3bt", 0.84, 3.7, 5.24, 0.82,
       [dict(runs=[("ANY GATE FIRES  →  BLOCKED BEFORE SEND", dict(size=6.8, color=DANGER, font=MONO))]),
        dict(runs=[("stage · cause · line · offset · snippet returned to the member, written to "
                    "BLOCK_LOG and attributed.", dict(size=7.8, color=TEXT))],
             space_before=4, line_spacing=120)])

d.rect(s, "s3good", 6.44, 3.62, 2.92, 0.98, SAGE_TINT, "36423A", rounded=True)
d.text(s, "s3gt", 6.62, 3.7, 2.56, 0.82,
       [dict(runs=[("ALL CLEAR  →  FORWARDED", dict(size=6.8, color=SAGE, font=MONO))]),
        dict(runs=[("via LiteLLM to the chosen provider; the exchange is saved to chat history.",
                    dict(size=7.8, color=TEXT))], space_before=4, line_spacing=120)])

d.text(s, "s3fc", ML, 4.74, 8.6, 0.18,
       [dict(runs=[("FAIL CLOSED — a scanner that crashes, times out (60 s) or prints no verdict "
                    "blocks the request.", dict(size=6.3, color=MUTED, font=MONO))])])


# ----------------------------------------------------------------- in action
s = "cs_s4"
d.slides[s] = []
d.chrome(s, 4, "03 — in action", "From keystroke to verdict, inside one request.",
         "No generic refusal: the member sees the exact line, the rule that fired, and a way forward.",
         lede_w=6.8)

d.rect(s, "s4mock", 0.64, 1.8, 5.6, 2.95, SURFACE, BORDER_SOFT, rounded=True)
d.rect(s, "s4bar", 0.64, 1.8, 5.6, 0.32, SURFACE_2)
d.text(s, "s4bart", 0.84, 1.86, 1.6, 0.18,
       [dict(runs=[("CyberSyn · workspace", dict(size=6.5, color=DIM, font=MONO))])])
d.text(s, "s4barr", 4.42, 1.86, 1.62, 0.18,
       [dict(runs=[("screening on host", dict(size=6, color=SAGE, font=MONO))], align="END")])

d.rect(s, "s4bub", 2.42, 2.3, 3.52, 0.62, SURFACE_3, BORDER, rounded=True)
d.text(s, "s4bubt", 2.52, 2.37, 3.32, 0.48,
       [dict(runs=[("“Refresh the invoice for ΑΦΜ 123456789 and send it to the model.”",
                    dict(size=6.5, color=TEXT, font=MONO))], align="END", line_spacing=125)])

d.rect(s, "s4blk", 0.86, 3.08, 5.16, 1.5, DANGER_TINT, DANGER_LINE, rounded=True)
d.text(s, "s4blkt", 1.04, 3.16, 4.8, 1.34,
       [dict(runs=[("BLOCKED · CHECK 1 — PERSONAL IDENTIFIERS",
                    dict(size=6.8, color=DANGER, font=MONO))]),
        dict(runs=[("Greek tax ID (AFM) · checksum matched · strict policy",
                    dict(size=6.2, color=DIM, font=MONO))], space_before=6),
        dict(runs=[("… invoice for ΑΦΜ 123456789 → send …", dict(size=8, color=TEXT, font=MONO))],
             space_before=6),
        dict(runs=[("GREEK_AFM · LINE 4 · OFFSET 21 · SCORE 0.92",
                    dict(size=5.6, color=MUTED, font=MONO))], space_before=7)])

d.text(s, "s4sent", 4.1, 4.38, 1.76, 0.18,
       [dict(runs=[("Nothing was sent.", dict(size=6.2, color=SAGE, font=MONO))], align="END")])

steps = [
    ("Authenticate", "The member’s own session token; policy and checks resolved for them."),
    ("Screen locally", "Three scanners, separate processes, 60 s cap, fail closed."),
    ("Explain or forward", "A block with line, snippet and stage — or a clean send to the provider."),
    ("Log & attribute", "Stage, reason, member, timestamp. No prompt text for overrides."),
]
step_paras = []
for n, (name, body) in enumerate(steps):
    step_paras.append(dict(runs=[(f"0{n+1}   ", dict(size=6.4, color=SAGE, font=MONO)),
                                 (name, dict(size=9, color=STRONG, bold=True))],
                           space_before=0 if n == 0 else 12))
    step_paras.append(dict(runs=[(body, dict(size=6.6, color=DIM))], space_before=3,
                           line_spacing=120))
d.text(s, "s4steps", 6.62, 1.78, 2.74, 2.9, step_paras)

d.text(s, "s4note", 6.62, 4.86, 2.8, 0.18,
       [dict(runs=[("Interface shown is illustrative.", dict(size=6, color=MUTED, font=MONO))])])


# ---------------------------------------------------------------- principles
s = "cs_s5"
d.slides[s] = []
d.chrome(s, 5, "04 — why it holds up", "Four rules we refused to break.",
         "What makes a gateway trustworthy rather than just another blocker in the way.", lede_w=7.2)

principles = [
    ("01", "Local first", "Scanning runs on the machine serving CyberSyn. No third-party DLP sees "
                          "the prompt — that would only move the leak."),
    ("02", "Fail closed", "A scanner that crashes, times out or prints nothing parseable refuses the "
                          "request. A broken gate is never an open gate."),
    ("03", "Explain, don’t just block", "Every block names the stage, category, line, offsets and "
                                        "snippet, so people learn the rule instead of fighting it."),
    ("04", "Humans stay in control", "An administrator can approve a real exception — verified "
                                     "server-side and recorded in the audit trail, attributed."),
]
for n, (num, name, body) in enumerate(principles):
    x = 0.64 + (n % 2) * 4.44
    y = 1.78 + (n // 2) * 1.24
    d.rect(s, f"s5c{n}", x, y, 4.26, 1.1, SURFACE, BORDER_SOFT, rounded=True)
    d.text(s, f"s5t{n}", x + 0.2, y + 0.14, 3.9, 0.86,
           [dict(runs=[(f"{num}   ", dict(size=6.4, color=SAGE, font=MONO)),
                       (name, dict(size=9.2, color=STRONG, bold=True))]),
            dict(runs=[(body, dict(size=6.8, color=DIM))], space_before=5, line_spacing=125)])

d.rect(s, "s5proof", ML, 4.36, MR - ML, 0.38, SURFACE_2, BORDER_SOFT, rounded=True)
d.text(s, "s5pt", ML + 0.1, 4.45, MR - ML - 0.2, 0.2,
       [dict(runs=[("21 authorisation tests · EN / EL interface · Fernet-encrypted keys · "
                    "SHA-256 session hashes · 0 prompts inspected by a third party",
                    dict(size=6, color=DIM, font=MONO))], align="CENTER")])

d.text(s, "s5ev", ML, 4.86, 6.4, 0.18,
       [dict(runs=[("Evidence: tools/test_auth.py · README → Security & privacy design",
                    dict(size=6, color=MUTED, font=MONO))])])


# -------------------------------------------------------------------- stack
s = "cs_s6"
d.slides[s] = []
d.chrome(s, 6, "05 — under the hood", "Boring where it counts. Sharp where it shows.")

groups = [
    ("SCREENING", "spaCy en + el · distilbart-mnli · PyTorch · bilingual rules", 1.55),
    ("PLATFORM", "Flask · SQLite · LiteLLM · Docker", 2.16),
    ("TRUST", "Fernet keys · Werkzeug hashes · SHA-256 sessions · EN / EL UI", 2.77),
]
for n, (label, chips, y) in enumerate(groups):
    d.text(s, f"s6g{n}", ML, y, 4.5, 0.42,
           [dict(runs=[(label, dict(size=6, color=MUTED, font=MONO))]),
            dict(runs=[(chips, dict(size=7.2, color=TEXT))], space_before=4)])

d.text(s, "s6shell", ML, 3.6, 4.7, 0.36,
       [dict(runs=[("$ docker compose up --build", dict(size=6.8, color=DIM, font=MONO))]),
        dict(runs=[("one command, no external database", dict(size=6, color=MUTED, font=MONO))],
             space_before=3)])

d.rect(s, "s6team", 5.38, 1.55, 3.98, 2.32, SURFACE, BORDER_SOFT, rounded=True)
d.text(s, "s6tl", 5.58, 1.68, 3.4, 0.18,
       [dict(runs=[("TEAM CYBERSYN", dict(size=6, color=MUTED, font=MONO))])])
roles = [("Machine learning & security", "Scanners, thresholds, evaluation harness"),
         ("Backend & platform", "Auth, encryption, provider routing, Docker"),
         ("Product & front-end", "Bilingual UI, chat history, team dashboard")]
role_paras = []
for n, (role, body) in enumerate(roles):
    role_paras.append(dict(runs=[(role, dict(size=8, color=STRONG, bold=True))],
                           space_before=0 if n == 0 else 10))
    role_paras.append(dict(runs=[(body, dict(size=6.3, color=MUTED))], space_before=3))
d.text(s, "s6roles", 5.58, 1.92, 3.55, 1.85, role_paras)

d.rect(s, "s6rule", ML, 4.16, MR - ML, 0.008, BORDER_SOFT)
d.text(s, "s6thanks", 0.6, 4.26, 4.8, 0.54,
       [dict(runs=[("Thank you", dict(size=30, color=STRONG, italic=True, font=SERIF)),
                   (".", dict(size=30, color=SAGE, bold=True))])])
d.text(s, "s6qa", ML, 4.88, 4.0, 0.2,
       [dict(runs=[("Questions & discussion", dict(size=8, color=DIM))])])
d.text(s, "s6right", 6.0, 4.5, 3.36, 0.5,
       [dict(runs=[("github.com/JohannSSK/CyberSyn", dict(size=6.4, color=TEXT, font=MONO))],
             align="END"),
        dict(runs=[("Netcompany Hackathon Athens 2026 · Challenge 3",
                    dict(size=6, color=MUTED, font=MONO))], space_before=3, align="END")])


if "--write" in sys.argv:
    payloads = {"slides_setup.json": {"requests": [
        {"createSlide": {"objectId": sid, "slideLayoutReference": {"predefinedLayout": "BLANK"}}}
        for sid in d.slides]}}
    for sid, reqs in d.slides.items():
        payloads[f"{sid}.json"] = {"requests": reqs}
    total = 0
    for name, payload in payloads.items():
        blob = json.dumps(payload, separators=(",", ":"))
        total += len(blob)
        with open(os.path.join(HERE, name), "w") as f:
            f.write(blob)
        print(name, len(payload["requests"]), "requests", len(blob), "bytes")
    print("TOTAL", total, "bytes")
