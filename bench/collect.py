#!/usr/bin/env python3
"""Collect tolerant judge CSV output against an expected batch manifest."""

import argparse
import csv
import json
import sys
from pathlib import Path

from score import HEADER


def collect(manifest, outputs, out):
    outputs = Path(outputs)
    kept, summaries = [], []
    failed = False
    for batch in manifest["batches"]:
        expected = set(batch["item_ids"])
        got = set()
        path = outputs / Path(batch["file"]).with_suffix(".txt").name
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            print(f"WARNING: {batch['file']}: output missing: {path}", file=sys.stderr)
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("```", "~~~")):
                continue
            try:
                row = next(csv.reader([line], skipinitialspace=True, strict=True))
            except (csv.Error, StopIteration):
                continue
            if len(row) != len(HEADER):
                continue
            row = [field.strip() for field in row]
            if row == HEADER:
                continue
            if row[:2] != [manifest["run_id"], manifest["question_id"]]:
                continue
            if row[3] not in expected:
                print(f"WARNING: {batch['file']}: unknown item_id {row[3]!r}", file=sys.stderr)
                continue
            kept.append(row)
            got.add(row[3])
        missing = expected - got
        if missing:
            print(f"WARNING: {batch['file']}: missing expected items: {', '.join(sorted(missing))}",
                  file=sys.stderr)
        if not got or len(missing) > len(expected) / 2:
            failed = True
        summaries.append(f"{batch['file']}: expected {len(expected)}, got {len(got)}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(kept)
    print(f"Rows kept: {len(kept)}")
    for summary in summaries:
        print(summary)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    return collect(manifest, args.outputs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
