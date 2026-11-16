"""Minimal SVG-to-PNG rasteriser used to build the CyberSyn icon set.

Only the slice of SVG the icon set actually uses is supported: `path`,
`circle`, `rect` (with rounded corners), `ellipse`, `line`, `polyline` and
`polygon`, with `stroke`, `stroke-width`, `fill`, `stroke-linecap` and
`stroke-linejoin`. Anything richer belongs in a real renderer; keeping the
scope small keeps the tool dependency-free apart from Pillow.

    from icons import Svg, Raster
    icon = Svg.from_string(markup)
    Raster.render(icon, size=72).save("shield.png")
"""

from .geometry import SubPath, flatten_path
from .raster import Raster
from .svgfile import Svg, Shape

__all__ = ["Svg", "Shape", "Raster", "SubPath", "flatten_path"]
