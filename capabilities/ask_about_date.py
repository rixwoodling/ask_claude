#!/usr/bin/env python3
"""Date and time capability for ask_claude."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CAPABILITY = "date"



PLANNER_INSTRUCTIONS = (
    "For questions asking the current time or date in a named place, "
    "use the date capability with the appropriate IANA timezone. "
    "For example, Hong Kong uses Asia/Hong_Kong and Taipei uses "
    "Asia/Taipei. For relative dates such as today, tomorrow, or "
    "this weekend, use the date capability when the exact calendar "
    "date or date range is needed."
)

REQUEST_SCHEMA = {
    "timezone": "required IANA timezone or supported timezone alias",
    "days": "optional integer day offset",
    "weeks": "optional integer week offset",
}

DESCRIPTION = (
    "Provides current local date and time for an IANA timezone, plus "
    "yesterday, today, tomorrow, this weekend, next weekend, weekday "
    "information, UTC offset, ISO datetime, and optional date offsets."
)

TIMEZONE_ALIASES = {
    "hong kong": "Asia/Hong_Kong",
    "hong kong time": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei",
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "london": "Europe/London",
    "uk": "Europe/London",
    "new york": "America/New_York",
    "eastern": "America/New_York",
    "chicago": "America/Chicago",
    "central": "America/Chicago",
    "denver": "America/Denver",
    "mountain": "America/Denver",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "utc": "UTC",
    "gmt": "Etc/GMT",
}


def _resolve_timezone(value):
    requested = str(value or "America/Los_Angeles").strip()
    timezone_name = TIMEZONE_ALIASES.get(
        requested.lower(),
        requested,
    )

    try:
        timezone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(
            f"Invalid timezone: {requested}"
        ) from exc

    return timezone_name, timezone


def _day_info(value):
    return {
        "date": value.strftime("%Y-%m-%d"),
        "day_of_week": value.strftime("%A"),
        "formatted": value.strftime("%A, %B %-d, %Y"),
    }


def _weekend_dates(today):
    """Return this weekend and next weekend.

    Monday-Friday: this weekend means the upcoming Saturday/Sunday.
    Saturday-Sunday: this weekend means the current weekend.
    """
    weekday = today.weekday()

    if weekday <= 4:
        saturday = today + timedelta(days=5 - weekday)
    elif weekday == 5:
        saturday = today
    else:
        saturday = today - timedelta(days=1)

    sunday = saturday + timedelta(days=1)
    next_saturday = saturday + timedelta(days=7)
    next_sunday = next_saturday + timedelta(days=1)

    return saturday, sunday, next_saturday, next_sunday


def run_lookup(request):
    if request is None:
        request = {}

    if not isinstance(request, dict):
        raise TypeError("Date request must be a dictionary.")

    timezone_name, timezone = _resolve_timezone(
        request.get("timezone")
    )

    now = datetime.now(timezone)
    today = now.date()

    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    (
        this_saturday,
        this_sunday,
        next_saturday,
        next_sunday,
    ) = _weekend_dates(today)

    result = {
        "date": today.strftime("%Y-%m-%d"),
        "year": today.year,
        "month": today.month,
        "day": today.day,
        "day_of_week": today.strftime("%A"),
        "time": now.strftime("%H:%M:%S"),
        "time_12h": now.strftime("%I:%M:%S %p"),
        "timezone": timezone_name,
        "utc_offset": now.strftime("%z"),
        "formatted": now.strftime("%A, %B %-d, %Y"),
        "iso_datetime": now.isoformat(),
        "yesterday": _day_info(yesterday),
        "today": _day_info(today),
        "tomorrow": _day_info(tomorrow),
        "this_weekend": {
            "saturday": _day_info(this_saturday),
            "sunday": _day_info(this_sunday),
        },
        "next_weekend": {
            "saturday": _day_info(next_saturday),
            "sunday": _day_info(next_sunday),
        },
        "days_until_this_saturday": (this_saturday - today).days,
        "days_until_this_sunday": (this_sunday - today).days,
    }

    if "days" in request:
        try:
            offset = int(request["days"])
        except (TypeError, ValueError) as exc:
            raise ValueError("days must be an integer.") from exc

        target = today + timedelta(days=offset)
        result["requested_offset"] = {
            "days": offset,
            **_day_info(target),
        }

    if "weeks" in request:
        try:
            offset = int(request["weeks"])
        except (TypeError, ValueError) as exc:
            raise ValueError("weeks must be an integer.") from exc

        target = today + timedelta(weeks=offset)
        result["requested_offset"] = {
            "weeks": offset,
            **_day_info(target),
        }

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--timezone",
        default="America/Los_Angeles",
        help="IANA timezone or supported alias.",
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--weeks", type=int)
    args = parser.parse_args()

    request = {"timezone": args.timezone}

    if args.days is not None:
        request["days"] = args.days

    if args.weeks is not None:
        request["weeks"] = args.weeks

    print(json.dumps(
        run_lookup(request),
        indent=2,
        ensure_ascii=False,
    ))
