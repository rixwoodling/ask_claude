#!/usr/bin/env python3
"""Google News RSS search capability."""

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

CAPABILITY = "news"

DESCRIPTION = (
    "Searches Google News RSS for current news about any custom topic, "
    "person, team, company, place, event, or keyword phrase. Requires "
    "a query string and optionally accepts language, country, and edition "
    "parameters. Returns normalized article titles, sources, publication "
    "times, descriptions, and URLs."
)

REQUEST_SCHEMA = {
    "query": "required news topic, person, team, company, place, event, or keyword phrase",
    "language": "optional language/locale such as en-US",
    "country": "optional two-letter country code such as US",
    "edition": "optional Google News edition such as US:en",
    "limit": "optional integer from 1 to 50",
}

PLANNER_INSTRUCTIONS = (
    "For current news questions, use the news capability with a concise "
    "query describing the topic, person, team, company, place, event, or "
    "keyword phrase. Preserve important names and specific topics from the "
    "user's question. Use a higher article limit when the user asks for a "
    "summary or multiple headlines. Do not invent a news topic or broaden "
    "the query unnecessarily."
)

API_URL = "https://news.google.com/rss/search"


def _clean_text(value):
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def run_lookup(request):
    query = request.get("query")
    if not query or not str(query).strip():
        return {"error": "Missing news search query."}

    query = str(query).strip()
    language = str(request.get("language", "en-US"))
    country = str(request.get("country", "US"))
    edition = str(request.get("edition", "US:en"))

    try:
        limit = max(1, min(int(request.get("limit", 10)), 50))
    except (TypeError, ValueError):
        return {"error": "Invalid article limit."}

    params = {"q": query, "hl": language, "gl": country, "ceid": edition}

    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=10,
            headers={"User-Agent": "local-personal-assistant/1.0"},
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        return {"error": f"Google News RSS returned HTTP {status or 'error'}.", "query": query}
    except requests.RequestException:
        return {"error": "Google News RSS request failed.", "query": query}

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return {"error": "Google News RSS returned invalid XML.", "query": query}

    articles = []
    for item in root.findall("./channel/item")[:limit]:
        source_element = item.find("source")
        articles.append({
            "title": _clean_text(item.findtext("title")),
            "source": _clean_text(source_element.text if source_element is not None else ""),
            "published": item.findtext("pubDate"),
            "description": _clean_text(item.findtext("description")),
            "url": item.findtext("link"),
        })

    return {
        "source": "Google News RSS",
        "query": query,
        "language": language,
        "country": country,
        "article_count": len(articles),
        "articles": articles,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    print(json.dumps(run_lookup({"query": args.query, "limit": args.limit}), indent=2, ensure_ascii=False))
