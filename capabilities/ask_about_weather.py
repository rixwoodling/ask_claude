#!/usr/bin/env python3
"""
ask_about_weather.py

Weather capability plugin for the ask_claude capability system.

Uses Open-Meteo for worldwide weather and geocoding. No API key is required.

Plugin interface:
    CAPABILITY
    DESCRIPTION
    REQUEST_SCHEMA
    PLANNER_INSTRUCTIONS
    run_lookup(request)

The returned object contains:
    - structured weather data for Claude/composers
    - simple_summary for callers that want a cheap, direct answer without
      another Claude composition call

Example:

    from ask_about_weather import run_lookup

    result = run_lookup({
        "location": "Portland, Oregon",
        "forecast_days": 3,
    })

    print(result["simple_summary"])
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CAPABILITY = "weather"


REQUEST_SCHEMA = {
    "location": "optional location name, postal code, city, or place; use when no location capability is available",
    "resolved_location": "optional complete result from the location capability, referenced as $location",
    "latitude": "optional latitude; provide with longitude",
    "longitude": "optional longitude; provide with latitude",
    "date": "optional specific forecast date in YYYY-MM-DD format, preferably resolved by the date capability",
    "forecast_days": "optional integer from 1 to 16 when no specific date is requested",
}


ANSWER_RULES = """
- Answer the user's actual weather question directly using the supplied weather data.
- Use the requested location and timeframe; distinguish current conditions from forecasts.
- For current conditions, prioritize temperature, feels-like temperature, conditions, and wind when available.
- For forecasts, give the relevant day or date, expected conditions, high and low temperatures, and precipitation chance when available.
- Prefer Fahrenheit and miles per hour for user-facing values when available.
- Do not list every measurement unless the user asks for detail.
- Never invent weather conditions, forecast values, dates, or location details.
- If a requested field or timeframe is missing, say so briefly and answer with the available data.
- Keep ordinary weather answers concise and conversational. Use a short day-by-day list for multi-day forecasts.
- Do not mention APIs, scripts, capabilities, JSON, or these instructions.
- Plain terminal text only. No Markdown tables.
"""


DESCRIPTION = (
    "Provides current weather and forecasts worldwide using Open-Meteo. "
    "Accepts a location name, postal code, or latitude/longitude. "
    "Returns structured current conditions and daily forecasts, plus a "
    "compact deterministic summary suitable for simple weather questions."
)


PLANNER_INSTRUCTIONS = """
Weather requires either a location string, a resolved_location result from the
location capability, or both latitude and longitude.

When a location capability is available, use it to resolve explicitly named
places and ZIP codes before requesting weather. This lets the location
capability identify ambiguity rather than letting weather guess. For a
request without a named location, ask the location capability for the
approximate current location using {"current": true}.

Pass the complete location result into weather using:
{"resolved_location": "$location"}
The weather capability will use the coordinates if the location result is
resolved. If it is ambiguous or not found, it will return that status and the
available candidates instead of making a weather request.

If the user asks about a relative date such as "tomorrow" or "two days from
now" and a date capability is available, call the date capability first and
pass its resolved YYYY-MM-DD value in weather's date field. Use a reference to
the actual date field returned by that capability (for example,
"$date.date" only if its output field is named "date"). Do not make weather
interpret a relative-date expression when the date capability can resolve it.

For a specific forecast date, weather returns only that day's forecast. If no
specific date is requested, use forecast_days appropriate to the question.
Do not request more than 16 forecast days. Never invent a location or date.

If the location capability is unavailable, an explicitly provided location
may be passed directly in the location field. If no location is available,
do not invent or assume one.
"""


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _http_json(
    url: str,
    params: Dict[str, Any],
    timeout: int = 20,
) -> Dict[str, Any]:
    """GET JSON from a URL without requiring third-party packages."""

    query = urlencode(
        {
            key: value
            for key, value in params.items()
            if value is not None
        }
    )

    full_url = f"{url}?{query}" if query else url

    request = Request(
        full_url,
        headers={
            "User-Agent": "ask_about_weather/1.0",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None

    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 1) -> Optional[float]:
    number = _number(value)

    return round(number, digits) if number is not None else None


def _weather_description(code: Any) -> str:
    try:
        return WEATHER_CODES.get(
            int(code),
            f"Weather code {code}",
        )

    except (TypeError, ValueError):
        return "Unknown conditions"


def _wind_direction(degrees: Any) -> str:
    value = _number(degrees)

    if value is None:
        return ""

    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]

    index = int((value + 11.25) / 22.5) % 16

    return directions[index]


def _format_number(value: Any, digits: int = 1) -> str:
    number = _number(value)

    if number is None:
        return "unknown"

    if digits == 0:
        return str(int(round(number)))

    text = f"{number:.{digits}f}"

    return text.rstrip("0").rstrip(".")


def _c_to_f(value: Any) -> Optional[float]:
    number = _number(value)

    if number is None:
        return None

    return number * 9.0 / 5.0 + 32.0


def _kmh_to_mph(value: Any) -> Optional[float]:
    number = _number(value)

    if number is None:
        return None

    return number * 0.621371


def _location_label(
    geo: Dict[str, Any],
    requested: str,
) -> str:
    """
    Produce a useful human-readable location without pretending that a
    large region has a single precise weather station.
    """

    name = geo.get("name") or requested
    admin1 = geo.get("admin1")
    country = geo.get("country")

    parts = [str(name)]

    if admin1 and str(admin1).lower() != str(name).lower():
        parts.append(str(admin1))

    if country and str(country).lower() not in " ".join(parts).lower():
        parts.append(str(country))

    return ", ".join(parts)


def geocode_location(location: str) -> Dict[str, Any]:
    """
    Resolve a location worldwide using Open-Meteo geocoding.

    A comma-separated qualifier is matched against the returned geographic
    metadata. No country or city is assumed when the query is ambiguous.
    """

    location = str(location).strip()

    if not location:
        raise ValueError("location cannot be empty")

    cleaned = re.sub(r"\\s+", " ", location).strip()
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]

    # A qualified query such as "Taipei, Taiwan" or
    # "Portland, Oregon, USA" searches for the place name first, then
    # filters candidates using the qualifiers returned by Open-Meteo.
    place_name = parts[0] if len(parts) > 1 else cleaned
    qualifiers = parts[1:] if len(parts) > 1 else []

    params = {
        "name": place_name,
        "count": 100,
        "language": "en",
        "format": "json",
    }

    data = _http_json(
        GEOCODING_URL,
        params,
    )

    results = data.get("results") or []

    if not results:
        raise ValueError(
            f"Could not find a location named {location!r}"
        )

    def normalize(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    if qualifiers:
        filtered_results = []

        for candidate in results:
            geographic_values = [
                candidate.get("name"),
                candidate.get("admin1"),
                candidate.get("admin2"),
                candidate.get("admin3"),
                candidate.get("country"),
                candidate.get("country_code"),
            ]
            normalized_values = {
                normalize(value)
                for value in geographic_values
                if value
            }

            # Every supplied qualifier must match a geographic field.
            if all(
                normalize(qualifier) in normalized_values
                for qualifier in qualifiers
            ):
                filtered_results.append(candidate)

        if not filtered_results:
            qualifier_text = ", ".join(qualifiers)
            raise ValueError(
                f"Could not find {place_name!r} matching "
                f"the geographic qualifier(s) {qualifier_text!r}."
            )

        results = filtered_results

    # Prefer exact place-name matches. Open-Meteo may also return points
    # of interest containing the search term (airports, hospitals, etc.).
    # Those should not make an otherwise unambiguous city name ambiguous.
    normalized_query = normalize(place_name)
    exact_matches = [
        candidate
        for candidate in results
        if normalize(candidate.get("name")) == normalized_query
    ]

    if exact_matches:
        results = exact_matches

    # Detect ambiguity between distinct geographic places, not between
    # duplicate records or nearby points with different coordinates.
    identities = {
        (
            normalize(candidate.get("name")),
            normalize(candidate.get("admin1")),
            normalize(candidate.get("admin2")),
            normalize(candidate.get("country")),
            normalize(candidate.get("country_code")),
        )
        for candidate in results
    }

    if len(identities) > 1:
        choices = []

        for candidate in results:
            label_parts = [
                candidate.get("name"),
                candidate.get("admin1"),
                candidate.get("country"),
            ]
            label = ", ".join(
                str(part)
                for part in label_parts
                if part
            )

            if label and label not in choices:
                choices.append(label)

        examples = "; ".join(choices[:5])
        raise ValueError(
            f"Ambiguous location {location!r}. "
            "Please provide a more specific region or country"
            + (f", for example: {examples}." if examples else ".")
        )

    # If Open-Meteo returned duplicate records for the same geographic
    # identity, prefer the most populated result when population is present.
    result = max(
        results,
        key=lambda candidate: candidate.get("population") or 0,
    )

    latitude = _number(result.get("latitude"))
    longitude = _number(result.get("longitude"))

    if latitude is None or longitude is None:
        raise ValueError(
            f"Geocoding returned no coordinates for {location!r}"
        )

    return {
        "name": result.get("name"),
        "admin1": result.get("admin1"),
        "admin2": result.get("admin2"),
        "country": result.get("country"),
        "country_code": result.get("country_code"),
        "latitude": latitude,
        "longitude": longitude,
        "timezone": result.get("timezone"),
        "elevation": result.get("elevation"),
    }


def fetch_weather(
    latitude: float,
    longitude: float,
    forecast_days: int = 3,
    timezone: str = "auto",
) -> Dict[str, Any]:
    """Fetch current and daily weather from Open-Meteo."""

    forecast_days = max(
        1,
        min(int(forecast_days), 16),
    )

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "forecast_days": forecast_days,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "precipitation_probability_max",
                "precipitation_sum",
                "rain_sum",
                "showers_sum",
                "snowfall_sum",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
                "wind_direction_10m_dominant",
                "sunrise",
                "sunset",
            ]
        ),
    }

    return _http_json(
        OPEN_METEO_URL,
        params,
    )


def normalize_weather(
    raw: Dict[str, Any],
    location_label: str,
    latitude: float,
    longitude: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert Open-Meteo's response to a stable plugin result."""

    current_raw = raw.get("current") or {}
    daily_raw = raw.get("daily") or {}

    current = {
        "time": current_raw.get("time"),
        "temperature_c": _round(
            current_raw.get("temperature_2m")
        ),
        "temperature_f": _round(
            _c_to_f(
                current_raw.get("temperature_2m")
            )
        ),
        "feels_like_c": _round(
            current_raw.get("apparent_temperature")
        ),
        "feels_like_f": _round(
            _c_to_f(
                current_raw.get("apparent_temperature")
            )
        ),
        "humidity_percent": current_raw.get(
            "relative_humidity_2m"
        ),
        "precipitation_mm": _round(
            current_raw.get("precipitation")
        ),
        "weather_code": current_raw.get("weather_code"),
        "weather": _weather_description(
            current_raw.get("weather_code")
        ),
        "cloud_cover_percent": current_raw.get(
            "cloud_cover"
        ),
        "wind_speed_kmh": _round(
            current_raw.get("wind_speed_10m")
        ),
        "wind_speed_mph": _round(
            _kmh_to_mph(
                current_raw.get("wind_speed_10m")
            )
        ),
        "wind_direction_degrees": _round(
            current_raw.get("wind_direction_10m"),
            0,
        ),
        "wind_direction": _wind_direction(
            current_raw.get("wind_direction_10m")
        ),
        "wind_gust_kmh": _round(
            current_raw.get("wind_gusts_10m")
        ),
        "wind_gust_mph": _round(
            _kmh_to_mph(
                current_raw.get("wind_gusts_10m")
            )
        ),
    }

    dates = daily_raw.get("time") or []
    codes = daily_raw.get("weather_code") or []
    highs = daily_raw.get("temperature_2m_max") or []
    lows = daily_raw.get("temperature_2m_min") or []
    feels_highs = (
        daily_raw.get("apparent_temperature_max")
        or []
    )
    feels_lows = (
        daily_raw.get("apparent_temperature_min")
        or []
    )
    precip_probs = (
        daily_raw.get("precipitation_probability_max")
        or []
    )
    precip = daily_raw.get("precipitation_sum") or []
    rain = daily_raw.get("rain_sum") or []
    showers = daily_raw.get("showers_sum") or []
    snow = daily_raw.get("snowfall_sum") or []
    wind_max = (
        daily_raw.get("wind_speed_10m_max")
        or []
    )
    gust_max = (
        daily_raw.get("wind_gusts_10m_max")
        or []
    )
    wind_dirs = (
        daily_raw.get("wind_direction_10m_dominant")
        or []
    )
    sunrises = daily_raw.get("sunrise") or []
    sunsets = daily_raw.get("sunset") or []

    forecast: List[Dict[str, Any]] = []

    for i, date in enumerate(dates):

        def at(
            values: List[Any],
            default: Any = None,
        ) -> Any:
            return (
                values[i]
                if i < len(values)
                else default
            )

        forecast.append(
            {
                "date": date,
                "weather_code": at(codes),
                "weather": _weather_description(
                    at(codes)
                ),
                "high_c": _round(at(highs)),
                "high_f": _round(
                    _c_to_f(at(highs))
                ),
                "low_c": _round(at(lows)),
                "low_f": _round(
                    _c_to_f(at(lows))
                ),
                "feels_like_high_c": _round(
                    at(feels_highs)
                ),
                "feels_like_high_f": _round(
                    _c_to_f(at(feels_highs))
                ),
                "feels_like_low_c": _round(
                    at(feels_lows)
                ),
                "feels_like_low_f": _round(
                    _c_to_f(at(feels_lows))
                ),
                "precipitation_probability": at(
                    precip_probs
                ),
                "precipitation_mm": _round(
                    at(precip)
                ),
                "rain_mm": _round(at(rain)),
                "showers_mm": _round(at(showers)),
                "snowfall_cm": _round(at(snow)),
                "max_wind_kmh": _round(
                    at(wind_max)
                ),
                "max_wind_mph": _round(
                    _kmh_to_mph(at(wind_max))
                ),
                "max_wind_gust_kmh": _round(
                    at(gust_max)
                ),
                "max_wind_gust_mph": _round(
                    _kmh_to_mph(at(gust_max))
                ),
                "dominant_wind_direction_degrees": _round(
                    at(wind_dirs),
                    0,
                ),
                "dominant_wind_direction": _wind_direction(
                    at(wind_dirs)
                ),
                "sunrise": at(sunrises),
                "sunset": at(sunsets),
            }
        )

    return {
        "source": "Open-Meteo",
        "location": location_label,
        "latitude": _round(latitude, 5),
        "longitude": _round(longitude, 5),
        "timezone": raw.get("timezone"),
        "timezone_abbreviation": raw.get(
            "timezone_abbreviation"
        ),
        "elevation_m": _round(
            raw.get("elevation")
        ),
        "location_metadata": metadata or {},
        "current": current,
        "forecast": forecast,
    }


def build_simple_summary(
    result: Dict[str, Any],
) -> str:
    """
    Build a concise plain-text response for simple weather questions.

    This is deliberately deterministic. It does not call Claude and
    therefore adds no model-token cost.
    """

    location = (
        result.get("location")
        or "the requested location"
    )

    current = result.get("current") or {}
    forecast = result.get("forecast") or []

    temp_f = current.get("temperature_f")
    feels_f = current.get("feels_like_f")
    condition = current.get("weather")
    humidity = current.get("humidity_percent")
    wind_mph = current.get("wind_speed_mph")
    wind_dir = current.get("wind_direction")
    precip = current.get("precipitation_mm")

    parts: List[str] = []

    if temp_f is not None:
        sentence = (
            f"{location} is currently "
            f"{temp_f:g}°F"
        )

        if feels_f is not None:
            sentence += (
                f", feels like {feels_f:g}°F"
            )

        if condition:
            sentence += (
                f", with {condition.lower()}"
            )

        parts.append(sentence + ".")

    details: List[str] = []

    if humidity is not None:
        details.append(
            f"{humidity:g}% humidity"
        )

    if wind_mph is not None:
        wind_text = (
            f"winds around {wind_mph:g} mph"
        )

        if wind_dir:
            wind_text += f" {wind_dir}"

        details.append(wind_text)

    if precip is not None and precip > 0:
        details.append(
            f"{precip:g} mm of precipitation"
        )

    if details:
        parts.append(
            "It has "
            + ", ".join(details)
            + "."
        )

    if forecast:
        today = forecast[0]

        high = today.get("high_f")
        low = today.get("low_f")
        today_condition = today.get("weather")

        today_parts: List[str] = []

        if high is not None:
            today_parts.append(
                f"a high of {high:g}°F"
            )

        if low is not None:
            today_parts.append(
                f"a low of {low:g}°F"
            )

        if today_condition:
            today_parts.append(
                today_condition.lower()
            )

        probability = today.get(
            "precipitation_probability"
        )

        if probability is not None:
            today_parts.append(
                f"{probability:g}% chance of precipitation"
            )

        if today_parts:
            parts.append(
                "Today: "
                + ", ".join(today_parts)
                + "."
            )

    return (
        " ".join(parts)
        if parts
        else f"Weather data is available for {location}."
    )


def _request_value(
    request: Dict[str, Any],
    *names: str,
) -> Any:
    for name in names:
        if (
            name in request
            and request[name] not in (None, "")
        ):
            return request[name]

    return None


def _specific_date_summary(result: Dict[str, Any], target_date: str) -> str:
    """Build a concise summary for a single requested forecast date."""
    location = result.get("location") or "the requested location"
    forecast = result.get("forecast") or []
    if not forecast:
        return f"A forecast for {target_date} is not available for {location}."

    day = forecast[0]
    details = []
    if day.get("weather"):
        details.append(str(day["weather"]).lower())
    if day.get("high_f") is not None:
        details.append(f"high {day['high_f']:g}°F")
    if day.get("low_f") is not None:
        details.append(f"low {day['low_f']:g}°F")
    if day.get("precipitation_probability") is not None:
        details.append(f"{day['precipitation_probability']:g}% chance of precipitation")

    if not details:
        return f"Weather data for {target_date} is incomplete for {location}."
    return f"Forecast for {location} on {target_date}: " + ", ".join(details) + "."


def run_lookup(
    request: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Capability registry entry point.

    Accepted request fields:
        location: string
        resolved_location: result from the location capability
        latitude: number
        longitude: number
        date: specific forecast date (YYYY-MM-DD)
        forecast_days: integer (1-16)
    """

    if not isinstance(request, dict):
        raise TypeError(
            "weather request must be a dictionary"
        )

    resolved_location = request.get("resolved_location")
    target_date_value = _request_value(request, "date", "forecast_date")
    target_date = None
    if target_date_value is not None:
        target_date = str(target_date_value).strip()
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            return {
                "status": "invalid_date",
                "requested_date": target_date,
                "message": "Weather date must use YYYY-MM-DD format.",
                "simple_summary": "I couldn't interpret the requested forecast date.",
            }

    location = _request_value(
        request,
        "location",
        "place",
        "city",
    )

    if isinstance(resolved_location, dict):
        status = resolved_location.get("status", "resolved")
        if status != "resolved":
            return {
                "status": status,
                "location_query": resolved_location.get("query"),
                "message": resolved_location.get("message") or "The location could not be resolved.",
                "candidates": resolved_location.get("candidates", []),
                "simple_summary": (
                    "The location is ambiguous. Please specify the region or country."
                    if status == "ambiguous"
                    else "I couldn't find that location. Please check the spelling or add a region."
                ),
            }
        latitude = _number(resolved_location.get("latitude"))
        longitude = _number(resolved_location.get("longitude"))
        if latitude is None or longitude is None:
            return {
                "status": "invalid_location_result",
                "message": "The resolved location did not contain valid coordinates.",
                "simple_summary": "I couldn't resolve the location coordinates.",
            }
        location = (
            resolved_location.get("display_name")
            or resolved_location.get("city")
            or resolved_location.get("query")
            or location
        )
        metadata = resolved_location
    else:
        location = _request_value(
            request,
            "location",
            "place",
            "city",
        )

    if not isinstance(resolved_location, dict):
        latitude = _number(
            _request_value(
                request,
                "latitude",
                "lat",
            )
        )

        longitude = _number(
            _request_value(
                request,
                "longitude",
                "lon",
                "lng",
            )
        )

    forecast_days_value = _request_value(
        request,
        "forecast_days",
        "days",
    )

    try:
        forecast_days = int(
            forecast_days_value or 3
        )

    except (TypeError, ValueError):
        forecast_days = 3

    forecast_days = max(
        1,
        min(forecast_days, 16),
    )

    if not isinstance(resolved_location, dict):
        metadata = {}

    if latitude is not None or longitude is not None:

        if latitude is None or longitude is None:
            raise ValueError(
                "Both latitude and longitude are "
                "required when using coordinates"
            )

        location_label = str(
            location
            or f"{latitude:.5f}, {longitude:.5f}"
        )

    elif location and not isinstance(resolved_location, dict):

        try:
            geo = geocode_location(str(location))
        except ValueError as exc:
            message = str(exc)
            status = "ambiguous" if message.startswith("Ambiguous location") else "not_found"
            return {
                "status": status,
                "location_query": str(location),
                "message": message,
                "simple_summary": (
                    "The location is ambiguous. Please specify the region or country."
                    if status == "ambiguous"
                    else f"I couldn't resolve {location!r}. Please check the spelling or add a region."
                ),
            }

        latitude = float(
            geo["latitude"]
        )

        longitude = float(
            geo["longitude"]
        )

        location_label = _location_label(
            geo,
            str(location),
        )

        metadata = geo

    else:
        raise ValueError(
            "Weather lookup requires a location "
            "or both latitude and longitude"
        )

    requested_forecast_days = 16 if target_date else forecast_days
    raw = fetch_weather(
        latitude=latitude,
        longitude=longitude,
        forecast_days=requested_forecast_days,
    )

    result = normalize_weather(
        raw=raw,
        location_label=location_label,
        latitude=latitude,
        longitude=longitude,
        metadata=metadata,
    )

    if target_date:
        matching_days = [
            day for day in result.get("forecast", [])
            if day.get("date") == target_date
        ]
        result["requested_date"] = target_date
        result["forecast"] = matching_days
        result["forecast_days"] = 1
        if not matching_days:
            result["status"] = "forecast_unavailable"
            result["message"] = (
                f"No forecast is available for {target_date}. "
                "The requested date may be outside the available forecast range."
            )
            result["simple_summary"] = (
                f"A forecast for {target_date} is not available for {location_label}."
            )
            return result
        result["simple_summary"] = _specific_date_summary(result, target_date)
    else:
        result["forecast_days"] = forecast_days
        result["simple_summary"] = build_simple_summary(result)

    result["status"] = "ok"
    return result


def _print_cli_result(
    result: Dict[str, Any],
    compact: bool = False,
) -> None:
    if compact:
        print(result["simple_summary"])
        return

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get weather from Open-Meteo."
    )

    parser.add_argument(
        "location",
        nargs="?",
        help="Location name, city, postal code, etc.",
    )

    parser.add_argument(
        "--latitude",
        type=float,
        help="Latitude",
    )

    parser.add_argument(
        "--longitude",
        type=float,
        help="Longitude",
    )

    parser.add_argument(
        "--forecast-days",
        type=int,
        default=3,
        help="Number of forecast days (1-16, default: 3)",
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print the concise plain-text summary instead of JSON",
    )

    args = parser.parse_args()

    try:
        result = run_lookup(
            {
                "location": args.location,
                "latitude": args.latitude,
                "longitude": args.longitude,
                "forecast_days": args.forecast_days,
            }
        )

    except Exception as exc:
        print(
            f"Weather lookup failed: {exc}",
            file=sys.stderr,
        )

        return 1

    _print_cli_result(
        result,
        compact=args.compact,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
