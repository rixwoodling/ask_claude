"""Model-agnostic preparation of retrieved capability results."""

import json


def compact_result(name, result):
    """Keep answer-relevant fields from large capability results."""
    if name != "weather" or not isinstance(result, dict):
        return result

    return {
        "location": result.get("location"),
        "timezone": result.get("timezone"),
        "forecast": [
            {
                "date": item.get("date"),
                "weather": item.get("weather"),
                "high_f": item.get("high_f"),
                "low_f": item.get("low_f"),
                "precipitation_probability": item.get(
                    "precipitation_probability"
                ),
            }
            for item in result.get("forecast", [])
        ],
    }


def compact_results(results):
    """Return a smaller, model-neutral representation of lookup results."""
    return {
        name: compact_result(name, result)
        for name, result in results.items()
    }


def results_as_json(results):
    """Serialize compact lookup results for any LLM adapter."""
    return json.dumps(
        compact_results(results),
        separators=(",", ":"),
        ensure_ascii=False,
    )


def format_memory(messages, limit=2):
    """Format a small recent conversation window for an LLM adapter."""
    if not messages:
        return "(none)"

    return "\n".join(
        f"{message.get('role', 'unknown')}: "
        f"{message.get('content', '')}"
        for message in messages[-limit:]
    )
