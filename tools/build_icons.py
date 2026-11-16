#!/usr/bin/env python3
"""Render the app's icon set to transparent PNGs.

The icon designs live in exactly one place: the `SVG` table in
`src/static/js/core/icons.js`. The browser inlines those paths as vectors;
this script parses the same table and rasterises every entry to a
transparent PNG under `assets/icons/`. One source, two renderings — they
cannot drift apart, and no path data is duplicated.

    python3 tools/build_icons.py            # rebuild every icon
    python3 tools/build_icons.py --check    # verify the PNGs, write nothing

Needs Pillow only:  pip install Pillow
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from icons import Raster, Svg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ICONS_JS = ROOT / "src" / "static" / "js" / "core" / "icons.js"
OUT_DIR = ROOT / "assets" / "icons"

SIZE = 72           # final PNG edge, in pixels
OVERSAMPLE = 6      # draw at 6x, then downsample for anti-aliasing
CELL = 24           # the viewBox the paths are drawn on
STROKE = "1.8"      # must match stroke-width in icons.js
ACCENT = "#c9c4ba"  # a warm neutral between --text-dim and --text,
                    # so the PNGs read on every surface in the palette

MIN_INK = 0.02      # a usable icon is mostly transparent...
MAX_INK = 0.55      # ...and carries a sensible amount of ink
MAX_EDGE_INK = 0.02 # ink touching the border means the icon is cropped


def parse_table() -> dict[str, str]:
    """Pull the `name: '<svg body>'` pairs out of the SVG table in icons.js."""
    if not ICONS_JS.is_file():
        sys.exit(f"cannot find {ICONS_JS}")
    source = ICONS_JS.read_text(encoding="utf-8")
    table = re.search(r"var SVG = \{(.*?)\n    \};", source, re.S)
    if not table:
        sys.exit("could not locate the `var SVG = { ... }` table in icons.js")
    # The trailing comma is optional: the last entry in the table has none.
    entries = re.findall(r"(\w+):\s*'((?:[^'\\]|\\.)*)'\s*,?\s*(?=\n|$)", table.group(1))
    if not entries:
        sys.exit("the SVG table parsed, but held no entries")
    return {name: body.replace("\\'", "'") for name, body in entries}


def document(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CELL} {CELL}" '
        f'width="{CELL}" height="{CELL}" fill="none" stroke="{ACCENT}" '
        f'stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


def write_icon(name: str, body: str, target: Path, raster: Raster) -> None:
    icon = Svg.from_string(document(body))
    raster.render(icon, size=SIZE).save(target, "PNG", optimize=True)


def inspect(path: Path) -> tuple[float, float]:
    """Return (ink fraction, fraction of ink sitting on the outer border)."""
    from PIL import Image

    with Image.open(path) as image:
        alpha = image.convert("RGBA").split()[3]
    width, height = alpha.size
    data = alpha.tobytes()  # "L" mode: one byte per pixel
    total = width * height
    ink = sum(1 for value in data if value > 8)
    border = 0
    for y in range(height):
        for x in range(width):
            if x and y and x < width - 1 and y < height - 1:
                continue
            if data[y * width + x] > 8:
                border += 1
    return ink / total, border / total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render every icon in icons.js to assets/icons/*.png"
    )
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args()

    icons = parse_table()
    raster = Raster(oversample=OVERSAMPLE)
    print(f"{len(icons)} icons declared in {ICONS_JS.relative_to(ROOT)}")

    failures: list[str] = []
    for name, body in sorted(icons.items()):
        target = OUT_DIR / f"{name}.png"
        try:
            if not args.check:
                write_icon(name, body, target, raster)
            elif not target.is_file():
                raise FileNotFoundError("no PNG on disk")
        except Exception as exc:  # noqa: BLE001 - report every bad icon, keep going
            failures.append(f"{name}: {exc}")
            print(f"  FAIL  {name:<12} {exc}")
            continue

        ink, edge = inspect(target)
        if not MIN_INK <= ink <= MAX_INK:
            failures.append(f"{name}: ink {ink:.1%} outside {MIN_INK:.0%}-{MAX_INK:.0%}")
            print(f"  FAIL  {name:<12} ink {ink:.1%} (want {MIN_INK:.0%}-{MAX_INK:.0%})")
            continue
        if edge > MAX_EDGE_INK:
            failures.append(f"{name}: {edge:.1%} ink on the border, icon is cropped")
            print(f"  FAIL  {name:<12} {edge:.1%} ink touches the edge (cropped?)")
            continue

        verb = "ok" if args.check else "wrote"
        print(f"  {verb:<5} {name:<12} {target.stat().st_size / 1024:4.1f} kB  ink {ink:5.1%}")

    stale = sorted(path.name for path in OUT_DIR.glob("*.png") if path.stem not in icons)
    for name in stale:
        print(f"  note  {name} has no entry in the SVG table")

    if failures:
        print(f"\n{len(failures)} of {len(icons)} icons failed")
        return 1
    print(f"\nall {len(icons)} icons render cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
