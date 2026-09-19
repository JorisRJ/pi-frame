"""Layout and drawing for the dashboard.

This module knows nothing about e-paper hardware: it produces a plain Pillow
Image. `display/epaper_output.py` decides what happens to that image.

Every block is drawn by a `draw_*_block(draw, y, data, fonts) -> int` function
that returns the y-offset below itself, so blocks stack and can be reordered or
swapped out (e.g. a future MQTT-driven "screen mode") without touching layout
maths elsewhere.

Blocks claim vertical space in priority order, each taking what it needs before
the next one sees what is left:

1. weather - fixed height, always drawn in full;
2. "Vandaag" - up to CALENDAR_EVENTS_TODAY events;
3. "Morgen" - up to CALENDAR_EVENTS_TOMORROW events;
4. news - no cap of its own, it fills whatever remains.

Every block also measures each row before drawing it and stops once a row would
cross the bottom margin, so a heavy agenda can squeeze the news feed out but
nothing ever runs off the panel or is clipped mid-line.
"""

import logging
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

import config
import icons
from icons import draw_icon_for_code
from sources.calendar_feed import DAY_LABELS, day_offset, format_event_clock

log = logging.getLogger(__name__)

# --- Canvas -----------------------------------------------------------------
# Portrait 480x800: the Waveshare 7.5" V2 panel is natively 800x480 landscape
# and is rotated 90 degrees in its frame.
#
# Mode "1" (1-bit) on purpose: the panel has exactly two states per pixel, so
# rendering in 1-bit means the preview PNG is pixel-for-pixel what the hardware
# shows. Drawing in greyscale instead would look nicer on screen and then get
# Floyd-Steinberg dithered into fuzzy speckle by the driver's getbuffer(). There
# is no muted grey for the same reason - hierarchy comes from size and weight.
WIDTH = 480
HEIGHT = 800
BACKGROUND = 255  # white
FOREGROUND = 0  # black

# --- Spacing ----------------------------------------------------------------
MARGIN = 20  # left and right
MARGIN_V = 40  # top and bottom
BLOCK_GAP = 20
LINE_GAP = 6

# --- Font sizes (tune these against real hardware) --------------------------
FONT_TEMP = 76  # Oswald is condensed, so it can carry more size than DejaVu
FONT_SECTION = 24
FONT_UNIT = 24  # the "degrees C" beside the big temperature
FONT_FEELS = 16
FONT_EVENT = 20
FONT_NEWS_TITLE = 19
FONT_NEWS_META = 12
FONT_HOUR_TIME = 17
FONT_HOUR_TEMP = 19

# --- Weather block ----------------------------------------------------------
ICON_LARGE = 78  # fallback only; the icon is normally sized to the temperature
ICON_SMALL = 26  # per-column icon in the forecast strip
ICON_GAP = 14  # clearance between the description text and the large icon
WEATHER_DESC_GAP = 8  # "degrees C" -> description
WEATHER_FEELS_GAP = 4
WEATHER_RULE_GAP = 12  # tallest column -> the rule under the header
HOURLY_ICON_GAP = 6  # time label -> icon
HOURLY_TEMP_GAP = 4  # icon -> temperature
# The strip's height is measured from what is actually drawn, not guessed: the
# two faces have different ink heights for the same nominal size.

# --- Agenda block -----------------------------------------------------------
SECTION_HEADER_HEIGHT = FONT_SECTION + 4 + 10  # label, rule, gap below it
EVENT_TIME_MIN = 62  # fits "09:30"; grows for "Hele dag" when one is shown
EVENT_TIME_PADDING = 14
EVENT_LINE_HEIGHT = 24
EVENT_GAP = 8
EVENT_MAX_LINES = 2

# --- News block -------------------------------------------------------------
NEWS_LINE_HEIGHT = 23
NEWS_MAX_LINES = 2
NEWS_META_GAP = 4
NEWS_ITEM_GAP = 10


def _load_font(path, size: int, weight: str = None) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, falling back to something usable if it is missing.

    `weight` names an instance on a variable font's weight axis ("SemiBold").
    Selecting one needs a FreeType build with variable-font support, which the
    Pi may not have, so a failure there is logged and leaves the font at its
    default instance rather than taking the dashboard down.

    A missing font file should not take the dashboard down either, but it earns
    a loud warning: the fallback looks noticeably worse.
    """
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError:
        log.warning("Font not found at %s - falling back to the default font", path)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1 has no size argument
            return ImageFont.load_default()

    if weight:
        try:
            font.set_variation_by_name(weight)
        except Exception as exc:  # noqa: BLE001 - any FreeType complaint is fatal here
            log.warning(
                "Could not select weight %r from %s (%s) - using its default instance",
                weight,
                path.name if hasattr(path, "name") else path,
                exc,
            )
    return font


class Fonts:
    """Pre-loaded font set, so each block does not re-open the .ttf files."""

    def __init__(self):
        regular = config.FONT_REGULAR_PATH
        bold = config.FONT_BOLD_PATH
        number = config.FONT_NUMBER_PATH

        # Text: DejaVu Sans.
        self.section = _load_font(bold, FONT_SECTION)
        self.body = _load_font(regular, FONT_EVENT)
        self.event = _load_font(regular, FONT_EVENT)
        self.feels = _load_font(regular, FONT_FEELS)
        self.news_title = _load_font(regular, FONT_NEWS_TITLE)
        self.news_meta = _load_font(regular, FONT_NEWS_META)

        # Numerals: Oswald. Condensed, so temperatures and times read as
        # instrument readings rather than as more body copy.
        self.temp = _load_font(number, FONT_TEMP, "SemiBold")
        self.unit = _load_font(number, FONT_UNIT, "Medium")
        self.hour_time = _load_font(number, FONT_HOUR_TIME, "Regular")
        self.hour_temp = _load_font(number, FONT_HOUR_TEMP, "SemiBold")
        # The agenda time column also carries "Hele dag", so the whole column
        # is set in Oswald to keep it visually one column.
        self.event_time = _load_font(number, FONT_EVENT, "SemiBold")


# --- Text helpers -----------------------------------------------------------


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Shorten text with a trailing ellipsis so it fits within max_width."""
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return text.rstrip() + ellipsis


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int
) -> List[str]:
    """Word-wrap text to at most `max_lines`, ellipsising whatever is left over.

    Wrapping rather than truncating on the first line fits noticeably more of a
    headline in the same column; the ellipsis then only appears when a title is
    genuinely too long for its box.
    """
    lines: List[str] = []
    current = ""
    for word in (text or "").split():
        candidate = f"{current} {word}".strip()
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if not lines:
        return [""]

    if len(lines) > max_lines:
        # Fold everything that did not fit back into the final visible line, so
        # the ellipsis lands after as many words as will fit.
        kept = lines[: max_lines - 1]
        kept.append(" ".join(lines[max_lines - 1 :]))
        lines = kept
    # A single word wider than the column still needs hard truncation.
    return [truncate(draw, line, font, max_width) for line in lines]


def _ink_box(draw: ImageDraw.ImageDraw, text: str, font, anchor: str = "la"):
    return draw.textbbox((0, 0), text, font=font, anchor=anchor)


def _ink_height_of(
    draw: ImageDraw.ImageDraw, text: str, font, anchor: str = "la"
) -> int:
    box = _ink_box(draw, text, font, anchor)
    return box[3] - box[1]


def _draw_ink_top(
    draw: ImageDraw.ImageDraw, xy, text: str, font, anchor: str = "la"
) -> int:
    """Draw text so the top of its *ink* lands at xy[1]. Returns its ink height.

    Oswald carries far more ascender padding than DejaVu (ascent 22 vs 17 at
    18px, and 23px of dead space above "22" at 60px), so placing numbers by the
    font's ascender would drop them relative to the text beside them and waste
    vertical space. Digits have a constant ink top, so aligning on ink is stable
    for them in a way it would not be for arbitrary words.
    """
    x, y = xy
    box = _ink_box(draw, text, font, anchor)
    draw.text((x, y - box[1]), text, font=font, fill=FOREGROUND, anchor=anchor)
    return box[3] - box[1]


def _fits(y: int, needed: int) -> bool:
    """Is there room for `needed` more pixels above the bottom margin?"""
    return y + needed <= HEIGHT - MARGIN_V


def _divider(draw: ImageDraw.ImageDraw, y: int) -> None:
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=FOREGROUND, width=1)


def _section_header(draw: ImageDraw.ImageDraw, y: int, label: str, fonts: Fonts) -> int:
    """A section label with a rule under it. Returns the y below the rule."""
    draw.text((MARGIN, y), label, font=fonts.section, fill=FOREGROUND)
    y += FONT_SECTION + 4
    _divider(draw, y)
    return y + 10


def _format_temp(value) -> str:
    return "--" if value is None else str(round(value))


# --- Blocks -----------------------------------------------------------------


def draw_weather_block(
    draw: ImageDraw.ImageDraw, y: int, weather: Dict[str, Any], fonts: Fonts
) -> int:
    """Current temperature, conditions and icon, then a stepped forecast strip."""
    temp_now = weather.get("temp_now")
    temp_text = _format_temp(temp_now) if temp_now is not None else ""

    code = weather.get("code")
    if code is not None:
        # Match the icon's ink height to the temperature's, so the two read as
        # one line. Sizing by the icon's box instead would leave a cloud looking
        # half the height of the figures, since icons fill their boxes by very
        # different amounts.
        name = icons.icon_for_code(code, weather.get("is_day", True))
        target = (
            _ink_height_of(draw, temp_text, fonts.temp) if temp_text else ICON_LARGE
        )
        size = icons.size_for_ink_height(name, target)
        box = icons.ink_box(name, size)
        # Placed by its ink too: right edge on the margin, top level with the
        # top of the figures.
        icons.draw_icon(draw, name, WIDTH - MARGIN - box[2], y - box[1], size)
        text_limit = WIDTH - MARGIN - (box[2] - box[0]) - ICON_GAP
    else:
        text_limit = WIDTH - MARGIN

    if temp_now is None:
        # No reading: show the message on its own rather than a giant "--",
        # which has no cap height to align anything else against.
        temp_height, unit_height, text_x = 0, 0, MARGIN
    else:
        temp_height = _draw_ink_top(draw, (MARGIN, y), temp_text, fonts.temp)
        text_x = MARGIN + _text_width(draw, temp_text, fonts.temp) + 12
        # The unit's ink top is aligned with the numerals' ink top, so "degrees
        # C" sits flush with the top of the figures rather than floating.
        unit_height = _draw_ink_top(draw, (text_x, y), "°C", fonts.unit)

    desc_y = y + unit_height + WEATHER_DESC_GAP
    draw.text(
        (text_x, desc_y),
        truncate(draw, weather.get("description", ""), fonts.body, text_limit - text_x),
        font=fonts.body,
        fill=FOREGROUND,
    )
    text_bottom = desc_y + FONT_EVENT
    feels = weather.get("feels_like")
    if feels is not None:
        feels_y = desc_y + FONT_EVENT + WEATHER_FEELS_GAP
        draw.text(
            (text_x, feels_y),
            f"Voelt als {_format_temp(feels)}°",
            font=fonts.feels,
            fill=FOREGROUND,
        )
        text_bottom = feels_y + FONT_FEELS

    # Whichever column is taller sets where the rule goes.
    y = max(y + temp_height, text_bottom) + WEATHER_RULE_GAP
    _divider(draw, y)
    y += 12

    hourly: List[Dict[str, Any]] = weather.get("hourly") or []
    if hourly:
        column_width = (WIDTH - 2 * MARGIN) / len(hourly)
        icon_y = (
            y + _ink_height_of(draw, "09:00", fonts.hour_time, "ma") + HOURLY_ICON_GAP
        )
        for index, point in enumerate(hourly):
            center_x = MARGIN + column_width * (index + 0.5)
            _draw_ink_top(draw, (center_x, y), point["time"], fonts.hour_time, "ma")
            if point.get("code") is not None:
                draw_icon_for_code(
                    draw,
                    point["code"],
                    point.get("is_day", True),
                    center_x - ICON_SMALL / 2,
                    icon_y,
                    ICON_SMALL,
                )
            _draw_ink_top(
                draw,
                (center_x, icon_y + ICON_SMALL + HOURLY_TEMP_GAP),
                f"{round(point['temp'])}°",
                fonts.hour_temp,
                "ma",
            )
        y = icon_y + ICON_SMALL + HOURLY_TEMP_GAP + _ink_height_of(
            draw, "18°", fonts.hour_temp
        )
    else:
        draw.text((MARGIN, y), "Geen uurverwachting", font=fonts.feels, fill=FOREGROUND)
        y += FONT_FEELS + LINE_GAP

    return y + BLOCK_GAP


def _event_lines(
    draw: ImageDraw.ImageDraw, event: Dict[str, Any], fonts: Fonts, time_width: int
) -> List[str]:
    """The title lines for one event, wrapped to its column."""
    return wrap_text(
        draw,
        event["title"],
        fonts.event,
        WIDTH - MARGIN - (MARGIN + time_width),
        EVENT_MAX_LINES,
    )


def _event_height(lines: List[str]) -> int:
    """What an event row will claim vertically, measured before it is drawn."""
    return len(lines) * EVENT_LINE_HEIGHT + EVENT_GAP


def _draw_event(
    draw: ImageDraw.ImageDraw,
    y: int,
    event: Dict[str, Any],
    fonts: Fonts,
    time_width: int,
    lines: List[str],
) -> int:
    """One agenda row: bold time on the left, wrapped title on the right."""
    clock = format_event_clock(event["start"], event["all_day"])
    # The time is Oswald and the title DejaVu; sharing the title font's baseline
    # is what makes the two sit on the same line, since their ascents differ.
    baseline = y + fonts.event.getmetrics()[0]
    draw.text(
        (MARGIN, baseline), clock, font=fonts.event_time, fill=FOREGROUND, anchor="ls"
    )

    title_x = MARGIN + time_width
    for line in lines:
        draw.text((title_x, y), line, font=fonts.event, fill=FOREGROUND)
        y += EVENT_LINE_HEIGHT
    return y + EVENT_GAP


def draw_calendar_block(
    draw: ImageDraw.ImageDraw, y: int, calendar: Dict[str, Any], fonts: Fonts
) -> int:
    """A "Vandaag" section and a "Morgen" section, each with its own events."""
    if not calendar.get("ok", False):
        # One honest line beats repeating the same failure under both days.
        y = _section_header(draw, y, "Agenda", fonts)
        message = calendar.get("message") or "Agenda niet beschikbaar"
        draw.text((MARGIN, y), message, font=fonts.event, fill=FOREGROUND)
        return y + EVENT_LINE_HEIGHT + BLOCK_GAP

    # Today is worth more screen than tomorrow, hence the separate caps.
    caps = {0: config.CALENDAR_EVENTS_TODAY, 1: config.CALENDAR_EVENTS_TOMORROW}
    grouped: Dict[int, List[Dict[str, Any]]] = {offset: [] for offset in DAY_LABELS}
    for event in calendar.get("events") or []:
        bucket = grouped.get(day_offset(event["start"]))
        if bucket is not None:
            bucket.append(event)
    for offset in grouped:
        grouped[offset] = grouped[offset][: caps.get(offset, 0)]

    # One column width across both sections keeps the titles aligned; it only
    # widens to fit "Hele dag" on days that actually have an all-day event.
    shown = [event for offset in DAY_LABELS for event in grouped[offset]]
    time_width = max(
        EVENT_TIME_MIN,
        max(
            (
                _text_width(
                    draw,
                    format_event_clock(e["start"], e["all_day"]),
                    fonts.event_time,
                )
                for e in shown
            ),
            default=0,
        )
        + EVENT_TIME_PADDING,
    )

    for offset, label in sorted(DAY_LABELS.items()):
        if not _fits(y, SECTION_HEADER_HEIGHT + EVENT_LINE_HEIGHT):
            break  # not even a header plus one line would fit

        y = _section_header(draw, y, label, fonts)
        events = grouped[offset]
        if not events:
            draw.text((MARGIN, y), "Geen afspraken", font=fonts.event, fill=FOREGROUND)
            y += EVENT_LINE_HEIGHT + BLOCK_GAP
            continue

        drawn = 0
        for event in events:
            lines = _event_lines(draw, event, fonts, time_width)
            if not _fits(y, _event_height(lines)):
                break
            y = _draw_event(draw, y, event, fonts, time_width, lines)
            drawn += 1
        if drawn:
            y -= EVENT_GAP
        y += BLOCK_GAP

    return y


def draw_news_block(
    draw: ImageDraw.ImageDraw, y: int, news: Dict[str, Any], fonts: Fonts
) -> int:
    """NOS headlines: a header rule, then wrapped titles with a relative time.

    No rules between items - the whitespace already separates them, and on a
    1-bit panel every extra line is another hard black stripe.
    """
    if not _fits(y, SECTION_HEADER_HEIGHT + NEWS_LINE_HEIGHT + FONT_NEWS_META):
        # A header with nothing under it is worse than no section at all.
        return y

    y = _section_header(draw, y, "NOS nieuws", fonts)

    items = news.get("items") or []
    if not items:
        message = news.get("message") or "Nieuws niet beschikbaar"
        draw.text((MARGIN, y), message, font=fonts.event, fill=FOREGROUND)
        return y + EVENT_LINE_HEIGHT

    max_width = WIDTH - 2 * MARGIN
    for item in items:
        lines = wrap_text(draw, item["title"], fonts.news_title, max_width, NEWS_MAX_LINES)
        needed = (
            len(lines) * NEWS_LINE_HEIGHT
            + NEWS_META_GAP
            + FONT_NEWS_META
            + NEWS_ITEM_GAP
        )
        # News is the last block, so it absorbs whatever space is left: drop any
        # item that would run off the bottom rather than clipping it mid-line.
        if not _fits(y, needed):
            break

        for line in lines:
            draw.text((MARGIN, y), line, font=fonts.news_title, fill=FOREGROUND)
            y += NEWS_LINE_HEIGHT
        y += NEWS_META_GAP
        draw.text((MARGIN, y), item["published"], font=fonts.news_meta, fill=FOREGROUND)
        y += FONT_NEWS_META + NEWS_ITEM_GAP

    return y


def build_dashboard_image(
    weather: Dict[str, Any],
    calendar: Dict[str, Any],
    news: Dict[str, Any],
) -> Image.Image:
    """Render the full dashboard and return it as a Pillow Image."""
    image = Image.new("1", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = Fonts()

    y = MARGIN_V
    y = draw_weather_block(draw, y, weather, fonts)
    y = draw_calendar_block(draw, y, calendar, fonts)
    y = draw_news_block(draw, y, news, fonts)

    if y > HEIGHT:
        log.warning("Content overflowed the canvas by %dpx", y - HEIGHT)

    return image
