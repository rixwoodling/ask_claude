#!/usr/bin/env python3
"""Historical research capability using Wikipedia/Wikimedia public APIs."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from typing import Any
from urllib.parse import quote

import requests

CAPABILITY = "history"
DESCRIPTION = (
    "Researches historical events, people, places, civilizations, and periods "
    "using Wikipedia. Retrieves article summaries or events associated with a date."
)

REQUEST_SCHEMA = {
    "query": "Historical topic, event, person, place, period, or article title",
    "mode": "search, article, or on_this_day",
    "date": "YYYY-MM-DD or MM-DD for on_this_day",
    "category": "events, births, deaths, or all",
    "limit": "Optional integer from 1 to 10; defaults to 3",
    "language": "Optional Wikipedia language code, default en",
}

# These rules are consumed by ask_claude.py when composing an answer from this
# capability's results. Keep them domain-specific; global style belongs in
# rules/general.py.
ANSWER_RULES = """
- Use only the supplied history results as factual sources.
- Answer the user's exact historical question; do not give a general history lesson unless requested.
- Be concise: normally one to three short sentences or at most three brief bullets.
- For an on-this-day question without a requested year, list no more than three notable events.
- For a specific date and year, discuss only events supported for that exact date and year.
- If the retrieved results do not establish what happened on the requested date, say that the available sources did not establish it. Do not substitute events from other years.
- Do not repeat the same event in different wording.
- Avoid long background explanations, inflated introductions, and unnecessary conclusions.
- Include dates and source URLs only when useful to answer the question.
"""

PLANNER_INSTRUCTIONS = (
    "Use this capability for historical questions about events, people, places, "
    "civilizations, wars, and periods. Use mode='search' for broad/explanatory "
    "questions, mode='article' for a named article, and mode='on_this_day' for "
    "events on a particular date. Preserve the year when supplied. Pass dates "
    "as YYYY-MM-DD or MM-DD. For date questions, default to category='events' "
    "and limit=3. Do not invent facts. The final answer should follow ANSWER_RULES."
)

USER_AGENT = "ask_claude_history/1.2"
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _limit(value: Any, default: int = 3) -> int:
    try:
        return max(1, min(int(value), 10))
    except (TypeError, ValueError):
        return default


def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        url, params=params, timeout=15,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected response format from Wikimedia.")
    return data


def _extracts(titles: list[str], language: str) -> dict[str, dict[str, str]]:
    if not titles:
        return {}
    data = _get_json(f"https://{language}.wikipedia.org/w/api.php", {
        "action": "query", "prop": "extracts|info", "exintro": 1,
        "explaintext": 1, "exsentences": 4, "inprop": "url",
        "redirects": 1, "titles": "|".join(titles),
        "format": "json", "formatversion": 2,
    })
    output = {}
    for page in data.get("query", {}).get("pages", []):
        if page.get("missing") is not None:
            continue
        title = _clean(page.get("title"))
        output[title] = {
            "summary": _clean(page.get("extract")),
            "url": page.get("fullurl") or (
                f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            ),
        }
    return output


def _search_terms(query: str) -> list[str]:
    """Extract useful content words without assuming a particular topic."""
    stopwords = {
        "a", "an", "and", "are", "about", "by", "did", "do", "does",
        "for", "from", "happened", "how", "in", "is", "it", "like", "of",
        "on", "or", "the", "to", "was", "were", "what", "when", "where",
        "which", "who", "why", "with", "tell", "me", "give", "history",
    }
    words = re.findall(r"[\w'-]+", query.lower())
    return [word for word in words if word not in stopwords and len(word) > 1]


def _search_variants(query: str) -> list[str]:
    """Build a small set of query variants mechanically from the user's query."""
    variants = [query.strip()]
    terms = _search_terms(query)
    reduced = " ".join(terms)
    if reduced and reduced.casefold() != query.strip().casefold():
        variants.append(reduced)
    # A quoted core phrase can help when the query contains several content words.
    if len(terms) >= 2:
        phrase = '"' + " ".join(terms[:5]) + '"'
        if phrase not in variants:
            variants.append(phrase)
    return list(dict.fromkeys(v for v in variants if v))[:3]


def _relevance_score(query_terms: list[str], item: dict[str, str]) -> float:
    """Rank candidates with local lexical evidence; no model call is made."""
    title = set(re.findall(r"[\w'-]+", item.get("title", "").lower()))
    snippet = set(re.findall(r"[\w'-]+", item.get("snippet", "").lower()))
    summary = set(re.findall(r"[\w'-]+", item.get("summary", "").lower()))
    if not query_terms:
        return 0.0
    title_hits = sum(term in title for term in query_terms)
    snippet_hits = sum(term in snippet for term in query_terms)
    summary_hits = sum(term in summary for term in query_terms)
    # Title matches carry more weight; summary matches help distinguish relevant
    # articles from pages that only mention the subject in passing.
    return (title_hits * 4.0) + (snippet_hits * 1.5) + (summary_hits * 1.0)


def _search(query: str, limit: int, language: str) -> dict[str, Any]:
    # Search several mechanically derived variants, gather a candidate pool,
    # then rank locally. This works across topics without topic-specific rules.
    variants = _search_variants(query)
    candidates: dict[str, dict[str, str]] = {}
    errors = []
    per_query_limit = max(5, min(10, limit * 3))

    for variant in variants:
        try:
            data = _get_json(f"https://{language}.wikipedia.org/w/api.php", {
                "action": "query", "list": "search", "srsearch": variant,
                "srnamespace": 0, "srlimit": per_query_limit,
                "srprop": "snippet", "format": "json", "formatversion": 2,
            })
        except (requests.RequestException, ValueError) as exc:
            errors.append(str(exc))
            continue

        for rank, page in enumerate(data.get("query", {}).get("search", [])):
            title = _clean(page.get("title"))
            if not title:
                continue
            snippet = re.sub(r"<[^>]*>", " ", str(page.get("snippet") or ""))
            candidate = candidates.setdefault(title, {
                "title": title, "snippet": _clean(snippet), "summary": "", "url": "",
                "_search_score": 0.0,
            })
            # Retain Wikipedia's own ranking signal across all query variants.
            # Reciprocal-rank weighting favors results near the top of each list.
            candidate["_search_score"] += 1.0 / (rank + 1)
            # Keep the most informative snippet if a title appears more than once.
            if len(_clean(snippet)) > len(candidate["snippet"]):
                candidate["snippet"] = _clean(snippet)

    if not candidates and errors:
        raise requests.RequestException("; ".join(errors[:2]))

    titles = list(candidates)
    try:
        details = _extracts(titles, language)
    except (requests.RequestException, ValueError):
        details = {}

    for title, candidate in candidates.items():
        detail = details.get(title, {})
        candidate["summary"] = detail.get("summary", "")
        candidate["url"] = detail.get("url") or (
            f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        )

    query_terms = _search_terms(query)
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            _relevance_score(query_terms, item) + item.get("_search_score", 0.0),
            bool(item.get("summary")),
        ),
        reverse=True,
    )
    results = ranked[:limit]
    for item in results:
        item.pop("_search_score", None)
    return {
        "source": f"Wikipedia ({language})", "mode": "search", "query": query,
        "query_variants": variants, "candidate_count": len(candidates),
        "result_count": len(results), "results": results,
    }


def _parse_date(value: Any) -> tuple[int, int, int | None]:
    if not value:
        today = date.today()
        return today.month, today.day, None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            year, month, day = map(int, parts)
            date(year, month, day)
            return month, day, year
        if len(parts) == 2:
            month, day = map(int, parts)
            date(2000, month, day)
            return month, day, None
    except ValueError:
        pass
    raise ValueError("date must be YYYY-MM-DD or MM-DD")


def _infer_date(text: str) -> str | None:
    text = _clean(text)
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            return None

    pattern = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.search(
        rf"\b({pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
        text, re.I,
    )
    if match:
        month, day = MONTHS[match.group(1).lower()], int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
    else:
        match = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({pattern})(?:,?\s+(\d{{4}}))?\b",
            text, re.I,
        )
        if not match:
            return None
        day, month = int(match.group(1)), MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else None

    try:
        if year is not None:
            return date(year, month, day).isoformat()
        date(2000, month, day)
        return f"{month:02d}-{day:02d}"
    except ValueError:
        return None


def _on_this_day(value: Any, category: str, limit: int, language: str) -> dict[str, Any]:
    if category not in {"events", "births", "deaths", "all"}:
        return {"error": "category must be events, births, deaths, or all"}
    try:
        month, day, year = _parse_date(value)
    except ValueError as exc:
        return {"error": str(exc), "date": value}

    categories = ["events", "births", "deaths"] if category == "all" else [category]
    results = []
    try:
        for kind in categories:
            data = _get_json(
                f"https://{language}.wikipedia.org/api/rest_v1/feed/"
                f"onthisday/{kind}/{month:02d}/{day:02d}"
            )
            for item in data.get(kind, []):
                if year is not None and item.get("year") != year:
                    continue
                pages = item.get("pages") or []
                results.append({
                    "category": kind, "year": item.get("year"),
                    "text": _clean(item.get("text")),
                    "url": (pages[0].get("content_urls", {}).get("desktop", {}).get("page")
                            if pages else None),
                    "pages": [{
                        "title": _clean(p.get("title")),
                        "url": p.get("content_urls", {}).get("desktop", {}).get("page"),
                    } for p in pages[:2]],
                })
    except (requests.RequestException, ValueError) as exc:
        return {"source": f"Wikipedia ({language})", "error": f"On This Day request failed: {exc}"}

    if year is not None and not results:
        month_name = date(year, month, day).strftime("%B")
        fallback = _search(f"{month_name} {day}, {year} historical events", min(limit, 3), language)
        fallback.update({
            "requested_mode": "on_this_day",
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "fallback_reason": "No exact-year entry in the curated On This Day feed; searched Wikipedia instead.",
        })
        return fallback

    return {
        "source": f"Wikipedia On This Day ({language})",
        "mode": "on_this_day",
        "date": f"{year:04d}-{month:02d}-{day:02d}" if year else f"{month:02d}-{day:02d}",
        "category": category, "result_count": min(len(results), limit),
        "results": results[:limit],
    }


def run_lookup(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {"error": "History request must be a dictionary."}
    mode = _clean(request.get("mode") or "search").lower()
    language = _clean(request.get("language") or "en").lower()
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,20}", language):
        return {"error": "Invalid Wikipedia language code."}
    limit = _limit(request.get("limit"), 3)
    query = _clean(request.get("query"))

    inferred = _infer_date(query)
    if inferred and re.search(
        r"\b(what happened|events? on|on this day|history of what happened)\b",
        query, re.I,
    ):
        if mode == "search":
            mode = "on_this_day"
        if mode == "on_this_day" and (
            not request.get("date")
            or (len(str(request.get("date")).split("-")) != 3 and len(inferred.split("-")) == 3)
        ):
            request = {**request, "date": inferred}

    try:
        if mode == "on_this_day":
            return _on_this_day(
                request.get("date"), _clean(request.get("category") or "events").lower(),
                limit, language,
            )
        if mode == "article":
            if not query:
                return {"error": "Article mode requires a query."}
            details = _extracts([query], language)
            if not details:
                return {"source": f"Wikipedia ({language})", "mode": "article",
                        "query": query, "error": "No article summary was found."}
            title, detail = next(iter(details.items()))
            return {"source": f"Wikipedia ({language})", "mode": "article",
                    "query": query, "title": title, **detail}
        if mode == "search":
            if not query:
                return {"error": "Search mode requires a query."}
            return _search(query, limit, language)
        return {"error": "Unsupported mode.", "mode": mode,
                "supported_modes": ["search", "article", "on_this_day"]}
    except (requests.RequestException, ValueError) as exc:
        return {"source": f"Wikipedia ({language})", "error": f"Wikipedia request failed: {exc}"}


def build_simple_summary(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])
    if result.get("mode") == "article":
        return f"{result.get('title') or result.get('query')}: {result.get('summary', '')} Source: {result.get('url', '')}".strip()
    lines = []
    for item in result.get("results", []):
        if result.get("mode") == "on_this_day":
            lines.append(f"{item.get('year', 'Unknown year')}: {item.get('text', '')}")
        else:
            lines.append(f"{item.get('title', 'Untitled')}: {item.get('summary') or item.get('snippet', '')}")
    return "\n".join(lines) if lines else "No matching historical information was found."


def main() -> int:
    parser = argparse.ArgumentParser(description="Search historical topics using Wikipedia.")
    parser.add_argument("query", nargs="?", help="Historical topic or article title")
    parser.add_argument("--mode", choices=("search", "article", "on_this_day"), default="search")
    parser.add_argument("--date", help="YYYY-MM-DD or MM-DD for on_this_day")
    parser.add_argument("--category", choices=("events", "births", "deaths", "all"), default="events")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--language", default="en")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = run_lookup({
        "query": args.query, "mode": args.mode, "date": args.date,
        "category": args.category, "limit": args.limit, "language": args.language,
    })
    print(build_simple_summary(result) if args.compact else json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
