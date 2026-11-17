# CyberSyn project deck

Six slides, 16:9, dark warm-charcoal palette taken from the app's own design tokens
(`src/static/css/base.css`), with the structure of the example deck: cover → problem →
how it works → in action → why it holds up → stack + team + thanks.

The primary deliverable is the **native Google Slides deck**:
[CyberSyn — Project Deck](https://docs.google.com/presentation/d/1Z_JOh5FAS0R2gSPdxB_Ox26CDD1KAcGmzXknMGzYukQ/edit)
(every title, card, rule and band is a real Slides object — nothing is a flat image).
`CyberSyn_Project_Deck.pptx` is the offline/backup copy.

| File | What it is |
|---|---|
| `CyberSyn_Project_Deck.pptx` | The PowerPoint backup. 6 slides, editable shapes, speaker notes on every slide. |
| `build_deck.py` | Rebuilds the `.pptx` from code (and `--preview` renders rough PNG proofs). |
| `build_slides.py` | Builds the Google Slides deck: emits one `batchUpdate` payload per slide. |

## Presenting

- **Google Slides** — open the deck above. It is already built; do not re-run the payloads,
  re-applying a slide duplicates its objects.
- **PowerPoint / Keynote** — open the `.pptx`. It is 13.33 × 7.5 in (16:9), and names Inter
  (body) and Georgia (serif accents) so it stays presentable without the webfonts installed.
- The `.pptx` carries speaker notes — a 30–45 second script per slide.

## The story the deck tells

1. **Cover** — CyberSyn, the gate every AI prompt passes through, and a small diagram of the screening path.
2. **The problem** — three ordinary prompts that leak an identifier, a credential and a contract clause.
3. **How it works** — the three gates, what each detects, and what happens on a hit versus a pass.
4. **In action** — one request end to end: the block card the member actually sees, plus the four server steps.
5. **Why it holds up** — local-first, fail-closed, explain-don't-just-block, humans in control, with the evidence strip.
6. **Under the hood** — the stack, the team split, and the one-command Docker start.

## Rebuilding

```bash
python3 -m venv .venv-deck
.venv-deck/bin/pip install python-pptx pillow
.venv-deck/bin/python presentation/build_deck.py            # writes the .pptx
.venv-deck/bin/python presentation/build_deck.py --preview   # + rough PNG proofs in _preview/

.venv-deck/bin/python presentation/build_slides.py --write   # writes slides_setup.json + cs_s1..6.json
```

All copy, colours and coordinates live at the top of each builder; edit there rather than
nudging shapes by hand, so the deck stays reproducible. The Google Slides side is a page
of 10 × 5.625 in, so `build_slides.py` scales the pptx geometry by 0.75.

To rebuild the online deck from scratch: create a blank presentation, apply
`slides_setup.json` once (creates the six pages), then apply `cs_s1.json` … `cs_s6.json`
one call each, in order. One slide per call — a single bad request rejects the whole batch.
