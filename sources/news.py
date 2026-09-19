"""Latest headlines from the NOS.nl RSS feed.

Run standalone for debugging:  python -m sources.news
"""

import calendar as _calendar
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import feedparser

import config

log = logging.getLogger(__name__)


def relative_time(published: datetime, now: datetime = None) -> str:
    """Render a timestamp as a short Dutch relative string, e.g. "12 min geleden"."""
    now = now or datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    seconds = (now - published).total_seconds()
    if seconds < 0:  # clock skew / future-dated item
        return "zojuist"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "zojuist"
    if minutes < 60:
        return f"{minutes} min geleden"
    hours = minutes // 60
    if hours < 24:
        # "uur" has no separate plural form in Dutch.
        return f"{hours} uur geleden"
    days = hours // 24
    return "1 dag geleden" if days == 1 else f"{days} dagen geleden"


def _published_datetime(entry: Any) -> datetime:
    """Get a timezone-aware UTC datetime from a feedparser entry."""
    struct_time = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if struct_time is None:
        return datetime.now(timezone.utc)
    # published_parsed is always UTC per the feedparser docs.
    return datetime.fromtimestamp(_calendar.timegm(struct_time), tz=timezone.utc)


def get_news(feed_url: str = None, count: int = None) -> Dict[str, Any]:
    """Fetch the latest headlines.

    Never raises. On failure returns {"items": [], "ok": False, "message": ...}
    so the renderer can show "News unavailable".
    """
    feed_url = config.NEWS_FEED_URL if feed_url is None else feed_url
    count = config.NEWS_ITEM_COUNT if count is None else count

    try:
        feed = feedparser.parse(feed_url)
        # feedparser swallows network errors into feed.bozo rather than raising.
        if feed.bozo and not feed.entries:
            raise RuntimeError(feed.bozo_exception)
        if not feed.entries:
            raise RuntimeError("feed contained no entries")

        items: List[Dict[str, str]] = []
        for entry in feed.entries[:count]:
            items.append(
                {
                    "title": (entry.get("title") or "").strip(),
                    "published": relative_time(_published_datetime(entry)),
                }
            )
        return {"items": items, "ok": True, "message": ""}
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        log.warning("News fetch failed: %s", exc)
        return {"items": [], "ok": False, "message": "Nieuws niet beschikbaar"}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(get_news(), indent=2, ensure_ascii=False))
