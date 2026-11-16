"""Draw an `Svg` onto an anti-aliased RGBA image with Pillow.

Pillow's `ImageDraw.line` has no round caps or round joins, and its own
anti-aliasing is only adequate at large sizes. So: draw every icon at
`oversample` times its final size, emulate round caps and joins by stamping
a filled disc at each vertex, then downsample with LANCZOS. At 72px output
the result is indistinguishable from a vector render.
"""

from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageDraw

from .svgfile import Svg


class Raster:
    def __init__(self, oversample: int = 6):
        if oversample < 1:
            raise ValueError("oversample must be at least 1")
        self.oversample = oversample

    def render(
        self,
        document: Svg,
        size: int = 72,
        colour: Tuple[int, int, int] = (56, 189, 248),
        background: Tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> Image.Image:
        """Draw `document` into a square `size` x `size` RGBA image."""
        if size < 1:
            raise ValueError("size must be at least 1")

        scale = size * self.oversample / max(document.width, document.height)
        big = size * self.oversample
        image = Image.new("RGBA", (big, big), background)
        painter = ImageDraw.Draw(image)

        for shape in document.shapes:
            fill = shape.fill or colour
            stroke = shape.stroke or colour
            width = max(shape.width * scale, 1.0)

            for subpath in shape.subpaths:
                points = [(x * scale, y * scale) for x, y in subpath.points]
                if len(points) < 2:
                    continue
                if shape.fill is not None and subpath.closed:
                    painter.polygon(points, fill=fill + (255,))
                if shape.stroke is not None:
                    painter.line(points, fill=stroke + (255,), width=int(round(width)), joint="curve")
                    if shape.round_caps:
                        self._round_joins(painter, points, stroke, width)
                    if subpath.closed:
                        painter.line(
                            [points[-1], points[0]],
                            fill=stroke + (255,),
                            width=int(round(width)),
                        )

        if self.oversample > 1:
            image = image.resize((size, size), Image.LANCZOS)
        return image

    @staticmethod
    def _round_joins(
        painter: ImageDraw.ImageDraw,
        points,
        colour: Tuple[int, int, int],
        width: float,
    ) -> None:
        """Stamp a disc at every vertex: that is a round cap and a round join."""
        radius = max(width / 2.0 - 0.5, 0.5)
        paint = colour + (255,)
        for x, y in points:
            painter.ellipse(
                [x - radius, y - radius, x + radius, y + radius],
                fill=paint,
            )
