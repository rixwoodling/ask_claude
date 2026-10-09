#!/usr/bin/env python3
"""Simple last-message memory capability."""

import json
from pathlib import Path


CAPABILITY = "memory"

DESCRIPTION = (
    "Remembers the user's most recent message. "
    "Use when the user asks what they just said, what they last said, "
    "or asks to recall the immediately previous statement."
)

REQUEST_SCHEMA = {
    "action": "required action: remember or recall",
    "message": "required when action is remember; message to store",
}

PLANNER_INSTRUCTIONS = (
    "Use the memory capability when the user asks to recall or remember "
    "their immediately previous statement. For recall requests, use "
    "{\"action\":\"recall\"}. For remember requests, use "
    "{\"action\":\"remember\",\"message\":\"...\"} with "
    "the exact message the user wants stored."
)

MEMORY_FILE = (
    Path(__file__).resolve().parent.parent / "memory" / "last_message.json"
)


def _load_memory():
    if not MEMORY_FILE.exists():
        return None

    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_memory(message):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "message": message,
    }

    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_lookup(request):
    action = request.get("action", "recall")
    message = request.get("message")

    if action == "remember":
        if not message:
            return {"error": "No message was provided to remember."}

        _save_memory(message)

        return {
            "remembered": True,
            "message": message,
        }

    if action == "recall":
        memory = _load_memory()

        if not memory:
            return {
                "remembered": False,
                "message": None,
            }

        return {
            "remembered": True,
            "message": memory.get("message"),
        }

    return {
        "error": f"Unknown memory action: {action}"
    }
