"""Read the small slice of SVG that the icon set is written in.

A document becomes a flat list of `Shape` objects, each holding already
flattened geometry plus resolved paint. Inheritance is handled the simple
way every icon needs: attributes fall back to the parent `<svg>` element.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from xml.etree import ElementTree

from .geometry import (
    SubPath,
    circle_path,
    ellipse_path,
    flatten_path,
    points_path,
    rounded_rect_path,
)


@dataclass
class Shape:
    subpaths: List[SubPath]
    stroke: Optional[Tuple[int, int, int]] = None
    fill: Optional[Tuple[int, int, int]] = None
    width: float = 1.0
    round_caps: bool = True


@dataclass
class Svg:
    width: float = 24.0
    height: float = 24.0
    shapes: List[Shape] = field(default_factory=list)

    @classmethod
    def from_string(cls, markup: str, default_colour: Tuple[int, int, int] = (0, 0, 0)) -> "Svg":
        root = ElementTree.fromstring(markup)
        view_box = _split_numbers(root.attrib.get("viewBox", "")) or [0, 0, 24, 24]
        width = _length(root.attrib.get("width"), view_box[2])
        height = _length(root.attrib.get("height"), view_box[3])

        inherited = {
            "stroke": _colour(root.attrib.get("stroke"), default_colour),
            "fill": _colour(root.attrib.get("fill"), None),
            "width": _number(root.attrib.get("stroke-width"), 1.0),
            "cap": (root.attrib.get("stroke-linecap", "butt").lower() == "round"),
        }

        document = cls(width=width, height=height)
        for element in root.iter():
            if element is root:
                continue
            document.shapes.append(_shape(element, inherited))
        return document


def _shape(element: ElementTree.Element, base: dict) -> Shape:
    tag = element.tag.split("}")[-1]  # strip any namespace
    attrib = element.attrib
    stroke = _colour(attrib.get("stroke"), base["stroke"])
    fill = _colour(attrib.get("fill"), base["fill"])

    if tag == "path":
        subpaths = flatten_path(attrib.get("d", ""))
    elif tag == "circle":
        subpaths = circle_path(
            _number(attrib.get("cx"), 0.0),
            _number(attrib.get("cy"), 0.0),
            _number(attrib.get("r"), 0.0),
        )
    elif tag == "ellipse":
        subpaths = ellipse_path(
            _number(attrib.get("cx"), 0.0),
            _number(attrib.get("cy"), 0.0),
            _number(attrib.get("rx"), 0.0),
            _number(attrib.get("ry"), 0.0),
        )
    elif tag == "rect":
        rx = _number(attrib.get("rx"), _number(attrib.get("ry"), 0.0))
        ry = _number(attrib.get("ry"), rx)
        subpaths = rounded_rect_path(
            _number(attrib.get("x"), 0.0),
            _number(attrib.get("y"), 0.0),
            _number(attrib.get("width"), 0.0),
            _number(attrib.get("height"), 0.0),
            rx,
            ry,
        )
    elif tag == "line":
        subpaths = [
            SubPath(
                points=[
                    (_number(attrib.get("x1"), 0.0), _number(attrib.get("y1"), 0.0)),
                    (_number(attrib.get("x2"), 0.0), _number(attrib.get("y2"), 0.0)),
                ]
            )
        ]
    elif tag in ("polyline", "polygon"):
        subpaths = points_path(attrib.get("points", ""), close=(tag == "polygon"))
    else:  # pragma: no cover - the icon set has no other shapes
        subpaths = []

    if subpaths and fill is None and stroke is None:
        stroke = base["stroke"]

    return Shape(
        subpaths=subpaths,
        stroke=stroke,
        fill=fill,
        width=_number(attrib.get("stroke-width"), base["width"]),
        round_caps=attrib.get("stroke-linecap", "").lower() == "round" or base["cap"],
    )


def _length(value: Optional[str], fallback: float) -> float:
    if not value:
        return fallback
    match = re.match(r"\s*([-+]?(?:\d*\.\d+|\d+\.?))", value)
    return float(match.group(1)) if match else fallback


def _number(value: Optional[str], fallback: float) -> float:
    try:
        return float(str(value).strip().rstrip("px").rstrip())
    except (TypeError, ValueError):
        return fallback


def _split_numbers(value: str) -> List[float]:
    return [float(part) for part in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)", value or "")]


def _colour(
    value: Optional[str], fallback: Optional[Tuple[int, int, int]]
) -> Optional[Tuple[int, int, int]]:
    """Resolve `none`, `currentColor` and #rgb / #rrggbb; unknown -> fallback."""
    if value is None:
        return fallback
    text = value.strip().lower()
    if text in ("none", "transparent"):
        return None
    if text == "currentcolor":
        return fallback
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        if len(digits) == 6:
            try:
                return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return fallback
    named = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 128, 0),
        "blue": (0, 0, 255),
    }
    return named.get(text, fallback)
