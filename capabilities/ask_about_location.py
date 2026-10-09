#!/usr/bin/env python3
"""Location lookup capability.

Supports:
- Named locations via OpenStreetMap Nominatim.
- US ZIP codes via Zippopotam.us.
- Current/non-specific location via IP geolocation.
- Great-circle distance calculations between two locations.

The module exposes:
    CAPABILITY
    DESCRIPTION
    run_lookup(request)
"""

import json
import math
import re
import sys
import urllib.parse
import urllib.request


CAPABILITY = "location"

PLANNER_INSTRUCTIONS = (
    "Use this capability for place lookups, current approximate location, "
    "ZIP-code location, and geographic distance questions. For a named place "
    "or ZIP code, put it in query. For current location, set current=true. "
    "For distance questions, provide origin and destination as separate "
    "fields; do not estimate distance from memory. The capability calculates "
    "great-circle distance from resolved coordinates. Do not invent places "
    "or coordinates."
)

ANSWER_RULES = """
- Answer simple location questions in one short sentence.
- Give only the minimum geographic detail needed to answer the question.
- For ZIP codes, identify the associated city and state when available.
- For current-location queries based on IP geolocation, describe the result as approximate.
- Never imply that IP geolocation identifies the user's exact physical address.
- Do not invent missing coordinates or address details.
- If a lookup fails or returns incomplete information, state the limitation.
- For distance questions, report the calculated great-circle distance in miles and kilometers.
- Clearly distinguish straight-line distance from road distance or flight distance.
- Do not add flight times, routes, or travel advice unless requested.
- Avoid Markdown formatting for simple answers. Use plain text unless formatting materially improves readability.
"""

REQUEST_SCHEMA = {
    "query": "location name, address, city, state, country, or US ZIP code",
    "current": "optional boolean; use true for approximate current location",
    "origin": "optional origin location for a geographic distance calculation",
    "destination": "optional destination location for a geographic distance calculation",
}

DESCRIPTION = (
    "Resolve named locations, US ZIP codes, or the user's approximate current "
    "location. Calculate great-circle distances between two locations when "
    "origin and destination are supplied."
)

USER_AGENT = "local-personal-assistant/1.0"

CURRENT_LOCATION_PHRASES = (
    "around me",
    "near me",
    "here",
    "my location",
    "current location",
    "where i am",
    "where am i",
)


def _get_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_current_location_query(query):
    if not query:
        return True

    normalized = " ".join(query.lower().split())

    return any(
        phrase in normalized
        for phrase in CURRENT_LOCATION_PHRASES
    )


def _is_us_zip(query):
    return bool(re.fullmatch(r"\d{5}(?:-\d{4})?", query.strip()))


def _lookup_zip(query):
    """Resolve a US ZIP code using Zippopotam.us."""
    zip_code = query.strip()[:5]

    url = (
        "https://api.zippopotam.us/us/"
        + urllib.parse.quote(zip_code)
    )

    data = _get_json(url)

    places = data.get("places", [])
    if not places:
        raise RuntimeError(f"US ZIP code not found: {zip_code}")

    place = places[0]

    latitude = float(place["latitude"])
    longitude = float(place["longitude"])

    city = place.get("place name")
    state = place.get("state")
    state_abbreviation = place.get("state abbreviation")
    country = data.get("country", "United States")
    country_abbreviation = data.get(
        "country abbreviation",
        "US",
    )

    return {
        "query": query,
        "latitude": latitude,
        "longitude": longitude,
        "display_name": (
            f"{city}, {state_abbreviation or state}, {country}"
        ),
        "city": city,
        "town": city,
        "village": city,
        "state": state,
        "state_abbreviation": state_abbreviation,
        "country": country,
        "country_code": country_abbreviation.lower(),
        "postal_code": zip_code,
        "source": "zippopotam.us",
    }


def _geocode(query):
    """Resolve a named place with Nominatim."""
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }
    )

    url = (
        "https://nominatim.openstreetmap.org/search?"
        + params
    )

    data = _get_json(url)

    if not data:
        raise RuntimeError(f"Location not found: {query}")

    result = data[0]
    address = result.get("address", {})

    return {
        "query": query,
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "display_name": result.get("display_name"),
        "city": (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
        ),
        "town": address.get("town"),
        "village": address.get("village"),
        "state": address.get("state"),
        "state_abbreviation": address.get("ISO3166-2-lvl4"),
        "country": address.get("country"),
        "country_code": address.get("country_code"),
        "postal_code": address.get("postcode"),
        "source": "nominatim",
    }


def _current_location():
    """Get approximate current location from the public IP address."""
    data = _get_json("https://ipapi.co/json/")

    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if latitude is None or longitude is None:
        raise RuntimeError(
            "Current location lookup did not return coordinates."
        )

    city = data.get("city")
    region = data.get("region")
    country = data.get("country_name")

    parts = [
        part
        for part in (city, region, country)
        if part
    ]

    return {
        "query": "current location",
        "latitude": float(latitude),
        "longitude": float(longitude),
        "display_name": ", ".join(parts),
        "city": city,
        "state": region,
        "country": country,
        "country_code": data.get("country_code"),
        "postal_code": data.get("postal"),
        "source": "ipapi.co",
    }


def _haversine_distance(lat1, lon1, lat2, lon2):
    """Return great-circle distance in kilometers between two coordinates."""
    earth_radius_km = 6371.0088

    lat1, lon1, lat2, lon2 = map(
        math.radians, (lat1, lon1, lat2, lon2)
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    a = max(0.0, min(1.0, a))
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def _resolve_location(query):
    """Resolve one named place or ZIP code to location fields."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Both origin and destination must be provided.")
    query = query.strip()
    if _is_us_zip(query):
        return _lookup_zip(query)
    return _geocode(query)


def _distance_lookup(origin, destination):
    """Resolve two places and calculate their great-circle distance."""
    origin_data = _resolve_location(origin)
    destination_data = _resolve_location(destination)

    distance_km = _haversine_distance(
        origin_data["latitude"],
        origin_data["longitude"],
        destination_data["latitude"],
        destination_data["longitude"],
    )
    return {
        "type": "great_circle_distance",
        "origin": origin_data.get("display_name") or origin_data["query"],
        "destination": destination_data.get("display_name") or destination_data["query"],
        "distance_km": round(distance_km, 1),
        "distance_miles": round(distance_km * 0.621371, 1),
        "method": "Haversine great-circle calculation using resolved coordinates",
        "source": {
            "origin": origin_data.get("source"),
            "destination": destination_data.get("source"),
        },
    }


def run_lookup(request):
    """Run a location lookup.

    Examples:
        {"query": "Hillsboro, Oregon"}
        {"query": "97124"}
        {"current": true}
    """
    if request is None:
        request = {}

    if not isinstance(request, dict):
        raise ValueError("Location request must be a dictionary.")

    query = request.get("query")

    origin = request.get("origin")
    destination = request.get("destination")
    if origin is not None or destination is not None:
        if not origin or not destination:
            raise ValueError("Distance lookup requires both origin and destination.")
        return _distance_lookup(origin, destination)

    if request.get("current") is True or _is_current_location_query(query):
        return _current_location()

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Location request requires a query.")

    query = query.strip()

    if _is_us_zip(query):
        return _lookup_zip(query)

    return _geocode(query)


def main():
    if len(sys.argv) < 2:
        request = {"current": True}
    else:
        query = " ".join(sys.argv[1:])
        request = {"query": query}

    result = run_lookup(request)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
