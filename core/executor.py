"""Model-agnostic capability execution and dependency resolution."""

import re

from capability_registry import CAPABILITIES

MISSING = object()


def resolve_references(value, results):
    """Resolve $capability.field and $capability.list[0] references."""
    if isinstance(value, str) and value.startswith("$"):
        path = value[1:]
        tokens = re.findall(r"([^\.\[\]]+)|\[(\d+)\]", path)

        if not tokens:
            return MISSING

        capability = tokens[0][0]
        if capability not in results:
            return MISSING

        current = results[capability]

        for field, index in tokens[1:]:
            if field:
                if not isinstance(current, dict) or field not in current:
                    return MISSING
                current = current[field]
            else:
                if not isinstance(current, list):
                    return MISSING
                try:
                    current = current[int(index)]
                except (ValueError, IndexError):
                    return MISSING

        return current

    if isinstance(value, dict):
        resolved = {}
        for key, item in value.items():
            item = resolve_references(item, results)
            if item is MISSING:
                return MISSING
            resolved[key] = item
        return resolved

    if isinstance(value, list):
        resolved = []
        for item in value:
            item = resolve_references(item, results)
            if item is MISSING:
                return MISSING
            resolved.append(item)
        return resolved

    return value


def execute_lookups(lookups):
    """Execute capabilities while resolving dependencies between them."""
    results = {}
    pending = list(lookups)

    while pending:
        progress = False
        remaining = []

        for lookup in pending:
            name = lookup["capability"]

            if name not in CAPABILITIES:
                raise RuntimeError(f"Unknown capability requested: {name}")

            request = resolve_references(lookup["request"], results)

            if request is MISSING:
                remaining.append(lookup)
                continue

            results[name] = CAPABILITIES[name]["run"](request)
            progress = True

        if not progress:
            unresolved = ", ".join(
                item["capability"] for item in remaining
            )
            raise RuntimeError(
                f"Could not resolve capability requests: {unresolved}"
            )

        pending = remaining

    return results
