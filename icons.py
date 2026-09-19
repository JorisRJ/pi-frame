"""Outline weather icons, drawn with Pillow for a 1-bit e-paper panel.

No icon font and no image assets. Each icon is built as a filled silhouette and
then reduced to its outline morphologically: `silhouette - erode(silhouette)`.
Drawing overlapping circles with `outline=` instead would leave the seams where
the shapes cross visible inside the icon; eroding the *union* gives one clean
contour, so a cloud reads as a single object.

Three things do most of the work for how they look:

* every stroke has round caps (`_cap_line`), so rays, raindrops and fog lines
  end in a dot rather than a chopped-off rectangle;
* the cloud's base rectangle spans exactly between the centres of the outer
  bumps, so the bottom edge is flat and the corners are true quarter-circles;
* everything is rasterised at SUPERSAMPLE times the final size and box-filtered
  down before thresholding, which places curves far more accurately than
  drawing a 26px circle directly.

The panel has two ink states, so the result is still pure black and white.
Icons are cached per (name, size) - the dashboard asks for the same handful
every run.
"""

import math
from functools import lru_cache
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

BLACK = 0
WHITE = 255

# Rasterisation scale. 4 is the knee of the curve: 6 changes a handful of edge
# pixels for roughly twice the erosion work.
SUPERSAMPLE = 4
# Coverage needed for a pixel to become ink. Below 0.5 so hairlines survive.
_THRESHOLD = 0.42 * 255

# --- Icon names -------------------------------------------------------------
CLEAR_DAY = "clear_day"
CLEAR_NIGHT = "clear_night"
PARTLY_DAY = "partly_day"
PARTLY_NIGHT = "partly_night"
CLOUDY = "cloudy"
FOG = "fog"
DRIZZLE = "drizzle"
RAIN = "rain"
HEAVY_RAIN = "heavy_rain"
SNOW = "snow"
THUNDER = "thunder"

# WMO weather code -> icon name. Codes that only differ in severity share an
# icon where the outlines would be indistinguishable at this size.
_CODE_ICONS = {
    0: "clear",
    1: "clear",
    2: "partly",
    3: CLOUDY,
    45: FOG,
    48: FOG,
    51: DRIZZLE,
    53: DRIZZLE,
    55: DRIZZLE,
    56: DRIZZLE,
    57: DRIZZLE,
    61: RAIN,
    63: RAIN,
    65: HEAVY_RAIN,
    66: RAIN,
    67: HEAVY_RAIN,
    71: SNOW,
    73: SNOW,
    75: SNOW,
    77: SNOW,
    80: RAIN,
    81: RAIN,
    82: HEAVY_RAIN,
    85: SNOW,
    86: SNOW,
    95: THUNDER,
    96: THUNDER,
    99: THUNDER,
}


def icon_for_code(code: Any, is_day: bool = True) -> str:
    """Map a WMO weather code to an icon name, picking the sun/moon variant."""
    try:
        name = _CODE_ICONS[int(code)]
    except (TypeError, ValueError, KeyError):
        return CLOUDY  # neutral stand-in for an unknown code
    if name == "clear":
        return CLEAR_DAY if is_day else CLEAR_NIGHT
    if name == "partly":
        return PARTLY_DAY if is_day else PARTLY_NIGHT
    return name


# --- Raster helpers ---------------------------------------------------------


def _layer(px: int) -> Image.Image:
    """A blank working layer: ink is white (255) on black, stencilled at the end."""
    return Image.new("L", (px, px), 0)


def _erode(mask: Image.Image, radius: int) -> Image.Image:
    for _ in range(max(0, radius)):
        mask = mask.filter(ImageFilter.MinFilter(3))
    return mask


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    for _ in range(max(0, radius)):
        mask = mask.filter(ImageFilter.MaxFilter(3))
    return mask


def _outline(mask: Image.Image, stroke: int) -> Image.Image:
    """The border band of a filled shape: what is left after eroding it away."""
    return ImageChops.subtract(mask, _erode(mask, stroke))


def _union(*layers: Image.Image) -> Image.Image:
    result = layers[0]
    for layer in layers[1:]:
        result = ImageChops.lighter(result, layer)
    return result


def _knock_out(base: Image.Image, mask: Image.Image) -> Image.Image:
    """Erase `mask` from `base`, so a foreground shape can hide what is behind."""
    return ImageChops.subtract(base, mask)


def _cap_line(drawer: ImageDraw.ImageDraw, p0, p1, width: int) -> None:
    """A stroke with round caps. Pillow's line ends are square, which reads as
    chopped-off at icon scale; a disc at each end rounds them."""
    drawer.line([p0, p1], fill=255, width=width)
    radius = width / 2
    for x, y in (p0, p1):
        drawer.ellipse([x - radius, y - radius, x + radius, y + radius], fill=255)


# --- Shapes -----------------------------------------------------------------

# A cloud as three bumps over a flat base, in unit coordinates of its own box.
# The base spans centre-to-centre of the outer bumps, so the bottom edge is flat
# and its corners are exactly the bumps' quarter-circles - no lumpy join.
_BUMP_LEFT = (0.00, 0.40, 0.46, 1.00)
_BUMP_MID = (0.20, 0.00, 0.76, 0.80)
_BUMP_RIGHT = (0.58, 0.32, 1.00, 1.00)
_CLOUD_SHAPES = (
    ("ellipse", _BUMP_LEFT),
    ("ellipse", _BUMP_MID),
    ("ellipse", _BUMP_RIGHT),
    ("rect", (0.23, 0.70, 0.79, 1.00)),
)


def _cloud_mask(px: int, box) -> Image.Image:
    """Filled cloud silhouette. `box` is (x, y, w, h) in unit coordinates."""
    x, y, width, height = (value * px for value in box)
    mask = _layer(px)
    drawer = ImageDraw.Draw(mask)
    for kind, (x0, y0, x1, y1) in _CLOUD_SHAPES:
        shape = [x + x0 * width, y + y0 * height, x + x1 * width, y + y1 * height]
        if kind == "ellipse":
            drawer.ellipse(shape, fill=255)
        else:
            drawer.rectangle(shape, fill=255)
    return mask


def _disc_mask(px: int, cx: float, cy: float, radius: float) -> Image.Image:
    mask = _layer(px)
    drawer = ImageDraw.Draw(mask)
    cx, cy, radius = cx * px, cy * px, radius * px
    drawer.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    return mask


def _crescent_mask(
    px: int, cx: float, cy: float, radius: float, bite: tuple
) -> Image.Image:
    """A moon: a disc with a second disc bitten out of it.

    `bite` is the offset of the removed disc in radii. Behind a cloud, bite the
    lower left so the horn that stays visible sticks out above the cloud.
    """
    moon = _disc_mask(px, cx, cy, radius)
    bitten = _disc_mask(px, cx + radius * bite[0], cy + radius * bite[1], radius * 0.88)
    return _knock_out(moon, bitten)


def _rays(px: int, cx: float, cy: float, radius: float, stroke: int) -> Image.Image:
    layer = _layer(px)
    drawer = ImageDraw.Draw(layer)
    cx, cy, radius = cx * px, cy * px, radius * px
    inner, outer = radius * 1.52, radius * 2.18
    for step in range(8):
        angle = math.radians(step * 45)
        dx, dy = math.cos(angle), math.sin(angle)
        _cap_line(
            drawer,
            (cx + dx * inner, cy + dy * inner),
            (cx + dx * outer, cy + dy * outer),
            stroke,
        )
    return layer


def _drops(
    px: int, top: float, count: int, length: float, stroke: int, spread=(0.20, 0.80)
) -> Image.Image:
    """Slanted rain streaks, evenly spread under the cloud."""
    layer = _layer(px)
    drawer = ImageDraw.Draw(layer)
    start, end = spread
    step = (end - start) / max(1, count - 1) if count > 1 else 0
    for index in range(count):
        x = (start + step * index) * px
        _cap_line(
            drawer, (x, top * px), (x - 0.075 * px, (top + length) * px), stroke
        )
    return layer


def _flakes(px: int, top: float, stroke: int) -> Image.Image:
    """Six-armed flakes: three crossed strokes with round tips."""
    layer = _layer(px)
    drawer = ImageDraw.Draw(layer)
    arm = 0.086 * px
    for index in range(3):
        cx = (0.26 + 0.24 * index) * px
        cy = (top + (0.055 if index == 1 else 0.0)) * px
        for angle in (90, 30, 150):
            radians = math.radians(angle)
            dx, dy = math.cos(radians) * arm, math.sin(radians) * arm
            _cap_line(drawer, (cx - dx, cy - dy), (cx + dx, cy + dy), stroke)
    return layer


# Lightning bolt in unit coordinates of the icon box. Drawn filled: an outlined
# zigzag this narrow closes up into a smudge at 26px.
_BOLT = (
    (0.57, 0.52),
    (0.33, 0.85),
    (0.47, 0.85),
    (0.40, 1.02),
    (0.67, 0.69),
    (0.52, 0.69),
)


def _bolt(px: int) -> Image.Image:
    layer = _layer(px)
    drawer = ImageDraw.Draw(layer)
    drawer.polygon([(x * px, y * px) for x, y in _BOLT], fill=255)
    return layer


def _cloud_in_front(
    behind: Image.Image, px: int, box, stroke: int, gap: int
) -> Image.Image:
    """Put an outlined cloud in front of `behind`, clearing a gap around it."""
    solid = _cloud_mask(px, box)
    cleared = _knock_out(behind, _dilate(solid, gap))
    return _union(cleared, _outline(solid, stroke))


# --- Icon builders ----------------------------------------------------------
# Each returns a supersampled layer with white ink on black.

_PARTLY_CLOUD = (0.00, 0.42, 0.78, 0.46)
_PRECIP_CLOUD = (0.04, 0.06, 0.92, 0.46)


def _build_clear_day(px, stroke):
    centre, radius = (0.50, 0.50), 0.20
    sun = _outline(_disc_mask(px, *centre, radius), stroke)
    return _union(sun, _rays(px, *centre, radius, stroke))


def _build_clear_night(px, stroke):
    return _outline(_crescent_mask(px, 0.52, 0.50, 0.38, bite=(0.48, -0.32)), stroke)


def _build_partly_day(px, stroke):
    centre, radius = (0.70, 0.26), 0.155
    behind = _union(
        _outline(_disc_mask(px, *centre, radius), stroke),
        _rays(px, *centre, radius, stroke),
    )
    return _cloud_in_front(behind, px, _PARTLY_CLOUD, stroke, gap=max(2, stroke))


def _build_partly_night(px, stroke):
    moon = _crescent_mask(px, 0.71, 0.27, 0.235, bite=(-0.42, 0.46))
    return _cloud_in_front(
        _outline(moon, stroke), px, _PARTLY_CLOUD, stroke, gap=max(2, stroke)
    )


def _build_cloudy(px, stroke):
    return _outline(_cloud_mask(px, (0.02, 0.24, 0.96, 0.52)), stroke)


def _build_fog(px, stroke):
    cloud = _outline(_cloud_mask(px, (0.04, 0.10, 0.92, 0.44)), stroke)
    lines = _layer(px)
    drawer = ImageDraw.Draw(lines)
    for index, (x0, x1) in enumerate(((0.12, 0.82), (0.22, 0.92), (0.12, 0.68))):
        y = (0.72 + 0.13 * index) * px
        _cap_line(drawer, (x0 * px, y), (x1 * px, y), stroke)
    return _union(cloud, lines)


def _build_drizzle(px, stroke):
    cloud = _outline(_cloud_mask(px, _PRECIP_CLOUD), stroke)
    return _union(cloud, _drops(px, 0.66, 2, 0.14, stroke, spread=(0.34, 0.62)))


def _build_rain(px, stroke):
    cloud = _outline(_cloud_mask(px, _PRECIP_CLOUD), stroke)
    return _union(cloud, _drops(px, 0.64, 3, 0.21, stroke, spread=(0.26, 0.72)))


def _build_heavy_rain(px, stroke):
    cloud = _outline(_cloud_mask(px, _PRECIP_CLOUD), stroke)
    return _union(cloud, _drops(px, 0.62, 4, 0.29, stroke, spread=(0.22, 0.78)))


def _build_snow(px, stroke):
    cloud = _outline(_cloud_mask(px, _PRECIP_CLOUD), stroke)
    return _union(cloud, _flakes(px, 0.78, max(2, round(stroke * 0.85))))


def _build_thunder(px, stroke):
    cloud = _outline(_cloud_mask(px, (0.04, 0.04, 0.92, 0.44)), stroke)
    return _union(cloud, _bolt(px))


_BUILDERS = {
    CLEAR_DAY: _build_clear_day,
    CLEAR_NIGHT: _build_clear_night,
    PARTLY_DAY: _build_partly_day,
    PARTLY_NIGHT: _build_partly_night,
    CLOUDY: _build_cloudy,
    FOG: _build_fog,
    DRIZZLE: _build_drizzle,
    RAIN: _build_rain,
    HEAVY_RAIN: _build_heavy_rain,
    SNOW: _build_snow,
    THUNDER: _build_thunder,
}


def _stroke_width(size: int) -> int:
    """Outline weight at the final size, before supersampling."""
    return max(2, round(size * 0.05))


@lru_cache(maxsize=None)
def render_icon(name: str, size: int) -> Image.Image:
    """Build the named icon as a mode "1" stencil: set pixels are the ink."""
    builder = _BUILDERS.get(name)
    if builder is None:
        raise KeyError(f"unknown weather icon: {name or '(none)'}")

    px = size * SUPERSAMPLE
    layer = builder(px, _stroke_width(size) * SUPERSAMPLE)
    # BOX is an area average, so each final pixel gets the true ink coverage of
    # its supersampled cell; thresholding that keeps stroke weight even.
    small = layer.resize((size, size), Image.Resampling.BOX)
    return small.point(lambda value: 255 if value >= _THRESHOLD else 0).convert("1")


def draw_icon(
    draw: ImageDraw.ImageDraw, name: str, x: float, y: float, size: int
) -> None:
    """Stamp the named icon with its top-left corner at (x, y)."""
    draw.bitmap((round(x), round(y)), render_icon(name, size), fill=BLACK)


def draw_icon_for_code(
    draw: ImageDraw.ImageDraw,
    code: Any,
    is_day: bool,
    x: float,
    y: float,
    size: int,
) -> None:
    """Convenience wrapper: map a WMO code to an icon and draw it."""
    draw_icon(draw, icon_for_code(code, is_day), x, y, size)


if __name__ == "__main__":
    # Contact sheet of every icon at both sizes used in the dashboard:
    #   python icons.py   ->   output/icons.png
    # The two sizes mirror ICON_LARGE / ICON_SMALL in render.py.
    from PIL import ImageFont

    import config

    big, small, pad = 78, 26, 26
    names = list(_BUILDERS)
    width = pad + len(names) * (big + pad)
    image = Image.new("1", (width, 210), WHITE)
    sheet = ImageDraw.Draw(image)
    try:
        label_font = ImageFont.truetype(str(config.FONT_REGULAR_PATH), 11)
    except OSError:
        label_font = ImageFont.load_default()

    for index, name in enumerate(names):
        x = pad + index * (big + pad)
        draw_icon(sheet, name, x, 16, big)
        draw_icon(sheet, name, x + (big - small) / 2, 122, small)
        sheet.text((x + big / 2, 170), name, font=label_font, fill=BLACK, anchor="ma")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / "icons.png"
    image.save(path)
    print(f"Icon sheet written to: {path.resolve()}")
