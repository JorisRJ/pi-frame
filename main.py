"""Entry point: fetch data, render the dashboard, output it.

    python main.py                # uses EPAPER_MODE from .env (default preview)
    python main.py --mode preview # force a preview PNG, even on the Pi
    python main.py --mode real    # force a push to the e-paper panel
    python main.py --test-pattern # panel bring-up card instead of the dashboard
    python main.py --clear        # blank the panel before storing it unpowered
"""

import argparse
import logging
import sys

import config
from display.epaper_output import clear_panel, output_image
from render import build_dashboard_image
from sources.calendar_feed import get_events
from sources.news import get_news
from sources.weather import get_weather

log = logging.getLogger("dashboard")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the e-paper dashboard.")
    parser.add_argument(
        "--mode",
        choices=["preview", "real"],
        default=None,
        help="Override EPAPER_MODE from .env for this run.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Blank the panel to white and exit. Use before storing it unpowered.",
    )
    parser.add_argument(
        "--list-panels",
        action="store_true",
        help="List the Waveshare driver modules installed on this machine and exit.",
    )
    parser.add_argument(
        "--test-pattern",
        action="store_true",
        help="Draw the hardware bring-up test card instead of the dashboard.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log at DEBUG level.",
    )
    return parser.parse_args(argv)


def _list_panels() -> int:
    """Report which waveshare_epd driver modules exist, and which one is configured.

    The 7.5" family has several incompatible members and some share a product
    SKU, so the only reliable way to choose is to see what the installed driver
    actually offers and match it against the panel in your hands.
    """
    import pkgutil

    try:
        import waveshare_epd
    except ImportError:
        print("waveshare_epd is not installed here (expected on a PC).")
        print("On the Pi, install it from the Waveshare e-Paper repo - see the README.")
        return 1

    names = sorted(m.name for m in pkgutil.iter_modules(waveshare_epd.__path__))
    print(f"waveshare_epd at {waveshare_epd.__path__[0]}")
    print(f"configured EPAPER_PANEL_MODEL = {config.EPAPER_PANEL_MODEL}")
    print()
    for name in names:
        marker = "  <-- configured" if name == config.EPAPER_PANEL_MODEL else ""
        size = ""
        try:
            module = __import__(f"waveshare_epd.{name}", fromlist=["EPD"])
            size = f"  {module.EPD_WIDTH}x{module.EPD_HEIGHT}"
        except Exception:  # noqa: BLE001 - a module that will not import is still worth listing
            size = "  (could not read size)"
        print(f"  {name}{size}{marker}")

    if config.EPAPER_PANEL_MODEL not in names:
        print(f"WARNING: {config.EPAPER_PANEL_MODEL} is not in that list.")
        return 1
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    mode = args.mode or config.EPAPER_MODE

    try:
        if args.list_panels:
            return _list_panels()

        if args.clear:
            clear_panel(mode=mode)
            return 0

        if args.test_pattern:
            # No network, no data sources: this is purely about the panel.
            from testcard import build_test_card

            log.info("Rendering the hardware test card")
            output_image(build_test_card(), mode=mode)
            return 0

        # Each source degrades gracefully on its own, so one dead feed cannot
        # stop the other two blocks from rendering.
        weather = get_weather()
        calendar = get_events()
        news = get_news()

        for label, ok in (
            ("weather", weather.get("ok")),
            ("calendar", calendar.get("ok")),
            ("news", news.get("ok")),
        ):
            log.info("%s: %s", label, "ok" if ok else "UNAVAILABLE")

        image = build_dashboard_image(weather, calendar, news)
        output_image(image, mode=mode)
        return 0
    except Exception:  # noqa: BLE001 - unattended via cron; log and exit non-zero
        log.exception("Dashboard run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
