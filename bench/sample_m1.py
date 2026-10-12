#!/usr/bin/env python3
"""Sample cited sentences from a blinded report, reproducibly."""

import argparse
import json
import random
import re
import sys
from pathlib import Path

from blind import DEFINITION, INLINE


SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def parse_report(text):
    """Return the body and footnote definitions, including indented continuations."""
    body, definitions = [], {}
    current = None
    for line in text.splitlines():
        match = DEFINITION.match(line)
        if match:
            current = match.group(1)
            definitions[current] = match.group(2).strip()
        elif current is not None and line.startswith("    "):
            definitions[current] += " " + line.strip()
        else:
            current = None
            body.append(line)
    return "\n".join(body), definitions


def report_sentences(body):
    """Split prose within paragraphs, excluding headings and table rows."""
    paragraphs, lines = [], []
    for line in body.splitlines():
        if not line.strip() or line.startswith(("#", "|")):
            if lines:
                paragraphs.append(" ".join(lines))
                lines = []
            continue
        lines.append(re.sub(r"^\s*(?:[-*] |\d+\. )", "", line).strip())
    if lines:
        paragraphs.append(" ".join(lines))
    return [sentence.strip() for paragraph in paragraphs
            for sentence in SENTENCE_BREAK.split(paragraph) if sentence.strip()]


def clean_sentence(sentence):
    return " ".join(INLINE.sub("", sentence).split())


def sample_items(text, n=15, seed=1):
    if n < 0:
        raise ValueError("n must be nonnegative")
    body, definitions = parse_report(text)
    sentences = report_sentences(body)
    candidates = [i for i, sentence in enumerate(sentences) if INLINE.search(sentence)]
    selected = sorted(random.Random(seed).sample(candidates, min(n, len(candidates))))
    items = []
    for number, position in enumerate(selected, 1):
        sentence = sentences[position]
        labels = list(dict.fromkeys(INLINE.findall(sentence)))
        urls = []
        for label in labels:
            match = re.search(r"https?://\S+", definitions.get(label, ""))
            url = match.group().rstrip("),.") if match else ""
            if not url:
                print(f"WARNING: footnote {label!r} has no definition or URL", file=sys.stderr)
            urls.append(url)
        neighbors = sentences[max(0, position - 1):position] + sentences[position + 1:position + 2]
        items.append({"item_id": f"s.{number:03d}", "sentence": clean_sentence(sentence),
                      "context": clean_sentence(" ".join(neighbors)), "labels": labels, "urls": urls})
    return items


def sample_report(report, out, n=15, seed=1):
    items = sample_items(Path(report).read_text(encoding="utf-8"), n, seed)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.n < 0:
        parser.error("--n must be nonnegative")
    sample_report(args.report, args.out, args.n, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
