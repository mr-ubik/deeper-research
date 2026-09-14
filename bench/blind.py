#!/usr/bin/env python3
"""Remove pipeline identity and normalize footnotes for blind review."""

import argparse
import json
import re


INLINE = re.compile(r"\[\^([^\]]+)\]")
DEFINITION = re.compile(r"^\[\^([^\]]+)\]:(.*)$")


def blind_text(text):
    lines = text.splitlines(keepends=True)
    kept, removing_methodology = [], False
    for line in lines:
        bare = line.rstrip("\r\n")
        if bare == "## Appendix A: Verification ledger":
            break
        if bare == "## Methodology":
            removing_methodology = True
            continue
        if removing_methodology:
            if line.startswith("## "):
                removing_methodology = False
            else:
                continue
        if "deeper-research" in line.lower():
            continue
        kept.append(line)

    definitions, content = {}, []
    for line in kept:
        match = DEFINITION.match(line.rstrip("\r\n"))
        if match:
            definitions[match.group(1)] = (match.group(2), line[len(line.rstrip("\r\n")):])
        else:
            content.append(line)
    mapping = {}
    for line in content:
        for match in INLINE.finditer(line):
            mapping.setdefault(match.group(1), str(len(mapping) + 1))
    rewritten = [INLINE.sub(lambda match: f"[^{mapping[match.group(1)]}]", line) for line in content]
    for old, new in mapping.items():
        if old in definitions:
            body, ending = definitions[old]
            rewritten.append(f"[^{new}]:{body}{ending}")
    return "".join(rewritten), mapping


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--out", required=True)
    parser.add_argument("--map", required=True)
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as handle: text = handle.read()
    blinded, mapping = blind_text(text)
    with open(args.out, "w", encoding="utf-8") as handle: handle.write(blinded)
    with open(args.map, "w", encoding="utf-8") as handle: json.dump(mapping, handle, indent=2); handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
