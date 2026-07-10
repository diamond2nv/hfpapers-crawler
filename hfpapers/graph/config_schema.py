#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config schema and defaults for stepping citation expansion.

Defines the expected structure of the ``stepping:`` section in
``config.yaml`` and provides validation and default values.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("hfpapers.graph.config_schema")

STEPPING_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "api_delay": 3.5,
    "resume": True,           # Skip completed layers on re-run
    "sources": {
        "s2_api": True,       # Semantic Scholar API (online)
        "pdf_refs": False,    # PDF→MD reference extraction (offline)
        "tex_bib": False,     # TeX .bib parsing (offline)
        "person_cards": True, # wiki/people DOI+ORCID seeds
    },
    "layers": [],  # List of layer dicts (see schema below)
}

STEPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {"type": "boolean"},
        "api_delay": {"type": "number", "minimum": 1.0, "maximum": 30.0},
        "resume": {"type": "boolean"},
        "sources": {
            "type": "object",
            "properties": {
                "s2_api": {"type": "boolean"},
                "pdf_refs": {"type": "boolean"},
                "tex_bib": {"type": "boolean"},
                "person_cards": {"type": "boolean"},
            },
        },
        "layers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "seeds": {"type": "array", "items": {"type": "string"}},
                    "orcid_seeds": {"type": "array", "items": {"type": "string"}},
                    "filter_keywords": {"type": "array", "items": {"type": "string"}},
                    "filter_authors": {"type": "array", "items": {"type": "string"}},
                    "direction": {"type": "string", "enum": ["references", "citations", "both"]},
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["name"],
            },
        },
    },
}


def validate_stepping_config(cfg: dict) -> list[str]:
    """Validate a stepping config dict against the schema.

    Returns a list of warning/error strings (empty if all valid).
    """
    errors: list[str] = []

    if not isinstance(cfg, dict):
        return ["stepping config must be a dict"]

    layers = cfg.get("layers", [])
    if not layers:
        errors.append("stepping.layers is empty — no citation expansion will run")

    seen_names: set[str] = set()
    for i, layer in enumerate(layers):
        name = layer.get("name", "")
        if not name:
            errors.append(f"Layer {i}: missing 'name'")
        elif name in seen_names:
            errors.append(f"Layer {i}: duplicate name '{name}'")
        else:
            seen_names.add(name)

        if not layer.get("seeds") and not layer.get("orcid_seeds"):
            errors.append(f"Layer '{name}': no 'seeds' or 'orcid_seeds' defined")

        direction = layer.get("direction", "both")
        if direction not in ("references", "citations", "both"):
            errors.append(f"Layer '{name}': invalid direction '{direction}'")

        md = layer.get("max_depth", 1)
        if not isinstance(md, int) or md < 1 or md > 5:
            errors.append(f"Layer '{name}': max_depth must be 1-5")

    if errors:
        for e in errors:
            logger.warning("Config validation: %s", e)

    return errors
