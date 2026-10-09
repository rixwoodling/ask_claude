#!/usr/bin/env python3
"""NASA DONKI space-weather capability."""

from datetime import datetime, timedelta, timezone
import argparse
import json

import requests

CAPABILITY = "spaceweather"

DESCRIPTION = (
    "Provides current and recent NASA space-weather conditions from DONKI, "
    "including solar flares, coronal mass ejections, and geomagnetic storms. "
    "Optionally accepts start_date and end_date in YYYY-MM-DD format."
)

API_BASE = "https://ccmc.gsfc.nasa.gov/DONKI-API/get"
DEFAULT_DAYS = 3
TIMEOUT = 15


def _parse_date(value):
    if value is None:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}. Use YYYY-MM-DD.") from exc


def _request(event_type, start_date, end_date):
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
    }

    try:
        response = requests.get(
            f"{API_BASE}/{event_type}",
            params=params,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        return {"error": f"NASA DONKI returned HTTP {status or 'error'}."}
    except requests.RequestException:
        return {"error": "NASA DONKI request failed."}
    except ValueError:
        return {"error": "NASA DONKI returned invalid JSON."}


def _cme_summary(data):
    fastest = None
    speeds = []

    for item in data:
        for analysis in item.get("cmeAnalyses") or []:
            speed = analysis.get("speed")
            if not isinstance(speed, (int, float)):
                continue

            speeds.append(speed)

            candidate = {
                "time": item.get("startTime"),
                "speed_km_s": speed,
                "half_angle": analysis.get("halfAngle"),
                "source_location": item.get("sourceLocation") or None,
                "active_region": item.get("activeRegionNum"),
                "note": item.get("note"),
            }

            if fastest is None or speed > fastest["speed_km_s"]:
                fastest = candidate

    return {
        "count": len(data),
        "speed_range_km_s": (
            [min(speeds), max(speeds)] if speeds else None
        ),
        "fastest": fastest,
    }


def _flare_summary(data):
    strongest = None

    for item in data:
        event = {
            "time": item.get("peakTime") or item.get("beginTime"),
            "class": item.get("classType"),
            "source_location": item.get("sourceLocation") or None,
            "active_region": item.get("activeRegionNum"),
        }

        if strongest is None:
            strongest = event
            continue

        current_class = event["class"] or ""
        strongest_class = strongest["class"] or ""

        if current_class > strongest_class:
            strongest = event

    return {
        "count": len(data),
        "events": [strongest] if strongest else [],
    }


def _storm_summary(data):
    max_kp = None
    events = []

    for item in data:
        kp_values = [
            x.get("KpIndex")
            for x in (item.get("allKpIndex") or [])
            if isinstance(x.get("KpIndex"), (int, float))
        ]

        item_max_kp = max(kp_values) if kp_values else None

        if item_max_kp is not None:
            max_kp = item_max_kp if max_kp is None else max(max_kp, item_max_kp)

        events.append({
            "time": item.get("startTime"),
            "max_kp": item_max_kp,
        })

    return {
        "count": len(data),
        "max_kp": max_kp,
        "events": events[:5],
    }


def run_lookup(request):
    if not isinstance(request, dict):
        return {"error": "Request must be an object."}

    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(request.get("start_date"))
    end_date = _parse_date(request.get("end_date"))

    if start_date is None and end_date is None:
        end_date = today
        start_date = today - timedelta(days=DEFAULT_DAYS)
    elif start_date is None:
        start_date = end_date - timedelta(days=DEFAULT_DAYS)
    elif end_date is None:
        end_date = today

    if start_date > end_date:
        return {"error": "start_date cannot be after end_date."}

    event_types = request.get("event_types")
    if event_types is None:
        event_types = ["FLR", "CME", "GST"]
    elif isinstance(event_types, str):
        event_types = [event_types]

    allowed = {"FLR", "CME", "GST"}
    event_types = [str(x).upper() for x in event_types]

    invalid = [x for x in event_types if x not in allowed]
    if invalid:
        return {
            "error": f"Unsupported event type(s): {', '.join(invalid)}.",
            "supported_event_types": sorted(allowed),
        }

    summary = {}
    errors = {}

    for event_type in event_types:
        data = _request(event_type, start_date, end_date)

        if isinstance(data, dict) and "error" in data:
            errors[event_type] = data["error"]
            continue

        if not isinstance(data, list):
            errors[event_type] = "NASA DONKI returned an unexpected response."
            continue

        if event_type == "FLR":
            summary["solar_flares"] = _flare_summary(data)
        elif event_type == "CME":
            summary["cmes"] = _cme_summary(data)
        elif event_type == "GST":
            summary["geomagnetic_storms"] = _storm_summary(data)

    result = {
        "source": "NASA DONKI",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": summary,
    }

    if errors:
        result["errors"] = errors

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--event-type",
        action="append",
        dest="event_types",
        choices=["FLR", "CME", "GST"],
    )
    args = parser.parse_args()

    print(json.dumps(
        run_lookup(vars(args)),
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
