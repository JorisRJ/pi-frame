"""Central configuration, loaded from .env (see .env.example).

Every value has a sensible default so the dashboard runs out of the box with
only GOOGLE_CALENDAR_ICS_URL missing.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_path(name: str, default: str) -> Path:
    """Resolve a configured path relative to the project root if it is relative."""
    raw = os.getenv(name, default)
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


# --- Location / weather ---
LATITUDE = _get_float("LATITUDE", 52.09)
LONGITUDE = _get_float("LONGITUDE", 5.12)
TIMEZONE = os.getenv("TIMEZONE", "Europe/Amsterdam")
WEATHER_HOURLY_COUNT = _get_int("WEATHER_HOURLY_COUNT", 5)
# Hours between forecast columns: 2 shows a 10-hour span in 5 columns.
WEATHER_HOURLY_STEP = _get_int("WEATHER_HOURLY_STEP", 2)

# --- News ---
NEWS_FEED_URL = os.getenv("NEWS_FEED_URL", "https://feeds.nos.nl/nosnieuwsalgemeen")
# An upper bound on what is fetched, not on what is shown: the news block is
# last in the priority order and draws as many as the leftover space allows.
NEWS_ITEM_COUNT = _get_int("NEWS_ITEM_COUNT", 8)

# --- Calendar ---
GOOGLE_CALENDAR_ICS_URL = os.getenv("GOOGLE_CALENDAR_ICS_URL", "")
CALENDAR_EVENT_COUNT = _get_int("CALENDAR_EVENT_COUNT", 8)
# The dashboard shows a "Vandaag" and a "Morgen" section, so one day ahead is
# all the window needs to cover.
CALENDAR_LOOKAHEAD_DAYS = _get_int("CALENDAR_LOOKAHEAD_DAYS", 1)
# Per-section caps. Today gets more room than tomorrow: see the block priority
# order documented in render.py.
CALENDAR_EVENTS_TODAY = _get_int("CALENDAR_EVENTS_TODAY", 4)
CALENDAR_EVENTS_TOMORROW = _get_int("CALENDAR_EVENTS_TOMORROW", 2)

# --- Display ---
EPAPER_MODE = os.getenv("EPAPER_MODE", "preview").strip().lower()
EPAPER_PANEL_MODEL = os.getenv("EPAPER_PANEL_MODEL", "epd7in5_V2")
# Degrees to rotate the portrait canvas by before handing it to the panel, which
# is natively landscape. Which way depends on how the panel sits in the frame,
# so it is configurable rather than baked in: 90 or 270 flip top-for-bottom.
EPAPER_ROTATE = _get_int("EPAPER_ROTATE", 90)
# A full white clear before each frame costs a second or two and makes the panel
# flash, but it is what stops ghosting building up over many refreshes.
EPAPER_CLEAR_FIRST = os.getenv("EPAPER_CLEAR_FIRST", "true").strip().lower() not in (
    "0",
    "false",
    "no",
)
OUTPUT_DIR = BASE_DIR / "output"
PREVIEW_PATH = OUTPUT_DIR / "preview.png"

# --- Fonts ---
FONT_REGULAR_PATH = _get_path("FONT_REGULAR_PATH", "fonts/DejaVuSans.ttf")
FONT_BOLD_PATH = _get_path("FONT_BOLD_PATH", "fonts/DejaVuSans-Bold.ttf")
# Numerals (temperatures and clock times) are set in a condensed face for
# contrast against the text. Oswald ships as a variable font; render.py picks
# weights off its wght axis and falls back to the default instance if the
# FreeType build has no variable-font support.
FONT_NUMBER_PATH = _get_path("FONT_NUMBER_PATH", "fonts/Oswald.ttf")

# --- Networking ---
HTTP_TIMEOUT = _get_int("HTTP_TIMEOUT", 10)
