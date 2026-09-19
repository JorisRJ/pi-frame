# pi-frame

A portrait dashboard for a 7.5" Waveshare e-paper display: today's weather, the
next few calendar events, and the latest NOS headlines, rendered as a 480x800
image. All on-screen text is in Dutch; the code and comments are in English.

The same code runs unchanged on a development PC and on a Raspberry Pi with the
e-paper HAT attached. All layout logic produces a plain Pillow `Image` and knows
nothing about the hardware; a single environment variable, `EPAPER_MODE`,
decides what happens to that image:

| `EPAPER_MODE` | Behaviour |
| --- | --- |
| unset / `preview` | Saves `output/preview.png` and prints its path. No Waveshare or GPIO library is imported. |
| `real` | Imports the Waveshare driver, initialises the panel, pushes the buffer, sleeps the panel. |

Every Waveshare/GPIO import lives *inside* the real-mode branch in
`display/epaper_output.py`, so nothing Pi-specific is imported on a PC.

## Layout

```
+------------------------------+
| 19 °C  Bewolkt          (~)  |  weather: current temp, description,
|        Voelt als 16°         |  feels-like and a condition icon, then a
| 13:00  15:00  17:00  19:00   |  forecast strip in 2-hour steps, each
|  (~)    (~)    (*)    (*)    |  column with its own icon
|  19°    20°    19°    18°    |
+------------------------------+
| Vandaag                      |  agenda: one section per day, each with
| 14:10   Tandarts afspraak    |  a rule under the label. Bold time on the
|         met een lange titel  |  left, title on the right, wrapped to at
| 16:25   Sprint review        |  most 2 lines. All-day events say
+------------------------------+  "Hele dag" instead of a clock time.
| Morgen                       |
| 09:30   Standup              |
+------------------------------+
| NOS nieuws                   |  news: header rule only, no rules between
| Kabinet presenteert begro-   |  items. Titles wrap to 2 lines in a
| ting met lastenverlichting   |  smaller face, with a small relative
| 12 min geleden               |  timestamp under each.
+------------------------------+
```

### How the 800px are shared

Blocks claim vertical space in priority order, each taking what it needs before
the next one sees what is left:

| # | Block | Claim |
| --- | --- | --- |
| 1 | Weather | Fixed height, always drawn in full |
| 2 | **Vandaag** | Up to `CALENDAR_EVENTS_TODAY` events (default 4) |
| 3 | **Morgen** | Up to `CALENDAR_EVENTS_TOMORROW` events (default 2) |
| 4 | NOS nieuws | No cap of its own — it fills whatever remains |

Every block measures each row before drawing it (`_fits()`) and stops once a row
would cross the bottom margin. So a heavy agenda can squeeze the news feed down
to a couple of items, and a quiet day lets the feed grow to six or more — but
nothing ever runs off the panel or is clipped half-way through a line. This is
also why `NEWS_ITEM_COUNT` is a fetch ceiling rather than a count: the layout,
not the config, decides how many headlines actually appear.

A day with nothing on it says "Geen afspraken" rather than collapsing, so the
two sections stay in the same place from run to run. If the calendar itself is
unreachable, the two day sections are replaced by a single "Agenda" section
carrying the failure message — repeating "niet beschikbaar" under both days
would say the same thing twice.

### Typography

Two faces, split by role:

* **DejaVu Sans** — all text: section labels (Bold), event and headline titles,
  the small relative timestamps.
* **Oswald** — all numerals: the big temperature and its unit, the forecast
  strip's times and temperatures, and the agenda's time column. It is
  condensed, so the numbers read as instrument readings rather than as more
  body copy, and they take less width than DejaVu's.

Oswald is only published as a variable font, so `_load_font()` selects weights
off its `wght` axis via `set_variation_by_name`. That needs a FreeType build
with variable-font support; if the Pi's does not have it, the call is caught,
logged, and the font stays at its default instance rather than the dashboard
dying.

Mixing two faces needs care about vertical metrics: Oswald carries far more
ascender padding than DejaVu (ascent 22 vs 17 at 18px, and 23px of dead space
above "22" at 60px). Positioning numbers by the font's ascender therefore drops
them a few pixels below the text beside them and wastes vertical space. So:

* numerals are placed by the top of their *ink* (`_draw_ink_top`), which is
  stable because every digit has the same ink top — it would not be for
  arbitrary words, whose ink top depends on whether they happen to start with a
  capital;
* in an agenda row the Oswald time is drawn on the DejaVu title's **baseline**,
  which is what actually puts the two on the same line.

There is one known nit, accepted deliberately: this Pillow build has no Raqm
(`features.check('raqm')` is False), so OpenType features cannot be enabled and
Oswald's figures are not quite tabular — its digit widths vary by up to 2px at
18px, so the colons in the agenda time column can sit 1-2px apart between rows.
Roboto Condensed has tabular figures by default if that ever becomes annoying.

### Weather icons

Eleven icons — sun, moon, sun/moon behind cloud, cloud, fog, drizzle, rain,
heavy rain, snow, thunder — live in `icons.py`, drawn from Pillow primitives
rather than an icon font or PNG assets.

They are outlines, not filled silhouettes, and the outline is taken
morphologically: each icon is built as a filled shape and then reduced to
`shape - erode(shape)`. Drawing the circles with `outline=` instead would leave
the seams where they overlap visible *inside* the cloud; eroding the union gives
one clean contour. Everything is rasterised at 3x and box-filtered down, so
curves and stroke weights come out even at 26px without any grey pixels
surviving into the final 1-bit stencil.

Open-Meteo's `is_day` flag picks the sun or moon variant, per forecast column as
well as for the current conditions. To eyeball every icon at both sizes:

```bash
python icons.py        # writes output/icons.png
```

## Project layout

```
pi-frame/
├── main.py                   entry point: fetch -> render -> output
├── config.py                 all settings, loaded from .env
├── render.py                 layout + drawing; returns a Pillow Image
├── icons.py                  weather icons drawn with Pillow primitives
├── sources/
│   ├── weather.py            Open-Meteo (no API key)
│   ├── news.py               NOS.nl RSS via feedparser
│   └── calendar_feed.py      Google Calendar secret iCal URL
├── display/
│   └── epaper_output.py      preview PNG or real panel
├── fonts/                    DejaVu Sans (text) + Oswald (numerals)
└── output/                   preview.png lands here (git-ignored)
```

## PC development workflow

1. Create a virtualenv and install the dependencies:

   ```bash
   python -m venv venv
   source venv/bin/activate          # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy the example config and fill it in:

   ```bash
   cp .env.example .env              # Windows: copy .env.example .env
   ```

   Weather and news work with the defaults. For the calendar, set
   `GOOGLE_CALENDAR_ICS_URL` to your private iCal address: Google Calendar →
   Settings → *Settings for my calendars* → your calendar → *Integrate calendar*
   → **Secret address in iCal format**. Treat that URL as a password; `.env` is
   git-ignored for exactly this reason.

3. Make sure the three font files exist in `fonts/`. They are already in this
   repo:

   | File | Role | Source |
   | --- | --- | --- |
   | `DejaVuSans.ttf` | body text | [DejaVu fonts release](https://github.com/dejavu-fonts/dejavu-fonts/releases) (`ttf/` inside `dejavu-fonts-ttf-*.zip`), or `fonts-dejavu-core` on Debian/Raspberry Pi OS |
   | `DejaVuSans-Bold.ttf` | headers, bold text | same |
   | `Oswald.ttf` | numerals | [Google Fonts](https://github.com/google/fonts/tree/main/ofl/oswald) (`Oswald[wght].ttf`) |

   All three are SIL OFL licensed. Any other TrueType will do — point
   `FONT_REGULAR_PATH`, `FONT_BOLD_PATH` and `FONT_NUMBER_PATH` at it. If you
   swap the numeral font for a non-variable one, the weight names in
   `render.py`'s `Fonts` class are simply ignored (with a warning).

4. Run it:

   ```bash
   python main.py
   ```

   This needs no e-paper hardware. It writes `output/preview.png` and prints the
   absolute path plus the image size, so a successful run is obvious from the
   terminal.

5. Open `preview.png` after each change. Iterate on the constants at the top of
   `render.py` (font sizes, margins, row heights) and on the `draw_*_block`
   functions.

6. Commit and push when you are happy with it, then deploy to the Pi (below).

### Debugging a single data source

Each source module runs standalone and pretty-prints what it fetched:

```bash
python -m sources.weather
python -m sources.news
python -m sources.calendar_feed
```

`python icons.py` does the same for the icon set.

### Graceful degradation

Every source catches its own failures and returns a clearly-marked fallback, so
one dead feed can never take down the dashboard: a broken calendar URL renders
"Agenda niet beschikbaar" while weather and news still draw normally. To try it,
point `GOOGLE_CALENDAR_ICS_URL` at garbage and run `python main.py` — the run
still exits 0 and still writes a full preview.

`main.py` itself exits non-zero and logs a clear error only on unexpected
failures, which is what you want from cron.

## Running on the Raspberry Pi

From a freshly imaged Raspberry Pi OS. Do these in order — each step is
verifiable on its own, so a failure tells you exactly which one broke.

### 1. Enable SPI and install system packages

```bash
sudo raspi-config     # Interface Options -> SPI -> Yes, then reboot
sudo apt update
sudo apt install -y git python3-venv python3-pip
```

After the reboot, confirm the kernel exposes the bus — if these devices are
missing, nothing further will work:

```bash
ls -l /dev/spidev*    # expect /dev/spidev0.0 and /dev/spidev0.1
```

### 2. Get the code and its Python dependencies

```bash
git clone <this repo> pi-frame
cd pi-frame
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

The fonts are committed, so nothing to download.

### 3. Create the .env

`.env` is git-ignored — it holds your secret calendar URL, so it never travels
through the repo. Copy the example and fill it in on the Pi itself:

```bash
cp .env.example .env
nano .env         # at minimum GOOGLE_CALENDAR_ICS_URL
```

Leave `EPAPER_MODE=preview` for now.

### 4. Prove the software works before involving the hardware

```bash
./venv/bin/python main.py --mode preview
```

This needs no panel. If it writes `output/preview.png` and logs all three
sources as `ok`, everything except the display is working — which means any
later failure is a hardware or driver problem, not a code one.

### 5. Install the Waveshare driver

Deliberately *not* in `requirements.txt`: it is Pi-only and would fail to
install on a PC.

```bash
git clone https://github.com/waveshare/e-Paper ~/e-Paper
./venv/bin/pip install ~/e-Paper/RaspberryPi_JetsonNano/python
```

Check that path against the repo you actually cloned — Waveshare move things
between releases. Then confirm the module imports and matches your panel:

```bash
./venv/bin/python -c "from waveshare_epd import epd7in5_V2 as d; e=d.EPD(); print(e.width, e.height)"
```

Expect `800 480`. If that import fails, see the two snags below.

### 6. Light the panel with the test card

```bash
./venv/bin/python main.py --mode real --test-pattern
```

The test card exists to answer what a PNG on a laptop cannot:

* **Orientation** — an arrow marked `BOVEN` and every corner labelled. If the
  card is upside down, set `EPAPER_ROTATE=270` in `.env` and re-run.
* **Cropping** — a 1px ring around the outermost pixels. If a side is missing,
  the frame's bezel is covering the panel there; raise `MARGIN`/`MARGIN_V` in
  `render.py` to suit.
* **Legibility** — a ladder from 12px to 24px. Read it from where the frame
  will actually hang and note the smallest line you can make out; that is the
  floor for `FONT_NEWS_META` and friends.
* **Ghosting and fine detail** — a solid block and a 1px comb.

### 7. Run the real dashboard

```bash
./venv/bin/python main.py --mode real
```

Once you are happy, set `EPAPER_MODE=real` in `.env` so a plain `main.py` does
the right thing, and add it to cron:

```cron
*/30 * * * * cd /home/pi/pi-frame && ./venv/bin/python main.py >> /tmp/pi-frame.log 2>&1
```

`main.py` exits non-zero and logs the cause on unexpected failures, which is
what makes an unattended job debuggable. Note that e-paper panels have a finite
number of refreshes and each full refresh takes seconds — every 15-30 minutes
is sensible, every minute is not.

### Two likely snags

**The driver imports but fails on GPIO.** This does not affect a Pi 3B, where
the classic `RPi.GPIO` backend still works. It bites on the Pi 5, and on
Bookworm more generally, which Recent Waveshare drivers can use `gpiozero`
plus `lgpio` instead; older ones cannot. If you see `RPi.GPIO`-related errors:

```bash
sudo apt install -y python3-lgpio
./venv/bin/pip install lgpio gpiozero spidev
```

and make sure you cloned a recent `e-Paper` checkout.

**The venv cannot see system GPIO packages.** If the driver expects
apt-installed modules, either install them into the venv as above, or recreate
the venv with access to them:

```bash
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
```

### Which panel driver?

`EPAPER_PANEL_MODEL` is the module name inside `waveshare_epd`. Ask the Pi what
it actually has:

```bash
./venv/bin/python main.py --list-panels
```

That prints every driver module the installed Waveshare package provides, with
each one's native resolution, and flags the configured one.

Matching it to the hardware needs care, because **Waveshare SKU 13504 has
shipped as two incompatible panels under the same product number**:

| Version | Resolution | Driver module | Canvas |
| --- | --- | --- | --- |
| 7.5" HAT **V1** | 640x384 | `epd7in5` | would need 384x640 |
| 7.5" HAT **V2** | 800x480 | `epd7in5_V2` | 480x800 (what this repo draws) |

To tell them apart, look for a **`V2` label on the back of the panel, under the
board name**. Failing that, go by purchase date: bought after August 2020 is V2;
before December 2019 is V1. Current retail listings for 13504 are all 800x480,
so V2 is the likely answer — but the 640x384 version was sold under the same
SKU, so it is worth checking rather than assuming.

If it does turn out to be a V1, the driver name is not the only change: the
canvas in `render.py` is 480x800 and every layout constant is tuned for it, so a
384x640 panel needs those retuned as well.

The other 7.5" family members are `epd7in5b_V2` (adds red) and `epd7in5_HD`
(880x528). The wrong module produces noise or nothing at all rather than a
helpful error.

## Configuration

All settings live in `.env`; see `.env.example` for the full list with comments.
The main ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LATITUDE` / `LONGITUDE` | `52.09` / `5.12` | Weather location (Utrecht, NL) |
| `TIMEZONE` | `Europe/Amsterdam` | Timezone for hourly forecast labels |
| `NEWS_FEED_URL` | NOS general news | Any NOS RSS feed; swap for a category feed |
| `WEATHER_HOURLY_STEP` | `2` | Hours between forecast columns |
| `WEATHER_HOURLY_COUNT` | `5` | Number of forecast columns |
| `NEWS_ITEM_COUNT` | `8` | Headlines fetched; the layout shows as many as fit |
| `GOOGLE_CALENDAR_ICS_URL` | – | Your secret iCal URL |
| `CALENDAR_EVENT_COUNT` | `10` | Upper bound on events fetched |
| `CALENDAR_EVENTS_TODAY` | `4` | Events shown under "Vandaag" |
| `CALENDAR_EVENTS_TOMORROW` | `2` | Events shown under "Morgen" |
| `CALENDAR_LOOKAHEAD_DAYS` | `1` | How far ahead to expand events |
| `EPAPER_MODE` | `preview` | `preview` or `real` |
| `EPAPER_PANEL_MODEL` | `epd7in5_V2` | Waveshare driver module name |
| `EPAPER_ROTATE` | `90` | Rotation onto the landscape panel; `270` flips it |
| `EPAPER_CLEAR_FIRST` | `true` | White-flash before each refresh, to stop ghosting |
| `FONT_REGULAR_PATH` | `fonts/DejaVuSans.ttf` | Text face |
| `FONT_BOLD_PATH` | `fonts/DejaVuSans-Bold.ttf` | Bold text face |
| `FONT_NUMBER_PATH` | `fonts/Oswald.ttf` | Numeral face |

## Notes and assumptions

- The canvas is `Image.new("1", (480, 800), 255)` — true 1-bit black and white,
  because that is all the panel can show. `output/preview.png` is therefore
  pixel-for-pixel what the hardware renders: no greys, no antialiasing. Drawing
  in greyscale would look smoother on a monitor and then get Floyd-Steinberg
  dithered into fuzzy speckle by the driver's `getbuffer()`, so the preview
  would flatter the result. There is no muted-grey colour for the same reason —
  visual hierarchy comes from font size and weight only.
- `_output_to_epaper` rotates the portrait image 90° to match the panel's native
  800x480 landscape buffer before sending.
- Blocks are drawn by `draw_weather_block` / `draw_calendar_block` /
  `draw_news_block`, each taking `(draw, y, data, fonts)` and returning the new
  y-offset, so they stack cleanly and are easy to reorder or extend later.
- Display text is Dutch and lives close to where it is used: weather
  descriptions in `sources/weather.py`, relative times in `sources/news.py`,
  clock labels in `format_event_clock()` and day names in `DAY_LABELS`, section
  labels in `render.py`.
- `wrap_text()` in `render.py` is the one place that word-wraps: it fills up to
  N lines and only ellipsises what is left over, which fits far more of a
  headline than truncating the first line would.
- Not built yet, on purpose: MQTT screen modes, Docker, Tailscale, Pi-hole.
