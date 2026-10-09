"""Model-agnostic lookup-plan validation and helpers.

This module does not know which LLM produced the plan.
"""


def validate_plan(plan, capabilities):
    """Return a clean lookup list from an LLM-produced plan."""
    if not isinstance(plan, dict):
        raise ValueError("Lookup plan must be a dictionary.")

    lookups = plan.get("lookups", [])
    if not isinstance(lookups, list):
        raise ValueError("Lookup plan must contain a list named 'lookups'.")

    valid = []

    for item in lookups:
        if not isinstance(item, dict):
            continue

        name = item.get("capability")
        request = item.get("request")

        if name in capabilities and isinstance(request, dict):
            valid.append({
                "capability": name,
                "request": request,
            })

    return valid
