"""A bring-up test card for the physical panel.

Run this before trusting the dashboard on real hardware:

    python main.py --test-pattern

It answers the questions you cannot answer from a PNG on a laptop:

* which way up is the panel mounted, and is EPAPER_ROTATE right;
* how much of the edge does the picture frame's bezel actually cover;
* what is the smallest font still readable from across the room;
* do the icons survive on e-ink at the sizes the dashboard uses.
"""

from typing import List

from PIL import Image, ImageDraw, ImageFont

import config
import icons
import render

BLACK = render.FOREGROUND
WHITE = render.BACKGROUND


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = config.FONT_BOLD_PATH if bold else config.FONT_REGULAR_PATH
    return render._load_font(path, size)


def _corner_labels(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Name every corner, so a rotated panel is instantly obvious."""
    font = _font(13, bold=True)
    inset = 8
    for text, xy, anchor in (
        ("LINKSBOVEN", (inset, inset), "la"),
        ("RECHTSBOVEN", (width - inset, inset), "ra"),
        ("LINKSONDER", (inset, height - inset), "ld"),
        ("RECHTSONDER", (width - inset, height - inset), "rd"),
    ):
        draw.text(xy, text, font=font, fill=BLACK, anchor=anchor)


def _arrow_up(draw: ImageDraw.ImageDraw, cx: int, y: int, size: int) -> None:
    half = size // 2
    draw.polygon(
        [(cx, y), (cx - half, y + half), (cx + half, y + half)], fill=BLACK
    )
    draw.rectangle([cx - half // 3, y + half, cx + half // 3, y + size], fill=BLACK)


def build_test_card() -> Image.Image:
    """Render the bring-up card at the dashboard's own canvas size."""
    width, height = render.WIDTH, render.HEIGHT
    image = Image.new("1", (width, height), WHITE)
    draw = ImageDraw.Draw(image)

    # Outermost pixel ring: if any side of this is missing on the panel, the
    # frame is cropping the picture there.
    draw.rectangle([0, 0, width - 1, height - 1], outline=BLACK, width=1)
    # The dashboard's own safe area.
    draw.rectangle(
        [render.MARGIN, render.MARGIN_V, width - render.MARGIN, height - render.MARGIN_V],
        outline=BLACK,
        width=1,
    )
    _corner_labels(draw, width, height)

    y = render.MARGIN_V + 14
    _arrow_up(draw, width // 2, y, 34)
    draw.text(
        (width // 2, y + 42), "BOVEN", font=_font(20, bold=True), fill=BLACK, anchor="ma"
    )
    y += 74

    draw.text(
        (width // 2, y),
        f"{width}x{height}  rotate={config.EPAPER_ROTATE}°",
        font=_font(15),
        fill=BLACK,
        anchor="ma",
    )
    y += 28
    render._divider(draw, y)
    y += 14

    # Legibility ladder: read it from where the frame will hang and note the
    # smallest line you can still make out.
    draw.text((render.MARGIN, y), "Leesbaarheid", font=_font(15, bold=True), fill=BLACK)
    y += 22
    for size in (12, 15, 17, 19, 24):
        draw.text(
            (render.MARGIN, y),
            f"{size}px  Voorbeeldtekst 0123456789",
            font=_font(size),
            fill=BLACK,
        )
        y += size + 8
    y += 4
    render._divider(draw, y)
    y += 14

    # Numerals, at the sizes the dashboard actually uses them.
    draw.text((render.MARGIN, y), "Cijfers (Oswald)", font=_font(15, bold=True), fill=BLACK)
    y += 20
    big = render._load_font(config.FONT_NUMBER_PATH, 60, "SemiBold")
    small = render._load_font(config.FONT_NUMBER_PATH, 19, "SemiBold")
    draw.text((render.MARGIN, y), "-3 22 18°", font=big, fill=BLACK)
    # Right-aligned so it cannot collide with the big figures beside it.
    draw.text(
        (width - render.MARGIN, y + 26), "09:30  21:45", font=small, fill=BLACK,
        anchor="ra",
    )
    y += 76
    render._divider(draw, y)
    y += 14

    # Every icon at both sizes used on the dashboard.
    draw.text((render.MARGIN, y), "Iconen", font=_font(15, bold=True), fill=BLACK)
    y += 22
    names: List[str] = list(icons._BUILDERS)
    per_row = 6
    for row_start in range(0, len(names), per_row):
        row = names[row_start : row_start + per_row]
        step = (width - 2 * render.MARGIN) / per_row
        for index, name in enumerate(row):
            x = render.MARGIN + step * index + (step - render.ICON_LARGE) / 2
            icons.draw_icon(draw, name, x, y, render.ICON_LARGE)
            icons.draw_icon(
                draw,
                name,
                x + (render.ICON_LARGE - render.ICON_SMALL) / 2,
                y + render.ICON_LARGE + 4,
                render.ICON_SMALL,
            )
        y += render.ICON_LARGE + render.ICON_SMALL + 14

    # A solid block and a fine comb: the block shows up ghosting from the
    # previous image, the comb shows whether 1px lines survive on the panel.
    render._divider(draw, y)
    y += 10
    # Caption above the swatches, so it cannot run into the corner labels.
    draw.text(
        (render.MARGIN, y),
        "Vlak: ghosting?   Kam: halen 1px lijnen het?",
        font=_font(12),
        fill=BLACK,
    )
    y += 18
    block_bottom = height - render.MARGIN_V - 6
    draw.rectangle([render.MARGIN, y, width // 2 - 6, block_bottom], fill=BLACK)
    for index in range(0, (width // 2) - render.MARGIN - 10, 4):
        x = width // 2 + 6 + index
        draw.line([(x, y), (x, block_bottom)], fill=BLACK, width=1)

    return image


if __name__ == "__main__":
    from display.epaper_output import output_image

    output_image(build_test_card(), mode="preview")
