"""Current weather + a short hourly forecast from Open-Meteo (no API key needed).

All display strings are Dutch, matching the rest of the dashboard.

Run standalone for debugging:  python -m sources.weather
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

import requests

import config

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo WMO weather interpretation codes -> short Dutch descriptions.
# Kept short on purpose: the e-paper layout has limited horizontal room.
WEATHER_CODES: Dict[int, str] = {
    0: "Onbewolkt",
    1: "Licht bewolkt",
    2: "Halfbewolkt",
    3: "Bewolkt",
    45: "Mist",
    48: "Aanvriezende mist",
    51: "Lichte motregen",
    53: "Motregen",
    55: "Dichte motregen",
    56: "Aanvriezende motregen",
    57: "Aanvriezende motregen",
    61: "Lichte regen",
    63: "Regen",
    65: "Zware regen",
    66: "Aanvriezende regen",
    67: "Aanvriezende regen",
    71: "Lichte sneeuw",
    73: "Sneeuw",
    75: "Zware sneeuw",
    77: "Sneeuwkorrels",
    80: "Lichte buien",
    81: "Buien",
    82: "Zware buien",
    85: "Sneeuwbuien",
    86: "Zware sneeuwbuien",
    95: "Onweer",
    96: "Onweer met hagel",
    99: "Onweer met hagel",
}


def describe_code(code: Any) -> str:
    """Map a WMO weather code to a short Dutch description."""
    try:
        return WEATHER_CODES[int(code)]
    except (TypeError, ValueError, KeyError):
        return "Onbekend"


def _fallback(reason: str = "Weer niet beschikbaar") -> Dict[str, Any]:
    return {
        "temp_now": None,
        "feels_like": None,
        "description": reason,
        "code": None,
        "is_day": True,
        "hourly": [],
        "ok": False,
    }


def _next_hours(
    hourly: Dict[str, List[Any]], count: int, step: int
) -> List[Dict[str, Any]]:
    """Pick `count` forecast points, `step` hours apart, from the current hour on."""
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    is_day_flags = hourly.get("is_day") or []
    now = datetime.now()

    points = []
    taken = 0  # counts hours since the first match, so `step` can skip them
    for index, (raw_time, temp) in enumerate(zip(times, temps)):
        # Open-Meteo returns local ISO timestamps like "2026-09-19T14:00".
        parsed = datetime.fromisoformat(raw_time)
        if parsed < now.replace(minute=0, second=0, microsecond=0):
            continue
        if temp is None:
            continue
        hours_in = taken
        taken += 1
        if hours_in % max(1, step):
            continue
        points.append(
            {
                "time": parsed.strftime("%H:%M"),
                "temp": round(float(temp), 1),
                "code": codes[index] if index < len(codes) else None,
                # is_day is 1/0; default to daytime if the field is missing.
                "is_day": bool(is_day_flags[index]) if index < len(is_day_flags) else True,
            }
        )
        if len(points) >= count:
            break
    return points


def get_weather(
    latitude: float = None,
    longitude: float = None,
    hours: int = None,
    step: int = None,
) -> Dict[str, Any]:
    """Fetch current conditions and a short hourly forecast.

    Never raises: on any failure a clearly-marked fallback dict is returned so
    the rest of the dashboard still renders.
    """
    latitude = config.LATITUDE if latitude is None else latitude
    longitude = config.LONGITUDE if longitude is None else longitude
    hours = config.WEATHER_HOURLY_COUNT if hours is None else hours
    step = config.WEATHER_HOURLY_STEP if step is None else step

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,apparent_temperature,weather_code,is_day",
        # is_day drives the sun/moon variant of each icon.
        "hourly": "temperature_2m,weather_code,is_day",
        "timezone": config.TIMEZONE,
        "forecast_days": 3,  # enough runway for a stepped strip near midnight
    }

    try:
        response = requests.get(API_URL, params=params, timeout=config.HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()

        current = payload["current"]
        return {
            "temp_now": round(float(current["temperature_2m"]), 1),
            "feels_like": round(float(current["apparent_temperature"]), 1),
            "description": describe_code(current.get("weather_code")),
            "code": current.get("weather_code"),
            "is_day": bool(current.get("is_day", 1)),
            "hourly": _next_hours(payload.get("hourly", {}), hours, step),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see docstring
        log.warning("Weather fetch failed: %s", exc)
        return _fallback()


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(get_weather(), indent=2, ensure_ascii=False))
