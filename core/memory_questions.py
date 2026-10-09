"""Model-agnostic detection of simple memory questions."""


def is_direct_memory_question(question):
    normalized = " ".join(question.lower().split())

    patterns = (
        "what was my last question",
        "what was my previous question",
        "what did i ask last",
        "what did i ask previously",
        "what was the last thing i asked",
        "what was the previous thing i asked",
    )

    return any(pattern in normalized for pattern in patterns)


def get_previous_user_question(recent_messages):
    """Return the most recent user message from prior conversation."""
    for message in reversed(recent_messages):
        if message.get("role") == "user":
            return message.get("content", "")

    return None
