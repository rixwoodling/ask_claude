#!/usr/bin/env python3
"""Open Library book search capability.

Supports:
    1. Specific book lookup
       Example: "What is Moby Dick about?"

    2. Book discovery/recommendation
       Example: "What's a good fiction novel including whales?"

No API key is required.
"""

import argparse
import json
import re

import requests


CAPABILITY = "books"

DESCRIPTION = (
    "Searches Open Library for books, novels, stories, and authors. "
    "Supports both identifying specific books and discovering books "
    "matching genres, subjects, themes, characters, or other criteria. "
    "Returns normalized metadata, descriptions, subjects, characters, "
    "places, and excerpts when available. No API key is required."
)

REQUEST_SCHEMA = {
    "query": (
        "required book title, author, genre, subject, theme, "
        "character, or other book search terms"
    ),
    "mode": (
        "optional: 'specific' for identifying a particular book, "
        "'discover' for finding books matching criteria, or "
        "'similar' for finding books similar to a specified book"
    ),
    "limit": "optional integer from 1 to 10",
}

PLANNER_INSTRUCTIONS = (
    "Use the books capability whenever the user asks about books, "
    "novels, stories, authors, plots, characters, themes, genres, "
    "subjects, recommendations, or what a book is about. "

    "Use mode='specific' when the user refers to a particular book "
    "or asks about a known title. Extract the book title and use the "
    "title as the query. "

    "Use mode='discover' when the user asks for books matching "
    "genres, subjects, themes, characters, settings, topics, or other "
    "criteria. Extract the meaningful search criteria rather than "
    "the entire natural-language question. "

    "Use mode='similar' when the user asks for books similar to, "
    "like, related to, or comparable to a specific book. Extract "
    "the referenced book title as the query. The books capability "
    "will identify the source book, examine its subjects and other "
    "metadata, and search for related books. "

    "For example, 'What is Moby Dick about?' should use "
    "mode='specific' with query='Moby Dick'. "

    "For example, 'Which books are similar to Moby Dick?' should "
    "use mode='similar' with query='Moby Dick'. "

    "For example, 'Which books are fiction and include a whale?' "
    "should use mode='discover' with a query containing the relevant "
    "criteria such as 'fiction whale'. "

    "Do not use the entire natural-language question as the search "
    "query. Do not answer the question yourself."
)

SEARCH_URL = "https://openlibrary.org/search.json"
WORK_URL = "https://openlibrary.org"


def _clean_text(value):
    """Normalize text returned by Open Library."""
    if value is None:
        return ""

    if isinstance(value, str):
        return " ".join(value.split())

    return str(value)


def _extract_description(description):
    """Handle Open Library string or structured description values."""
    if not description:
        return ""

    if isinstance(description, dict):
        return _clean_text(description.get("value", ""))

    return _clean_text(description)


def _normalize_query(query):
    """Clean a planner-generated search query."""
    query = str(query).strip()

    # Remove accidental surrounding quotation marks.
    if len(query) >= 2:
        if (
            query[0] == query[-1]
            and query[0] in {"\"", "'"}
        ):
            query = query[1:-1].strip()

    return query


def _search_books(query, limit):
    """Search Open Library."""
    params = {
        "q": query,
        "limit": limit,
    }

    try:
        response = requests.get(
            SEARCH_URL,
            params=params,
            timeout=10,
            headers={
                "User-Agent": "local-personal-assistant/1.0",
            },
        )
        response.raise_for_status()

    except requests.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else None
        )

        return {
            "error": (
                f"Open Library search returned HTTP "
                f"{status or 'error'}."
            ),
            "query": query,
        }

    except requests.RequestException as exc:
        return {
            "error": "Open Library search request failed.",
            "query": query,
            "details": str(exc),
        }

    try:
        data = response.json()

    except ValueError:
        return {
            "error": "Open Library returned invalid JSON.",
            "query": query,
        }

    return {
        "num_found": data.get("numFound", 0),
        "docs": data.get("docs", []),
    }


def _get_work(work_key):
    """Retrieve detailed information for an Open Library work."""
    if not work_key:
        return {
            "error": "Missing Open Library work key."
        }

    if not isinstance(work_key, str):
        return {
            "error": "Invalid Open Library work key."
        }

    if not work_key.startswith("/works/"):
        return {
            "error": "Invalid Open Library work key.",
            "work_key": work_key,
        }

    url = f"{WORK_URL}{work_key}.json"

    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "local-personal-assistant/1.0",
            },
        )
        response.raise_for_status()

    except requests.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else None
        )

        return {
            "error": (
                f"Open Library work lookup returned HTTP "
                f"{status or 'error'}."
            ),
            "work_key": work_key,
        }

    except requests.RequestException as exc:
        return {
            "error": "Open Library work request failed.",
            "work_key": work_key,
            "details": str(exc),
        }

    try:
        return response.json()

    except ValueError:
        return {
            "error": "Open Library returned invalid JSON.",
            "work_key": work_key,
        }


def _score_specific_result(doc, query):
    """
    Score a search result for a specific-book lookup.

    Open Library can return multiple editions, translations,
    adaptations, and similarly named works. Prefer actual work
    records and exact title matches.
    """
    score = 0

    key = doc.get("key", "")
    title = _clean_text(doc.get("title", ""))
    query_lower = query.lower().strip()
    title_lower = title.lower().strip()

    if isinstance(key, str) and key.startswith("/works/"):
        score += 20

    if title_lower == query_lower:
        score += 100

    elif query_lower in title_lower:
        score += 50

    elif title_lower in query_lower:
        score += 30

    # Prefer records with an author.
    if doc.get("author_name"):
        score += 10

    # Prefer older canonical works when several results are similar.
    year = doc.get("first_publish_year")

    if isinstance(year, int):
        if year < 1950:
            score += 5

    return score


def _select_specific_work(docs, query):
    """Select the most likely work for a specific-book request."""
    if not docs:
        return None

    ranked = sorted(
        docs,
        key=lambda doc: _score_specific_result(
            doc,
            query,
        ),
        reverse=True,
    )

    for doc in ranked:
        key = doc.get("key", "")

        if (
            isinstance(key, str)
            and key.startswith("/works/")
        ):
            return doc

    return ranked[0]


def _normalize_work(search_doc, work):
    """Create compact normalized information for a specific work."""
    title = (
        work.get("title")
        or search_doc.get("title")
        or ""
    )

    authors = []

    for author in search_doc.get("author_name", []) or []:
        author = _clean_text(author)

        if author and author not in authors:
            authors.append(author)

    description = _extract_description(
        work.get("description")
    )

    subjects = []

    for subject in work.get("subjects", []) or []:
        subject = _clean_text(subject)

        if subject and subject not in subjects:
            subjects.append(subject)

        if len(subjects) >= 15:
            break

    characters = []

    for person in work.get("subject_people", []) or []:
        person = _clean_text(person)

        if person and person not in characters:
            characters.append(person)

        if len(characters) >= 15:
            break

    places = []

    for place in work.get("subject_places", []) or []:
        place = _clean_text(place)

        if place and place not in places:
            places.append(place)

        if len(places) >= 15:
            break

    excerpts = []

    for excerpt in work.get("excerpts", []) or []:
        if not isinstance(excerpt, dict):
            continue

        text = _clean_text(
            excerpt.get("excerpt")
        )

        if not text:
            continue

        item = {
            "text": text,
        }

        comment = excerpt.get("comment")

        if comment:
            item["comment"] = _clean_text(comment)

        excerpts.append(item)

        if len(excerpts) >= 5:
            break

    work_key = (
        work.get("key")
        or search_doc.get("key")
    )

    return {
        "title": title,
        "authors": authors,
        "first_publish_year": search_doc.get(
            "first_publish_year"
        ),
        "work_key": work_key,
        "description": description,
        "subjects": subjects,
        "characters": characters,
        "places": places,
        "excerpts": excerpts,
        "open_library_url": (
            f"{WORK_URL}{work_key}"
            if work_key
            else ""
        ),
    }


def _normalize_discovery_result(doc):
    """Create compact information for a discovery result."""
    key = doc.get("key", "")

    authors = []

    for author in doc.get("author_name", []) or []:
        author = _clean_text(author)

        if author and author not in authors:
            authors.append(author)

    subjects = []

    for subject in doc.get("subject", []) or []:
        subject = _clean_text(subject)

        if subject and subject not in subjects:
            subjects.append(subject)

        if len(subjects) >= 10:
            break

    return {
        "title": _clean_text(
            doc.get("title")
        ),
        "authors": authors,
        "first_publish_year": doc.get(
            "first_publish_year"
        ),
        "work_key": key,
        "subjects": subjects,
        "edition_count": doc.get(
            "edition_count"
        ),
        "open_library_url": (
            f"{WORK_URL}{key}"
            if key
            else ""
        ),
    }


def _run_specific(query, limit):
    """Resolve a specific book and retrieve its Work record."""
    search_result = _search_books(
        query,
        limit,
    )

    if "error" in search_result:
        return search_result

    docs = search_result.get("docs", [])

    if not docs:
        return {
            "source": "Open Library",
            "mode": "specific",
            "query": query,
            "book_count": 0,
            "books": [],
        }

    selected = _select_specific_work(
        docs,
        query,
    )

    if not selected:
        return {
            "source": "Open Library",
            "mode": "specific",
            "query": query,
            "book_count": 0,
            "books": [],
        }

    work_key = selected.get("key")

    if not work_key:
        return {
            "source": "Open Library",
            "mode": "specific",
            "query": query,
            "error": (
                "Open Library search result has no work key."
            ),
        }

    work = _get_work(work_key)

    if "error" in work:
        return {
            "source": "Open Library",
            "mode": "specific",
            "query": query,
            "work_key": work_key,
            "error": work["error"],
        }

    book = _normalize_work(
        selected,
        work,
    )

    return {
        "source": "Open Library",
        "mode": "specific",
        "query": query,
        "book_count": 1,
        "books": [book],
    }


def _run_discovery(query, limit):
    """Find multiple books matching discovery criteria."""
    search_result = _search_books(
        query,
        limit,
    )

    if "error" in search_result:
        return search_result

    docs = search_result.get("docs", [])

    books = []

    seen_keys = set()

    for doc in docs:
        key = doc.get("key")

        if key in seen_keys:
            continue

        seen_keys.add(key)

        books.append(
            _normalize_discovery_result(doc)
        )

    return {
        "source": "Open Library",
        "mode": "discover",
        "query": query,
        "book_count": len(books),
        "books": books,
    }


def run_lookup(request):
    """
    Run an Open Library book lookup.

    Specific example:

        {
            "query": "Moby Dick",
            "mode": "specific",
            "limit": 5
        }

    Discovery example:

        {
            "query": "fiction cats",
            "mode": "discover",
            "limit": 5
        }
    """
    if not isinstance(request, dict):
        return {
            "error": "Book lookup request must be an object."
        }

    query = request.get("query")

    if not query or not str(query).strip():
        return {
            "error": "Missing book search query."
        }

    query = _normalize_query(query)

    mode = str(
        request.get("mode", "specific")
    ).strip().lower()

    if mode not in {
        "specific",
        "discover",
    }:
        return {
            "error": (
                "Invalid book lookup mode. "
                "Use 'specific' or 'discover'."
            )
        }

    try:
        limit = int(
            request.get("limit", 5)
        )

    except (TypeError, ValueError):
        return {
            "error": "Invalid book result limit."
        }

    limit = max(1, min(limit, 10))

    if mode == "discover":
        return _run_discovery(
            query,
            limit,
        )

    return _run_specific(
        query,
        limit,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Search Open Library for books."
        )
    )

    parser.add_argument(
        "query",
        help=(
            "Book title, author, genre, subject, "
            "theme, or search terms"
        ),
    )

    parser.add_argument(
        "--mode",
        choices=[
            "specific",
            "discover",
        ],
        default="specific",
        help=(
            "specific identifies a book; "
            "discover finds matching books"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help=(
            "Maximum number of results "
            "(1-10)"
        ),
    )

    args = parser.parse_args()

    result = run_lookup(
        {
            "query": args.query,
            "mode": args.mode,
            "limit": args.limit,
        }
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
