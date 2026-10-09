#!/usr/bin/env python3
"""Claude assistant using model-agnostic core components.

Architecture:
    Memory -> Claude planner -> capability execution -> Claude answer
    Claude-specific behavior stays in this file.
    Reusable assistant logic lives in core/.
"""
import sys
import argparse
import json

from anthropic import Anthropic

from capability_registry import (
    CAPABILITIES,
    capability_instructions,
    capability_schemas,
)
from memory import add_message, get_recent_messages
from rules.general import GENERAL_ANSWER_RULES
from rules.intent import INTENT_RULES
from rules.composed import COMPOSED_ANSWER_RULES
import importlib
from rules.planner import PLANNER_RULES

from core.answer import format_memory, results_as_json
from core.executor import execute_lookups
from core.memory_questions import (
    get_previous_user_question,
    is_direct_memory_question,
)
from core.plan import validate_plan


MODEL = "claude-haiku-4-5-20251001"


def call_claude(prompt, system=None, max_tokens=500):
    """Claude-specific API call."""
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    if system:
        kwargs["system"] = system

    response = Anthropic().messages.create(**kwargs)

    text = "".join(
        block.text
        for block in response.content
        if hasattr(block, "text")
    ).strip()

    usage = response.usage

    return text, {
        "input": getattr(usage, "input_tokens", 0),
        "output": getattr(usage, "output_tokens", 0),
    }


def parse_json_response(raw):
    """Parse a JSON object from Claude's response."""

    text = raw.strip()

    # First try the complete response.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Remove common Markdown code fences.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        fenced = "\n".join(lines).strip()
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            pass

    # Find the first JSON object in surrounding prose.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            return obj
        except json.JSONDecodeError:
            continue

    raise RuntimeError(
        "Claude returned invalid JSON: " + raw
    )

def plan_lookups(question, recent_messages=None):
    """Use Claude to decide which capabilities are required."""
    schemas = capability_schemas()
    instructions = capability_instructions()

    capabilities = {
        name: {
            "request": schemas.get(name),
            "instructions": instructions.get(name),
        }
        for name in sorted(CAPABILITIES)
    }

    prompt = (
        "Capabilities:\n"
        + json.dumps(
            capabilities,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n\nRecent conversation:\n"
        + format_memory(recent_messages, limit=2)
        + "\n\nQuestion:\n"
        + question
    )

    raw, usage = call_claude(prompt, system=PLANNER_RULES, max_tokens=220)
    plan = parse_json_response(raw)
    lookups = validate_plan(plan, CAPABILITIES)

    # Deterministic weather guardrail.
    if "weekend" in question.lower():
        for item in lookups:
            if item["capability"] == "weather":
                requested = item["request"].get("forecast_days", 0)
                try:
                    requested = int(requested)
                except (TypeError, ValueError):
                    requested = 0
                item["request"]["forecast_days"] = max(requested, 7)

    return lookups, usage


def capability_answer_rules(lookups):
    """Collect ANSWER_RULES from the capability modules used for this query.

    Capability-specific rules replace COMPOSED_ANSWER_RULES when present.
    GENERAL_ANSWER_RULES are always retained as the global baseline.
    """
    rules = []
    seen = set()

    for item in lookups:
        capability_name = item.get("capability")
        definition = CAPABILITIES.get(capability_name)
        if not definition:
            continue

        # The registry stores each plugin's run_lookup function. Its module
        # path identifies the actual plugin without changing the registry API.
        runner = definition.get("run") if isinstance(definition, dict) else None
        module_name = getattr(runner, "__module__", None)
        if not module_name:
            continue

        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        answer_rules = getattr(module, "ANSWER_RULES", None)
        if isinstance(answer_rules, str) and answer_rules.strip() and answer_rules not in seen:
            rules.append(answer_rules.strip())
            seen.add(answer_rules)

    return "\\n\\n".join(rules)


def answer_question(question, results, recent_messages=None, lookups=None):
    """Compose an answer using global and capability-specific instructions."""
    context = results_as_json(results)
    specific_rules = capability_answer_rules(lookups or [])

    # Keep composed.py as a fallback while capabilities are migrated.
    # Capability ANSWER_RULES override composed.py, never general.py.
    task_rules = specific_rules or COMPOSED_ANSWER_RULES
    system_rules = GENERAL_ANSWER_RULES + "\\n\\n" + task_rules

    prompt = (
        system_rules
        + "\\n\\nRecent conversation:\\n"
        + format_memory(recent_messages, limit=2)
        + "\\n\\nQuestion:\\n"
        + question
        + "\\n\\nRetrieved information:\\n"
        + context
    )

    return call_claude(prompt, system=system_rules, max_tokens=220)


def classify_intent(question, recent_messages=None):
    """Classify the conversational intent of a general question."""

    prompt = (
        "Recent conversation:\n"
        + format_memory(
            recent_messages,
            limit=2
        )
        + "\n\nQuestion:\n"
        + question
    )

    raw, usage = call_claude(
        prompt,
        system=INTENT_RULES,
        max_tokens=20,
    )

    intent = raw.strip().lower()

    if intent not in {"serious", "playful", "ambiguous"}:
        intent = "ambiguous"

    return intent, usage


def answer_general(
    question,
    recent_messages=None,
    intent="ambiguous",
):
    """Claude answer when no specialized capability is required."""

    prompt = (
        "Recent conversation:\n"
        + format_memory(
            recent_messages,
            limit=2
        )
        + "\n\nQuestion:\n"
        + question
        + "\n\nDetected conversational intent:\n"
        + intent
    )

    return call_claude(
        prompt,
        system=GENERAL_ANSWER_RULES,
        max_tokens=220,
    )

def answer_direct_memory_question(question, recent_messages):
    """Claude-specific natural-language response for memory questions."""
    previous = get_previous_user_question(recent_messages)

    if not previous:
        prompt = (
            "Answer concisely. There is no previous user question. "
            "Plain terminal text only.\n"
            "Question: "
            + question
        )
    else:
        prompt = (
            "Answer the current question concisely using the previous "
            "user question as the factual source. "
            "Do not mention memory or implementation. "
            "Plain terminal text only.\n\n"
            "Current question:\n"
            + question
            + "\n\nPrevious user question:\n"
            + previous
        )

    return call_claude(prompt, max_tokens=80)


def add_usage(total, usage):
    total["input"] += usage.get("input", 0)
    total["output"] += usage.get("output", 0)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Claude assistant with automatically discovered capabilities."
        )
    )
    parser.add_argument("question", nargs="+")
    args = parser.parse_args()

    question = " ".join(args.question)

    total = {
        "input": 0,
        "output": 0,
    }

    # Retrieve previous conversation before adding the current question.
    recent_messages = get_recent_messages(limit=10)

    # Simple memory questions bypass capability routing.
    if is_direct_memory_question(question):
        answer, usage = answer_direct_memory_question(
            question,
            recent_messages,
        )

        add_usage(total, usage)

        add_message("user", question)
        add_message("assistant", answer)

        print(answer)
        print()
        print(
            f"Claude tokens: {total['input']} input, "
            f"{total['output']} output, "
            f"{total['input'] + total['output']} total"
        )
        return

    add_message("user", question)

    # Claude #1: decide what information is needed.
    lookups, usage = plan_lookups(
        question,
        recent_messages,
    )

    add_usage(total, usage)

    if not lookups:
        intent, intent_usage = classify_intent(
            question,
            recent_messages,
        )
        print(f"DEBUG intent={intent}", file=sys.stderr)
        add_usage(total, intent_usage)

        answer, usage = answer_general(
            question,
            recent_messages,
            intent,
        )
        add_usage(total, usage)

    else:
        # Model-agnostic execution happens in core/.
        results = execute_lookups(lookups)

        # Claude #2: compose the final answer.
        answer, usage = answer_question(
            question,
            results,
            recent_messages,
            lookups,
        )
        add_usage(total, usage)

    add_message("assistant", answer)

    print(answer)
    print()
    print(
        f"Claude tokens: {total['input']} input, "
        f"{total['output']} output, "
        f"{total['input'] + total['output']} total"
    )


if __name__ == "__main__":
    main()
