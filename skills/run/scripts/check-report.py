#!/usr/bin/env python3
"""Validate report footnotes against the persisted source ledger."""

import json
import re
import sys
from pathlib import Path


APPENDIX_RE = re.compile(r"^## Appendix A: Verification ledger\s*$", re.M)
DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:\s*(.*)$")
INLINE_RE = re.compile(r"\[\^([^\]\s]+)\]")


def ordered_unique(items):
    return list(dict.fromkeys(items))


# Characters that can continue a URL. A ledger URL counts only when the text
# carries it verbatim AND complete: `.../abs/2409.17424` must not match
# `.../abs/2409.17424v2`, and `example.org/a` must not match `example.org/abc`.
_URL_CONTINUATION = re.compile(r"[\w/.\-#?=&%~+]")


def url_in(url, text):
    start = 0
    while True:
        pos = text.find(url, start)
        if pos < 0:
            return False
        after = text[pos + len(url):pos + len(url) + 1]
        if not after or not _URL_CONTINUATION.match(after):
            return True
        start = pos + 1


def inspect_report(report, data):
    ledger = data.get("ledger")
    if ledger is not None:
        sources = ledger.get("sources", [])
    else:
        sources = [dict(key=f"S{i}", source=r.get("source", ""),
                        title=r.get("title", ""), fetch_ok=r.get("fetch_ok"))
                   for i, r in enumerate(data.get("results", []))]

    appendix = APPENDIX_RE.search(report)
    checked = report[:appendix.start()] if appendix else report
    body_lines = []
    definitions = {}
    definition_order = []
    duplicate_labels = []
    current = None
    for line in checked.splitlines():
        match = DEF_RE.match(line)
        if match:
            label, text = match.groups()
            if label in definitions:
                duplicate_labels.append(label)
            else:
                definitions[label] = text
                definition_order.append(label)
            current = label
        elif current is not None and re.match(r"^ {4,}", line):
            definitions[current] += "\n" + line
        else:
            current = None
            body_lines.append(line)
    body = "\n".join(body_lines)
    inline_labels = ordered_unique(INLINE_RE.findall(body))
    refs_without_definition = [x for x in inline_labels if x not in definitions]
    definitions_never_referenced = [x for x in definition_order
                                    if x not in inline_labels]

    urls = [s.get("source", "") for s in sources if s.get("source", "")]
    matches = {}
    for label in definition_order:
        found = ordered_unique(url for url in urls if url_in(url, definitions[label]))
        matches[label] = [url for url in found
                          if not any(url != other and other.startswith(url)
                                     for other in found)]
    definitions_without_ledger_url = [x for x in definition_order
                                      if not matches[x]]
    definitions_with_multiple_urls = [x for x in definition_order
                                      if len(matches[x]) > 1]
    duplicate_source_definitions = ordered_unique(
        url for url in urls
        if sum(url in matches[label] for label in definition_order) > 1)

    cited_urls = {url for label in inline_labels for url in matches.get(label, [])}
    sources_cited = [s.get("key") for s in sources
                     if s.get("source") in cited_urls]
    failed = [s.get("key") for s in sources
              if s.get("key") in sources_cited and s.get("fetch_ok") is False]
    methodology = data.get("methodology")
    methodology_ok = None if methodology is None else methodology in report
    problems = [refs_without_definition, definitions_never_referenced,
                duplicate_labels, definitions_without_ledger_url,
                definitions_with_multiple_urls, duplicate_source_definitions]
    ok = all(not problem for problem in problems) and bool(inline_labels) \
        and methodology_ok is not False
    return {
        "inline_labels": inline_labels,
        "refs_without_definition": refs_without_definition,
        "definitions_never_referenced": definitions_never_referenced,
        "duplicate_labels": duplicate_labels,
        "definitions_without_ledger_url": definitions_without_ledger_url,
        "definitions_with_multiple_urls": definitions_with_multiple_urls,
        "duplicate_source_definitions": duplicate_source_definitions,
        "sources_cited": sources_cited,
        "fetch_failed_cited": failed,
        "methodology_ok": methodology_ok,
        "ok": ok,
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 check-report.py <run_dir>")
        return 2
    run_dir = Path(sys.argv[1])
    try:
        report = (run_dir / "report.md").read_text()
        data = json.loads((run_dir / "results.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    result = inspect_report(report, data)
    print(json.dumps(result, indent=2))
    for kind in ("refs_without_definition", "definitions_never_referenced",
                 "duplicate_labels", "definitions_without_ledger_url",
                 "definitions_with_multiple_urls", "duplicate_source_definitions"):
        for detail in result[kind]:
            print(f"PROBLEM {kind}: {detail}")
    if not result["inline_labels"]:
        print("PROBLEM inline_labels: no inline references")
    if result["methodology_ok"] is False:
        print("PROBLEM methodology_ok: methodology is not verbatim")
    if result["ok"]:
        print(f"CLEAN: {len(result['inline_labels'])} footnote labels cite "
              f"{len(result['sources_cited'])} ledger sources.")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
