"""Turn SVG path data into plain polylines.

Everything a renderer needs is a list of points: curves and elliptical arcs
are flattened into straight segments, so the drawing code never has to know
about beziers. The flattening is adaptive — a quarter arc gets more segments
than a short one — so oversampled renders stay smooth without wasting work.

Public API:
    SubPath          - one continuous run of points, plus a `closed` flag
    flatten_path(d)  - parse an SVG `d` attribute into a list of SubPath
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

Point = Tuple[float, float]

_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUMBER)

# How finely to slice a right angle of arc or a bezier, in segments.
ARC_QUALITY = 24
CURVE_QUALITY = 16


@dataclass
class SubPath:
    points: List[Point] = field(default_factory=list)
    closed: bool = False


def _cubic_at(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _quad_at(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    u = 1.0 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def _step_count(p0: Point, p1: Point, p2: Point, p3: Point) -> int:
    """Segments needed to keep a bezier visually straight once scaled up."""
    span = max(
        math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
        math.hypot(p2[0] - p1[0], p2[1] - p1[1]),
        math.hypot(p3[0] - p2[0], p3[1] - p2[1]),
    )
    return max(4, int(math.ceil(span / 3.0 * CURVE_QUALITY)))


def _arc_points(
    start: Point,
    rx: float,
    ry: float,
    phi_deg: float,
    large_arc: bool,
    sweep: bool,
    end: Point,
) -> List[Point]:
    """Endpoint-to-centre arc conversion (SVG implementation notes F.6.1)."""
    x1, y1 = start
    x2, y2 = end
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [end]

    phi = math.radians(phi_deg % 360.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    # Step 1: midpoint, expressed in the rotated frame of the ellipse.
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy

    rx, ry = abs(rx), abs(ry)
    scale_sq = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if scale_sq > 1.0:  # Step 2: the radii are too small, grow them evenly.
        grow = math.sqrt(scale_sq)
        rx, ry = rx * grow, ry * grow

    # Step 3: centre, still in the rotated frame.
    numerator = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    factor = math.sqrt(max(numerator / denominator, 0.0))
    if large_arc == sweep:
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx

    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        value = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        return -value if (ux * vy - uy * vx) < 0 else value

    theta1 = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    steps = max(4, int(math.ceil(abs(delta) / (math.pi / 2) * ARC_QUALITY)))
    points = []
    for index in range(1, steps + 1):
        theta = theta1 + delta * index / steps
        points.append(
            (
                cos_p * rx * math.cos(theta) - sin_p * ry * math.sin(theta) + cx,
                sin_p * rx * math.cos(theta) + cos_p * ry * math.sin(theta) + cy,
            )
        )
    return points


def flatten_path(data: str) -> List[SubPath]:
    """Parse an SVG `d` attribute into a list of flattened sub-paths."""
    tokens = _TOKEN.findall(data or "")
    subpaths: List[SubPath] = []
    current: Optional[SubPath] = None

    cursor = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_cubic: Optional[Point] = None  # second control point, for S/s
    prev_quad: Optional[Point] = None   # control point, for T/t
    index = 0

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index] in "MmLlHhVvCcSsQqTtAaZz":
            raise ValueError(f"expected a number in path data near {tokens[index:index + 3]}")
        value = float(tokens[index])
        index += 1
        return value

    def flag() -> bool:
        """Read one arc flag.

        SVG flags are single characters, and minifiers happily glue them to
        what follows: `A8 8 0 1121 12` is rot=0, large=1, sweep=1, x=21, y=12.
        So take exactly one character and push the rest of the token back.
        """
        nonlocal index
        token = tokens[index]
        if token[:1].isdigit():
            remainder = token[1:]
            if remainder:
                tokens[index] = remainder
            else:
                del tokens[index]
            return token[0] == "1"
        return number() > 0.5

    def ensure() -> SubPath:
        nonlocal current
        if current is None:
            current = SubPath()
            subpaths.append(current)
        return current

    while index < len(tokens):
        command = tokens[index]
        index += 1
        relative = command.islower()
        command = command.upper()

        if command == "M":
            while index < len(tokens) and tokens[index] not in "MmLlHhVvCcSsQqTtAaZz":
                x, y = number(), number()
                cursor = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
                start = cursor
                current = SubPath(points=[cursor])
                subpaths.append(current)
                prev_cubic = prev_quad = None
            # A run of coordinates after M is treated as implicit lineto.
            command = "L"
            while index < len(tokens) and tokens[index] not in "MmLlHhVvCcSsQqTtAaZz":
                x, y = number(), number()
                cursor = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
                ensure().points.append(cursor)
            continue

        if command == "Z":
            path = ensure()
            path.closed = True
            if path.points:
                cursor = start
            prev_cubic = prev_quad = None
            continue

        while index < len(tokens) and tokens[index] not in "MmLlHhVvCcSsQqTtAaZz":
            path = ensure()
            if not path.points:
                path.points.append(cursor)

            if command == "L":
                x, y = number(), number()
                cursor = (cursor[0] + x, cursor[1] + y) if relative else (x, y)
            elif command == "H":
                x = number()
                cursor = (cursor[0] + x, cursor[1]) if relative else (x, cursor[1])
            elif command == "V":
                y = number()
                cursor = (cursor[0], cursor[1] + y) if relative else (cursor[0], y)
            elif command in "CS":
                if command == "C":
                    c1 = (number(), number())
                    c2 = (number(), number())
                else:  # S reflects the previous second control point.
                    c1 = (2 * cursor[0] - prev_cubic[0], 2 * cursor[1] - prev_cubic[1]) \
                        if prev_cubic else cursor
                    c2 = (number(), number())
                end = (number(), number())
                if relative:
                    c1 = (cursor[0] + c1[0], cursor[1] + c1[1])
                    c2 = (cursor[0] + c2[0], cursor[1] + c2[1])
                    end = (cursor[0] + end[0], cursor[1] + end[1])
                steps = _step_count(cursor, c1, c2, end)
                path.points.extend(_cubic_at(cursor, c1, c2, end, i / steps) for i in range(1, steps + 1))
                cursor, prev_cubic, prev_quad = end, c2, None
            elif command in "QT":
                if command == "Q":
                    ctrl = (number(), number())
                else:  # T reflects the previous quadratic control point.
                    ctrl = (2 * cursor[0] - prev_quad[0], 2 * cursor[1] - prev_quad[1]) \
                        if prev_quad else cursor
                end = (number(), number())
                if relative:
                    ctrl = (cursor[0] + ctrl[0], cursor[1] + ctrl[1])
                    end = (cursor[0] + end[0], cursor[1] + end[1])
                steps = _step_count(cursor, ctrl, ctrl, end)
                path.points.extend(_quad_at(cursor, ctrl, end, i / steps) for i in range(1, steps + 1))
                cursor, prev_quad, prev_cubic = end, ctrl, None
            elif command == "A":
                rx, ry = number(), number()
                phi = number()
                large, sweep = flag(), flag()
                end = (number(), number())
                if relative:
                    end = (cursor[0] + end[0], cursor[1] + end[1])
                path.points.extend(_arc_points(cursor, rx, ry, phi, large, sweep, end))
                cursor = end
                prev_cubic = prev_quad = None
            else:  # pragma: no cover - the token regex excludes other letters
                raise ValueError(f"unsupported path command {command!r}")

            # Curves and arcs extend the point list themselves; the straight
            # commands only move the cursor, so record where it landed.
            if command in "LHV":
                path.points.append(cursor)

    return [path for path in subpaths if len(path.points) > 1 or path.closed]


def circle_path(cx: float, cy: float, r: float) -> List[SubPath]:
    """A circle as two flattened half-arcs, so round icons stay truly round."""
    left, right = (cx - r, cy), (cx + r, cy)
    upper = _arc_points(left, r, r, 0.0, False, True, right)
    lower = _arc_points(right, r, r, 0.0, False, True, left)
    return [SubPath(points=[left] + upper + lower, closed=True)]


def ellipse_path(cx: float, cy: float, rx: float, ry: float) -> List[SubPath]:
    left, right = (cx - rx, cy), (cx + rx, cy)
    upper = _arc_points(left, rx, ry, 0.0, False, True, right)
    lower = _arc_points(right, rx, ry, 0.0, False, True, left)
    return [SubPath(points=[left] + upper + lower, closed=True)]


def rounded_rect_path(
    x: float, y: float, width: float, height: float, rx: float, ry: float
) -> List[SubPath]:
    """A rectangle whose corners are quarter arcs; `rx`/`ry` may be 0."""
    if width <= 0 or height <= 0:
        return []
    rx = max(0.0, min(rx, width / 2.0))
    ry = max(0.0, min(ry, height / 2.0))
    if rx == 0 or ry == 0:
        return [SubPath(points=[(x, y), (x + width, y), (x + width, y + height), (x, y + height)], closed=True)]

    # Walk the outline clockwise: straight edge, corner arc, straight edge, ...
    # `curved` marks the four corner runs, which are quarter arcs of rx/ry.
    corners = [
        ((x + width - rx, y), False),                       # top edge
        ((x + width, y + ry), True),                        # top-right corner
        ((x + width, y + height - ry), False),              # right edge
        ((x + width - rx, y + height), True),               # bottom-right corner
        ((x + rx, y + height), False),                      # bottom edge
        ((x, y + height - ry), True),                       # bottom-left corner
        ((x, y + ry), False),                               # left edge
        ((x + rx, y), True),                                # top-left corner
    ]
    outline: List[Point] = [(x + rx, y)]
    cursor = outline[0]
    for end_point, curved in corners:
        if curved:
            outline.extend(_arc_points(cursor, rx, ry, 0.0, False, True, end_point))
        else:
            outline.append(end_point)
        cursor = end_point
    return [SubPath(points=outline, closed=True)]


def points_path(data: str, close: bool) -> List[SubPath]:
    """Parse a `points` attribute (polyline / polygon) into one sub-path."""
    values = [float(value) for value in re.findall(_NUMBER, data or "")]
    paired = [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]
    if len(paired) < 2:
        return []
    return [SubPath(points=paired, closed=close)]
