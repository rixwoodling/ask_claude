#!/usr/bin/env python3
"""Automatically discover ask_about_* capability plugins."""

import importlib
from pathlib import Path


CAPABILITY_DIR = Path(__file__).resolve().parent / "capabilities"


def discover_capabilities():
    """Discover capability plugins from the capabilities directory."""
    capabilities = {}

    if not CAPABILITY_DIR.is_dir():
        return capabilities

    for path in sorted(CAPABILITY_DIR.glob("ask_about_*.py")):
        module_name = f"{CAPABILITY_DIR.name}.{path.stem}"
        module = importlib.import_module(module_name)

        capability = getattr(module, "CAPABILITY", None)
        description = getattr(module, "DESCRIPTION", None)
        schema = getattr(module, "REQUEST_SCHEMA", None)

        prompt_instructions = getattr(module, "PLANNER_INSTRUCTIONS", None)

        if prompt_instructions is not None and not isinstance(prompt_instructions, str):
            raise RuntimeError(
                f"{path.name} has an invalid PLANNER_INSTRUCTIONS"
            )
        runner = getattr(module, "run_lookup", None)

        if not capability:
            raise RuntimeError(f"{path.name} is missing CAPABILITY")
        if not description:
            raise RuntimeError(f"{path.name} is missing DESCRIPTION")
        if schema is not None and not isinstance(schema, dict):
            raise RuntimeError(
                f"{path.name} has an invalid REQUEST_SCHEMA"
            )
        if not callable(runner):
            raise RuntimeError(f"{path.name} is missing run_lookup()")

        if capability in capabilities:
            raise RuntimeError(f"Duplicate capability: {capability}")

        capabilities[capability] = {
            "run": runner,
            "description": description,
            "schema": schema,
            "instructions": prompt_instructions,
        }

    return capabilities


CAPABILITIES = discover_capabilities()


def capability_descriptions():
    return {
        name: definition["description"]
        for name, definition in CAPABILITIES.items()
    }


def capability_schemas():
    return {
        name: definition["schema"]
        for name, definition in CAPABILITIES.items()
    }


def capability_instructions():
    """Return planner instructions exported by discovered capabilities."""
    return {
        name: definition["instructions"]
        for name, definition in CAPABILITIES.items()
        if definition.get("instructions")
    }
