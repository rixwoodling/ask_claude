#!/usr/bin/env python3
"""Location lookup capability.

Supports:
- Named locations via OpenStreetMap Nominatim.
- US ZIP codes via Zippopotam.us.
- Current/non-specific location via IP geolocation.

The module exposes:
    CAPABILITY
    DESCRIPTION
    run_lookup(request)
"""

import json
import re
import sys
import urllib.parse
import urllib.request


CAPABILITY = "location"

PLANNER_INSTRUCTIONS = (
    "For location-dependent questions, use the location capability to "
    "resolve the requested place before calling a capability that needs "
    "coordinates. If the user refers to their current or local location "
    "without naming a specific place, request the location capability "
    "with current=true. For a named place or ZIP code, put it in the "
    "query field. When another capability needs coordinates from this "
    "lookup, use $location.latitude and $location.longitude. Do not "
    "invent coordinates or guess a city."
)

ANSWER_RULES = """
- Answer the specific location question directly.
- For simple location questions, normally use one sentence.
- Include only essential geographic context.
- Do not add unrelated distances, travel times, tourist attractions,
  historical background, or comparisons unless requested.
- For ZIP codes, identify the primary associated city and state when available.
- For current-location queries based on IP geolocation, explicitly describe
  the result as approximate.
- Never imply that IP geolocation identifies the user's exact physical address.
- Do not invent missing coordinates or address details.
- If the lookup fails or returns incomplete information, state the limitation.
- Include coordinates only when relevant to the request.
- Avoid Markdown formatting by default.
- Do not use bold, italics, headings, bullet lists, or numbered lists for simple
  location answers.
- Use plain text unless formatting materially improves readability or the user
  requests it.
"""

REQUEST_SCHEMA = {
    "query": "location name, address, city, state, country, or US ZIP code",
    "current": "optional boolean; use true for approximate current location",
}

DESCRIPTION = (
    "Resolve a named location, US ZIP code, or the user's current approximate "
    "location into latitude/longitude and address information."
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
