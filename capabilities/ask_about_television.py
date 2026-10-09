#!/usr/bin/env python3
"""TV schedule capability plugin for ask_claude_v12."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

CAPABILITY = "television"
DESCRIPTION = "TV listings and television schedules by channel."


STATIONS = {
    "portland": {
        "abc": {
            "callsign": "KATU",
            "url": "https://www.tvpassport.com/tv-listings/stations/abc-katu-portland-or-hd/3727",
        },
        "cbs": {
            "callsign": "KOIN",
            "url": "https://www.tvpassport.com/tv-listings/stations/cbs-koin-portland-or-hd/3728",
        },
        "nbc": {
            "callsign": "KGW",
            "url": "https://www.tvpassport.com/tv-listings/stations/nbc-kgw-portland-or-hd/3729",
        },
        "fox": {
            "callsign": "KPTV",
            "url": "https://www.tvpassport.com/tv-listings/stations/fox-kptv-portland-or-hd/3731",
        },
    }
}

ALIASES = {
    "abc": "abc",
    "cbs": "cbs",
    "nbc": "nbc",
    "fox": "fox",
}


def _find_channel(request: dict[str, Any]) -> str | None:
    for key in ("channel", "network", "station"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return ALIASES.get(value.lower().strip(), value.lower().strip())

    # Also tolerate a request such as {"query": "What's on NBC now?"}.
    query = request.get("query") or request.get("question")
    if isinstance(query, str):
        match = re.search(r"\b(ABC|CBS|NBC|FOX)\b", query, re.I)
        if match:
            return match.group(1).lower()

    # No specific channel means all supported local broadcast channels.
    return None


def _find_location(request: dict[str, Any]) -> str:
    value = request.get("location") or request.get("market") or "Portland"
    if not isinstance(value, str):
        return "Portland"
    return value.strip()


def _find_date(request: dict[str, Any]) -> dt.date:
    value = request.get("date")
    if value is None:
        return dt.date.today()

    if isinstance(value, dt.date):
        return value

    if isinstance(value, str):
        return dt.date.fromisoformat(value)

    raise ValueError("Television date must be YYYY-MM-DD.")


def _resolve_station(channel: str, location: str) -> dict[str, str]:
    location_key = location.lower().strip()
    if "portland" in location_key:
        market = "portland"
    else:
        market = location_key

    if market not in STATIONS:
        raise ValueError(
            f"Unsupported television market '{location}'. "
            "Currently supported: Portland."
        )

    if channel not in STATIONS[market]:
        raise ValueError(
            f"Unsupported channel '{channel}' in {location}. "
            f"Supported: {', '.join(sorted(STATIONS[market]))}."
        )

    station = STATIONS[market][channel].copy()
    station["channel"] = channel.upper()
    station["market"] = "Portland"
    station["timezone"] = "America/Los_Angeles"
    return station


def _fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/140 Safari/537.36"
            )
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.text


def _parse_schedule(html: str, date: dt.date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    time_re = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)
    results = []
    seen = set()

    # Prefer obvious listing/program elements.
    containers = soup.select(
        "[class*='listing'], [class*='schedule'], [class*='program']"
    )
    if not containers:
        containers = soup.find_all(["article", "li", "tr"])

    for container in containers:
        text = " ".join(container.stripped_strings)
        match = time_re.search(text)
        if not match:
            continue

        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3).upper()

        if not 1 <= hour <= 12 or minute > 59:
            continue

        title = None
        for node in container.select("h2, h3, h4, a, strong"):
            candidate = " ".join(node.stripped_strings).strip()
            if not candidate or time_re.fullmatch(candidate):
                continue
            if 2 <= len(candidate) <= 200:
                title = candidate
                break

        if not title:
            continue

        hour24 = hour % 12
        if ampm == "PM":
            hour24 += 12

        # Portland is Pacific Time. Use the appropriate UTC offset for the
        # requested date (PDT/ PST) rather than hard-coding -07:00.
        if dt.date(2026, 3, 8) <= date <= dt.date(2026, 11, 1):
            offset = dt.timedelta(hours=-7)
        else:
            offset = dt.timedelta(hours=-8)

        start = dt.datetime(
            date.year,
            date.month,
            date.day,
            hour24,
            minute,
            tzinfo=dt.timezone(offset),
        )

        key = (start.isoformat(), title)
        if key in seen:
            continue

        seen.add(key)
        results.append(
            {
                "start": start.isoformat(),
                "title": title,
            }
        )

    results.sort(key=lambda item: item["start"])
    return results


def get_schedule(
    channel: str,
    location: str = "Portland",
    date: dt.date | None = None,
) -> dict[str, Any]:
    """Return structured schedule data. No 'now'/'next' interpretation."""
    if date is None:
        date = dt.date.today()

    station = _resolve_station(channel.lower().strip(), location)
    url = f"{station['url'].rstrip('/')}/{date.isoformat()}"

    schedule = _parse_schedule(_fetch(url), date)

    return {
        "source": "TV Passport",
        "source_url": url,
        "channel": station["channel"],
        "station": station["callsign"],
        "market": station["market"],
        "timezone": station["timezone"],
        "date": date.isoformat(),
        "schedule": schedule,
    }


def run_lookup(request: dict[str, Any]) -> dict[str, Any]:
    """Capability-registry entry point used by ask_claude_v12."""
    if not isinstance(request, dict):
        raise TypeError("television run_lookup() expects a request dictionary")

    channel = _find_channel(request)
    location = _find_location(request)
    date = _find_date(request)

    if channel:
        return get_schedule(
            channel=channel,
            location=location,
            date=date,
        )

    channels = STATIONS.get("portland", {})
    schedules = {}
    for channel_name in channels:
        schedules[channel_name] = get_schedule(
            channel=channel_name,
            location=location,
            date=date,
        )

    return {
        "source": "TV Passport",
        "market": "Portland",
        "timezone": "America/Los_Angeles",
        "date": date.isoformat(),
        "channels": schedules,
    }
