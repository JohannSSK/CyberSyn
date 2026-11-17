# CyberSyn project deck

Six slides, 16:9, dark warm-charcoal palette taken from the app's own design tokens
(`src/static/css/base.css`), with the structure of the example deck: cover → problem →
how it works → in action → why it holds up → stack + team + thanks.

| File | What it is |
|---|---|
| `CyberSyn_Project_Deck.pptx` | The PowerPoint. 6 slides, editable shapes, speaker notes on every slide. |
| `index.html` | The same deck in a browser — arrow keys / space to move, `F` full screen, `N` speaker notes. |
| `build_deck.py` | Rebuilds the `.pptx` from code (and `--preview` renders rough PNG proofs). |

## Presenting

- PowerPoint / Keynote / Google Slides: open the `.pptx`. It is 13.33 × 7.5 in (16:9).
- Browser: open `index.html` (or serve the repo and visit `/presentation/index.html`).
  The browser version loads Inter, Instrument Serif and JetBrains Mono from Google Fonts;
  the `.pptx` names Inter (body) and Georgia (serif accents), so it stays presentable
  even on a machine without the webfonts installed.
- Every slide carries speaker notes — a 30–45 second script per slide.

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
```

All copy, colours and coordinates live at the top of `build_deck.py`; edit there rather
than nudging shapes in PowerPoint, so the deck stays reproducible.
