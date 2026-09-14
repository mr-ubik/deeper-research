#!/usr/bin/env python3
"""Perform the small, dependency-free validation used by benchmark tools."""

import json
import sys


TOP_KEYS = {
    "question_id", "question", "register", "source", "claims",
    "conclusions", "references", "authoritative_sources",
}
ENUMS = {
    "register": {"decision-memo", "survey", "article"},
    "source.type": {"survey", "rubric"},
    "claims.kind": {"must-have", "trap", "hedge-required"},
    "references.class": {"load-bearing", "background"},
    "references.access": {"open", "closed"},
}


def validate(data):
    """Return human-readable errors for required keys and enum values."""
    errors = []
    missing = TOP_KEYS - data.keys() if isinstance(data, dict) else TOP_KEYS
    if missing:
        errors.append("missing required keys: " + ", ".join(sorted(missing)))
        return errors
    if data["register"] not in ENUMS["register"]:
        errors.append("invalid register: " + repr(data["register"]))
    required_source = {"type", "title", "url", "content_cutoff"}
    if not isinstance(data["source"], dict) or not required_source <= data["source"].keys():
        errors.append("source requires type, title, url, and content_cutoff")
    elif data["source"]["type"] not in ENUMS["source.type"]:
        errors.append("invalid source.type: " + repr(data["source"]["type"]))
    specs = [
        ("claims", {"id", "text", "kind", "acceptance", "survey_ref"}),
        ("conclusions", {"id", "text"}),
        ("references", {"id", "title", "url", "class", "access"}),
    ]
    for collection, required in specs:
        if not isinstance(data[collection], list):
            errors.append(f"{collection} must be a list")
            continue
        for index, item in enumerate(data[collection]):
            if not isinstance(item, dict) or not required <= item.keys():
                errors.append(f"{collection}[{index}] is missing required keys")
                continue
            for field in ("kind", "class", "access"):
                key = f"{collection}.{field}"
                if field in item and key in ENUMS and item[field] not in ENUMS[key]:
                    errors.append(f"invalid {key}: {item[field]!r}")
    if not isinstance(data["authoritative_sources"], list):
        errors.append("authoritative_sources must be a list")
    return errors


def main(argv=None):
    paths = (argv if argv is not None else sys.argv[1:])
    if len(paths) != 1:
        print("usage: validate_checklist.py <checklist.json>", file=sys.stderr)
        return 2
    try:
        with open(paths[0], encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
