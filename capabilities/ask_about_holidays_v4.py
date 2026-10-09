#!/usr/bin/env python3
"""Public holiday capability using the Nager.Date v4 API."""

import requests

CAPABILITY = "holidays"

DESCRIPTION = (
    "Provides public holidays for a country and year. "
    "Request fields: country_code (two-letter ISO country code) "
    "and year (four-digit year). For questions about today or a "
    "relative date, use the date capability to determine the date "
    "and year, then use the appropriate country_code."
)

API_URL = "https://nagerholidays.com/api/v4/Holidays"


def run_lookup(request):
    country_code = request.get("country_code")
    year = request.get("year")

    if not country_code:
        return {"error": "Missing country_code."}

    if not year:
        return {"error": "Missing year."}

    country_code = str(country_code).upper()

    try:
        year = int(year)
    except (TypeError, ValueError):
        return {"error": f"Invalid year: {year}"}

    url = f"{API_URL}/{country_code}/{year}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        if response.status_code == 204:
            return {
                "country_code": country_code,
                "year": year,
                "holidays": [],
            }

        try:
            data = response.json()
        except ValueError:
            return {
                "error": "Holiday service returned invalid JSON.",
                "country_code": country_code,
                "year": year,
            }

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None

        if status in (400, 404):
            return {
                "error": (
                    f"No public holiday data was found for "
                    f"{country_code} in {year}."
                ),
                "country_code": country_code,
                "year": year,
            }

        return {
            "error": (
                f"Holiday service returned HTTP {status or 'error'}."
            ),
            "country_code": country_code,
            "year": year,
        }

    except requests.RequestException as exc:
        return {
            "error": "Holiday service request failed.",
            "country_code": country_code,
            "year": year,
            "details": str(exc),
        }

    if not isinstance(data, list):
        return {
            "error": "Holiday service returned an unexpected response.",
            "country_code": country_code,
            "year": year,
        }

    holidays = []

    for holiday in data:
        holidays.append({
            "date": holiday.get("date"),
            "name": holiday.get("name"),
            "local_name": holiday.get("name"),
            "country_code": holiday.get("countryCode", country_code),
            "national": holiday.get("nationalHoliday"),
            "subdivisions": holiday.get("subdivisionCodes", []),
            "types": holiday.get("holidayTypes", []),
        })

    return {
        "country_code": country_code,
        "year": year,
        "holidays": holidays,
    }
