"""Decide what happens to a rendered dashboard image.

The only place in the project that is allowed to know about e-paper hardware.
All Waveshare/GPIO imports live *inside* the real-mode branch, so this module
imports cleanly on a development PC where those libraries do not exist.
"""

import logging
from datetime import datetime

from PIL import Image

import config

log = logging.getLogger(__name__)


def output_image(image: Image.Image, mode: str = None) -> None:
    """Send the image to the e-paper panel, or save it as a preview PNG.

    mode == "real": push to the attached Waveshare panel (Raspberry Pi only).
    Anything else:  save output/preview.png and print a summary.
    """
    mode = (mode or config.EPAPER_MODE or "preview").strip().lower()

    if mode == "real":
        _output_to_epaper(image)
    else:
        _output_preview(image)


def _output_to_epaper(image: Image.Image) -> None:
    """Initialise the panel, push the buffer, then put the panel back to sleep.

    Imports are local on purpose: `waveshare_epd` is installed separately on the
    Pi and is not in requirements.txt.
    """
    import importlib

    module_name = config.EPAPER_PANEL_MODEL
    log.info("Initialising Waveshare panel: waveshare_epd.%s", module_name)

    # TODO: confirm exact panel driver module name once hardware is known.
    # EPAPER_PANEL_MODEL in .env selects it, e.g. epd7in5_V2 / epd7in5b_V2.
    try:
        driver = importlib.import_module(f"waveshare_epd.{module_name}")
    except ImportError as exc:
        raise RuntimeError(
            f"Could not import waveshare_epd.{module_name}. The Waveshare driver is "
            "installed separately on the Pi (see the README) and is deliberately not "
            "in requirements.txt. On a PC, run with --mode preview."
        ) from exc

    epd = driver.EPD()
    log.info("Panel reports %dx%d", epd.width, epd.height)

    try:
        epd.init()
        if config.EPAPER_CLEAR_FIRST:
            epd.Clear()

        # The panel buffer is landscape (epd.width x epd.height, e.g. 800x480)
        # while the dashboard is drawn portrait, so rotate before sending. Which
        # rotation is right depends on how the panel sits in its frame.
        frame = image
        if config.EPAPER_ROTATE % 360:
            frame = frame.rotate(config.EPAPER_ROTATE, expand=True)
            log.info("Rotated %d degrees -> %s", config.EPAPER_ROTATE, frame.size)
        if frame.size != (epd.width, epd.height):
            log.warning(
                "Image %s does not match panel %s - the driver will crop or pad. "
                "Check EPAPER_ROTATE and the canvas size in render.py.",
                frame.size,
                (epd.width, epd.height),
            )

        # render.py already draws in mode "1", so this convert is a no-op
        # safeguard: it only matters if a caller hands us a greyscale image.
        epd.display(epd.getbuffer(frame.convert("1")))
        log.info("Frame pushed to panel")
    finally:
        _shutdown(epd, driver)


def _shutdown(epd, driver) -> None:
    """Sleep the panel and release the GPIO, whatever the driver vintage.

    Leaving an e-paper panel powered can damage it, so neither step may be
    skipped - but the driver API varies. Older releases have `module_exit()`
    with no arguments, and an unexpected TypeError raised here would mask a
    perfectly successful refresh, so each step is guarded separately.
    """
    try:
        epd.sleep()
    except Exception:  # noqa: BLE001 - best effort, we still want module_exit
        log.exception("epd.sleep() failed")

    module_exit = getattr(getattr(driver, "epdconfig", None), "module_exit", None)
    if module_exit is None:
        log.warning("Driver has no epdconfig.module_exit - GPIO left as-is")
        return
    try:
        module_exit(cleanup=True)
    except TypeError:
        module_exit()  # pre-cleanup-kwarg driver releases
    except Exception:  # noqa: BLE001
        log.exception("epdconfig.module_exit() failed")


def _output_preview(image: Image.Image) -> None:
    """Save the image to output/preview.png and report it on stdout."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PREVIEW_PATH
    image.save(path)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Preview written to: {path.resolve()}")
    print(f"  size={image.width}x{image.height}  mode={image.mode}  at {timestamp}")
