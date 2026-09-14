#!/usr/bin/env python3
"""Render the builtin /deep-research workflow's JSON result as Markdown.

The builtin returns a structured object (summary, findings with source URL
lists, caveats, open questions). Claude Code's session normally turns that
into prose, which makes the rendering a variable in any comparison. This
renderer is deterministic, so the builtin arm's report is the workflow's
output and nothing else. Every finding's sources become GitHub footnotes,
one footnote per unique URL, numbered in order of first citation; the
definitions carry the URL only, since the builtin records no bibliography
metadata. Refuted and unverified claims are not part of the report the
builtin asserts, so they are not rendered (they stay in the JSON).

Usage: python3 render_builtin.py <result.json> --out <report.md>
"""

import argparse
import json
import sys


def _clean(text):
    return " ".join(str(text or "").split())


def render(result):
    footnotes = {}

    def ref(url):
        url = _clean(url)
        if not url:
            return ""
        if url not in footnotes:
            footnotes[url] = str(len(footnotes) + 1)
        return f"[^{footnotes[url]}]"

    lines = [f"# {_clean(result.get('question', 'Research report'))}", ""]
    summary = _clean(result.get("summary"))
    if summary:
        lines += ["## Summary", "", summary, ""]

    findings = result.get("findings") or []
    if findings:
        lines += ["## Findings", ""]
        for i, f in enumerate(findings, 1):
            refs = "".join(ref(u) for u in (f.get("sources") or []))
            confidence = _clean(f.get("confidence"))
            lines.append(f"### {i}. {_clean(f.get('claim'))}{refs}")
            lines.append("")
            if confidence:
                lines.append(f"Confidence: {confidence}.")
                lines.append("")
            evidence = _clean(f.get("evidence"))
            if evidence:
                lines.append(evidence)
                lines.append("")

    caveats = _clean(result.get("caveats"))
    if caveats:
        lines += ["## Caveats", "", caveats, ""]

    open_questions = [_clean(q) for q in (result.get("openQuestions") or []) if _clean(q)]
    if open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- {q}" for q in open_questions]
        lines.append("")

    if footnotes:
        lines += [f"[^{n}]: {url}" for url, n in footnotes.items()]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("result")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.result, encoding="utf-8") as handle:
            result = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    text = render(result)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(json.dumps({"findings": len(result.get("findings") or []),
                      "footnotes": text.count("]: http"), "bytes": len(text.encode())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
