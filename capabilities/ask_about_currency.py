#!/usr/bin/env python3
"""Currency exchange capability using the public Frankfurter API."""

import requests

CAPABILITY = "currency"

DESCRIPTION = (
    "Provides current or historical foreign exchange rates and currency "
    "conversion."
)

REQUEST_SCHEMA = {
    "from_currency": "required ISO 4217 currency code",
    "to_currency": "required ISO 4217 currency code",
    "amount": "optional numeric amount",
    "date": "optional YYYY-MM-DD historical date",
}

API_URL = "https://api.frankfurter.dev/v2/rate"


def run_lookup(request):
    from_currency = request.get("from_currency")
    to_currency = request.get("to_currency")

    if not from_currency:
        return {"error": "Missing source currency (from_currency)."}

    if not to_currency:
        return {"error": "Missing target currency (to_currency)."}

    from_currency = str(from_currency).upper()
    to_currency = str(to_currency).upper()

    url = f"{API_URL}/{from_currency}/{to_currency}"

    params = {}
    date = request.get("date")
    if date:
        params["date"] = date

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None

        if status == 422:
            return {
                "error": (
                    f"Unsupported currency or invalid currency pair: "
                    f"{from_currency}/{to_currency}."
                ),
                "from_currency": from_currency,
                "to_currency": to_currency,
            }

        return {
            "error": (
                f"Currency service returned HTTP {status or 'error'} "
                f"for {from_currency}/{to_currency}."
            ),
            "from_currency": from_currency,
            "to_currency": to_currency,
        }

    except requests.RequestException as exc:
        return {
            "error": "Currency service is temporarily unavailable.",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "details": str(exc),
        }

    except (ValueError, KeyError, TypeError):
        return {
            "error": "Currency service returned an invalid response.",
            "from_currency": from_currency,
            "to_currency": to_currency,
        }

    result = {
        "date": data["date"],
        "base": data["base"],
        "quote": data["quote"],
        "rate": data["rate"],
    }

    amount = request.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return {
                "error": f"Invalid amount: {amount}",
                "from_currency": from_currency,
                "to_currency": to_currency,
            }

        result["amount"] = amount
        result["converted"] = amount * float(data["rate"])

    return result
