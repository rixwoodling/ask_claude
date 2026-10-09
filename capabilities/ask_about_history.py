#!/usr/bin/env python3
"""Historical research capability backed by Wikipedia/Wikimedia APIs.

Supports:
    - General historical topic searches
    - Historical people, places, periods, and events
    - Article summaries
    - On-this-day events, births, and deaths

No API key is required.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests


CAPABILITY = "history"

DESCRIPTION = (
    "Researches history using Wikipedia and Wikimedia's public APIs. "
    "Searches historical events, people, places, periods, and topics; "
    "retrieves article summaries with source URLs; and looks up events, "
    "births, or deaths associated with a month and day. No API key is required."
)

REQUEST_SCHEMA = {
    "query": (
        "optional historical topic, event, person, place, period, or article title; "
        "required for search and article modes"
    ),
    "mode": (
        "optional: 'search' for historical research, 'article' for a specific "
        "Wikipedia article, or 'on_this_day' for date-associated events"
    ),
    "date": (
        "optional date in YYYY-MM-DD or MM-DD format for on_this_day mode; "
        "defaults to today's month and day"
    ),
    "category": (
        "optional on_this_day category: 'events', 'births', 'deaths', or 'all'"
    ),
    "limit": "optional integer from 1 to 10",
    "language": "optional Wikipedia language code such as 'en' or 'zh'",
}

PLANNER_INSTRUCTIONS = (
    "Use the history capability for questions about historical events, "
    "people, places, civilizations, wars, historical periods, timelines, "
    "and what happened on a particular date. "
    "Use mode='search' for explanatory questions, broad topics, historical "
    "figures, causes, consequences, or comparisons. Pass a concise topic "
    "rather than the entire natural-language question. "
    "Use mode='article' when the user names a specific Wikipedia article "
    "or asks for a summary of a particular historical subject. "
    "Use mode='on_this_day' for 'on this day in history', historical events "
    "on a specific month/day, or notable births/deaths associated with a date. "
    "For on_this_day, pass date as YYYY-MM-DD or MM-DD when specified, and "
    "category='events', 'births', 'deaths', or 'all' as appropriate. Preserve "
    "the year when the user specifies one. For example, 'What happened on "
    "December 19th, 1978?' requires date='1978-12-19', not '12-19'. "
    "Do not invent facts or dates. Use the returned source URLs when composing "
    "an answer, and distinguish sourced facts from interpretation. "
    "For questions requiring explanation, synthesize the retrieved information "
    "rather than merely listing search results."
)

ACTION_API_URL = "https://en.wikipedia.org/w/api.php"
ON_THIS_DAY_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday"
USER_AGENT = "ask_claude_history/1.0 (historical research capability)"


def _clean_text(value: Any) -> str:
    """Normalize plain text returned by Wikimedia."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _limit(value: Any, default: int = 5) -> int:
    try:
        return max(1, min(int(value), 10))
    except (TypeError, ValueError):
        return default


def _request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make a JSON GET request with a descriptive user agent."""
    response = requests.get(
        url,
        params=params,
        timeout=15,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Wikimedia returned an unexpected response format.")
    return data


def _api_error(exc: Exception, source: str, query: Optional[str] = None) -> Dict[str, Any]:
    """Return a stable error shape without dumping a traceback to the planner."""
    result: Dict[str, Any] = {
        "source": source,
        "error": str(exc),
    }
    if query:
        result["query"] = query
    return result


def _search_pages(query: str, limit: int, language: str) -> Dict[str, Any]:
    """Search Wikipedia article titles and contents."""
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,20}", language):
        return {"error": "Invalid Wikipedia language code.", "query": query}

    url = f"https://{language}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": 0,
        "srlimit": limit,
        "srprop": "snippet|titlesnippet",
        "format": "json",
        "formatversion": 2,
    }

    try:
        data = _request_json(url, params)
    except requests.RequestException as exc:
        return _api_error(
            RuntimeError(f"Wikipedia search request failed: {exc}"),
            f"Wikipedia ({language})",
            query,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _api_error(
            RuntimeError(f"Wikipedia returned invalid JSON: {exc}"),
            f"Wikipedia ({language})",
            query,
        )

    pages = data.get("query", {}).get("search", [])
    titles = [page.get("title") for page in pages if page.get("title")]

    extracts: Dict[str, Dict[str, Any]] = {}
    if titles:
        extracts = _fetch_extracts(titles, language)

    results = []
    for page in pages:
        title = _clean_text(page.get("title"))
        details = extracts.get(title, {})
        results.append({
            "title": title,
            "snippet": _strip_html(page.get("snippet", "")),
            "summary": details.get("summary", ""),
            "url": details.get(
                "url",
                f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            ),
        })

    return {
        "source": f"Wikipedia ({language})",
        "mode": "search",
        "query": query,
        "result_count": len(results),
        "results": results,
    }


def _strip_html(value: Any) -> str:
    """Remove search-result markup and normalize text."""
    text = str(value or "")
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return _clean_text(text)


def _fetch_extracts(titles: List[str], language: str) -> Dict[str, Dict[str, Any]]:
    """Fetch short plain-text extracts for a batch of article titles."""
    if not titles:
        return {}

    url = f"https://{language}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "exsentences": 6,
        "inprop": "url",
        "redirects": 1,
        "titles": "|".join(titles),
        "format": "json",
        "formatversion": 2,
    }

    try:
        data = _request_json(url, params)
    except (requests.RequestException, ValueError):
        return {}

    output: Dict[str, Dict[str, Any]] = {}
    for page in data.get("query", {}).get("pages", []):
        title = _clean_text(page.get("title"))
        if page.get("missing") is not None:
            continue
        output[title] = {
            "summary": _clean_text(page.get("extract")),
            "url": page.get("fullurl"),
        }
    return output


def _article(query: str, language: str) -> Dict[str, Any]:
    """Retrieve a specific article's introductory summary."""
    if not query:
        return {"error": "Article mode requires a query."}
    result = _fetch_extracts([query], language)
    if not result:
        return {
            "source": f"Wikipedia ({language})",
            "mode": "article",
            "query": query,
            "error": "No article summary was found for that title.",
        }

    title, details = next(iter(result.items()))
    return {
        "source": f"Wikipedia ({language})",
        "mode": "article",
        "query": query,
        "title": title,
        "summary": details.get("summary", ""),
        "url": details.get("url") or (
            f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        ),
    }


def _parse_month_day(value: Any) -> tuple[int, int, Optional[int]]:
    """Parse YYYY-MM-DD or MM-DD and return month, day, optional year."""
    if value is None or not str(value).strip():
        today = date.today()
        return today.month, today.day, None

    value = str(value).strip()
    parts = value.split("-")
    try:
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
            date(year, month, day)  # Validate the complete date.
            return month, day, year
        if len(parts) == 2:
            month, day = (int(part) for part in parts)
            date(2000, month, day)  # Leap-year validation for month/day.
            return month, day, None
    except (TypeError, ValueError):
        raise ValueError("date must be YYYY-MM-DD or MM-DD.")

    raise ValueError("date must be YYYY-MM-DD or MM-DD.")


def _infer_date_from_query(query: str) -> Optional[str]:
    """Extract a clearly stated date from a natural-language history question."""
    text = _clean_text(query)
    if not text:
        return None

    # ISO date, e.g. 1978-12-19.
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        candidate = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        try:
            date.fromisoformat(candidate)
            return candidate
        except ValueError:
            return None

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
        "nov": 11, "dec": 12,
    }
    month_pattern = "|".join(sorted(months, key=len, reverse=True))
    match = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        # Also accept 19 December 1978.
        match = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})(?:,?\s+(\d{{4}}))?\b",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        day = int(match.group(1))
        month = months[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else None
    else:
        month = months[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None

    try:
        if year is not None:
            date(year, month, day)
            return f"{year:04d}-{month:02d}-{day:02d}"
        date(2000, month, day)
        return f"{month:02d}-{day:02d}"
    except ValueError:
        return None


def _on_this_day(
    date_value: Any,
    category: str,
    limit: int,
    language: str,
) -> Dict[str, Any]:
    """Retrieve date-associated events, births, and/or deaths."""
    if category not in {"events", "births", "deaths", "all"}:
        return {
            "error": "category must be events, births, deaths, or all.",
            "category": category,
        }

    try:
        month, day, year = _parse_month_day(date_value)
    except ValueError as exc:
        return {"error": str(exc), "date": date_value}

    types = (
        ["events", "births", "deaths"]
        if category == "all"
        else [category]
    )
    results = []
    try:
        for item_type in types:
            url = (
                f"https://{language}.wikipedia.org/api/rest_v1/feed/"
                f"onthisday/{item_type}/{month:02d}/{day:02d}"
            )
            data = _request_json(url)
            for item in data.get(item_type, []):
                item_year = item.get("year")
                if year is not None and item_year != year:
                    continue
                page_links = item.get("pages") or []
                page = page_links[0] if page_links else {}
                results.append({
                    "category": item_type,
                    "year": item_year,
                    "text": _clean_text(item.get("text")),
                    "pages": [
                        {
                            "title": _clean_text(p.get("title")),
                            "description": _clean_text(p.get("description")),
                            "url": p.get("content_urls", {})
                                .get("desktop", {})
                                .get("page"),
                        }
                        for p in page_links[:3]
                    ],
                    "url": page.get("content_urls", {})
                        .get("desktop", {})
                        .get("page"),
                })
    except requests.RequestException as exc:
        return _api_error(
            RuntimeError(f"Wikipedia On This Day request failed: {exc}"),
            f"Wikipedia ({language})",
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _api_error(
            RuntimeError(f"Wikipedia On This Day returned invalid data: {exc}"),
            f"Wikipedia ({language})",
        )

    # Wikimedia's curated On This Day feed does not include every historical
    # date. If an exact year was requested but no item exists in the feed, try
    # a targeted Wikipedia search rather than returning unrelated years.
    if year is not None and not results:
        month_name = date(year, month, day).strftime("%B")
        date_query = f"{month_name} {day}, {year} historical events"
        fallback = _search_pages(date_query, min(limit, 3), language)
        return {
            "source": f"Wikipedia ({language})",
            "mode": "search",
            "requested_mode": "on_this_day",
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "category": category,
            "fallback_reason": "The On This Day feed had no entry for that exact year; searched Wikipedia instead.",
            "query": date_query,
            "result_count": fallback.get("result_count", 0),
            "results": fallback.get("results", []),
            **({"error": fallback["error"]} if fallback.get("error") else {}),
        }

    # Keep results in API order and cap the returned payload.
    results = results[:limit]
    return {
        "source": f"Wikipedia On This Day ({language})",
        "mode": "on_this_day",
        "date": f"{month:02d}-{day:02d}" if year is None else f"{year:04d}-{month:02d}-{day:02d}",
        "category": category,
        "result_count": len(results),
        "results": results,
    }


def build_simple_summary(result: Dict[str, Any]) -> str:
    """Build a compact deterministic summary for CLI callers."""
    if result.get("error"):
        return str(result["error"])

    mode = result.get("mode")

    if mode == "article":
        title = result.get("title") or result.get("query") or "Article"
        summary = result.get("summary") or "No summary available."
        return f"{title}: {summary} Source: {result.get('url', '')}".strip()

    results = result.get("results") or []
    if not results:
        return "No matching historical information was found."

    lines = []
    for item in results:
        if mode == "on_this_day":
            year = item.get("year", "Unknown year")
            event_text = item.get("text") or item.get("title") or "Historical event"
            lines.append(f"{year}: {event_text}")
        else:
            title = item.get("title") or "Untitled"
            summary = item.get("summary") or item.get("snippet") or ""
            lines.append(f"{title}: {summary}".strip())

    return "\n".join(lines)


def run_lookup(request: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point used by the ask_claude capability registry."""
    if request is None:
        request = {}
    if not isinstance(request, dict):
        return {"error": "History request must be a dictionary."}

    mode = str(request.get("mode") or "search").strip().lower()
    language = str(request.get("language") or "en").strip().lower()
    limit = _limit(request.get("limit"), default=5)
    query = _clean_text(request.get("query"))

    # Defensive routing: date questions sometimes arrive with mode="search"
    # or a month/day date that has lost its year. Recover a stated date from
    # the original question before calling the On This Day feed.
    inferred_date = _infer_date_from_query(query)
    if inferred_date and re.search(r"\b(what happened|events? on|on this day|history of what happened)\b", query, re.IGNORECASE):
        if mode == "search":
            mode = "on_this_day"
        if mode == "on_this_day" and len(str(request.get("date") or "").split("-")) != 3 and len(inferred_date.split("-")) == 3:
            request = dict(request)
            request["date"] = inferred_date
        elif mode == "on_this_day" and not request.get("date"):
            request = dict(request)
            request["date"] = inferred_date

    if not re.fullmatch(r"[a-zA-Z0-9-]{1,20}", language):
        return {"error": "Invalid Wikipedia language code."}

    if mode == "on_this_day":
        category = str(request.get("category") or "events").strip().lower()
        return _on_this_day(
            request.get("date"),
            category,
            limit,
            language,
        )

    if mode == "article":
        return _article(query, language)

    if mode == "search":
        if not query:
            return {"error": "Search mode requires a historical query."}
        return _search_pages(query, limit, language)

    return {
        "error": "Unsupported history mode.",
        "mode": mode,
        "supported_modes": ["search", "article", "on_this_day"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search historical topics using Wikipedia (no API key required)."
    )
    parser.add_argument("query", nargs="?", help="Historical topic or article title")
    parser.add_argument(
        "--mode",
        choices=("search", "article", "on_this_day"),
        default="search",
    )
    parser.add_argument("--date", help="Date as YYYY-MM-DD or MM-DD for on_this_day")
    parser.add_argument(
        "--category",
        choices=("events", "births", "deaths", "all"),
        default="events",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--language", default="en")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    request = {
        "query": args.query,
        "mode": args.mode,
        "date": args.date,
        "category": args.category,
        "limit": args.limit,
        "language": args.language,
    }
    result = run_lookup(request)
    if args.compact:
        print(build_simple_summary(result))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
