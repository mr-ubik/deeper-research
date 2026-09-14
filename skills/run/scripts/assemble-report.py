#!/usr/bin/env python3
"""Assemble the canonical and plain reports for a completed run."""

import json
import re
import sys
from pathlib import Path


def remove_methodology(text):
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^## Methodology\s*$", line.rstrip("\r\n"))), None)
    if start is None:
        return text, False
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"^## ", lines[i])), len(lines))
    return "".join(lines[:start] + lines[end:]), True


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 assemble-report.py <run_dir>")
        return 2
    run_dir = Path(sys.argv[1])
    try:
        data = json.loads((run_dir / "results.json").read_text())
    except (OSError, json.JSONDecodeError):
        data = None
    # The workflow records which file it considers canonical. Honor it: a
    # stale final_report.md from an earlier attempt must not outrank the
    # draft the workflow actually produced this time. Without the key (older
    # runs) fall back to "final if present, else draft".
    candidates = (("final_report.md", "final"), ("unreviewed_report.md", "draft"))
    recorded = data.get("report_source") if data is not None else None
    if recorded in ("final", "draft"):
        candidates = tuple(c for c in candidates if c[1] == recorded)
    elif recorded == "none":
        candidates = ()
    chosen = None
    for name, label in candidates:
        path = run_dir / name
        if path.exists():
            text = path.read_text()
            if len(text.strip().encode()) >= 200:
                chosen = (text, label)
                break
    if chosen is None:
        print("NO-REPORT")
        return 1
    if data is None:
        print("ERROR: results.json missing or unreadable")
        return 2
    source, report_source = chosen
    appendix = data.get("appendix", "")
    report = source.rstrip() + ("\n\n" + appendix if appendix else "") + "\n"
    plain, stripped = remove_methodology(source)
    plain = plain.rstrip() + "\n"
    (run_dir / "report.md").write_text(report)
    (run_dir / "report_plain.md").write_text(plain)
    print(json.dumps({"report_source": report_source,
                      "report_bytes": len(report.encode()),
                      "plain_bytes": len(plain.encode()),
                      "methodology_stripped": stripped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
