#!/usr/bin/env python3
"""Run the benchmark judge harness, resuming completed batches without retries."""

import argparse
import json
import shlex
import sys
from pathlib import Path

import judge
from collect import collect
from fetch_sources import fetch_sources
from make_batches import make_batches
from sample_m1 import sample_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--checklist", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--model", default="openai-codex/gpt-6-astra")
    parser.add_argument("--thinking", default="high")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.n < 0:
        parser.error("--n must be nonnegative")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    items = sample_report(args.report, out / "items.json", args.n, args.seed)
    fetch_sources(items, out / "sources", args.run_dir)
    manifest = make_batches(items, out / "sources", Path(args.report).read_text(encoding="utf-8"),
                            json.loads(Path(args.checklist).read_text(encoding="utf-8")),
                            args.run_id, args.question_id, out / "batches", seed=args.seed)
    result = 0
    if not args.dry_run:
        outputs = out / "judge-outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        failures_path = outputs / "failures.json"
        failures = json.loads(failures_path.read_text(encoding="utf-8")) if failures_path.exists() else {}
        failures_path.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        for batch in manifest["batches"]:
            filename = batch["file"]
            stem = Path(filename).stem
            text_path = outputs / (stem + ".txt")
            if text_path.exists():
                continue
            if filename in failures:
                print(f"WARNING: skipping previously failed batch {filename}", file=sys.stderr)
                continue
            try:
                code = judge.main(["--prompt", str(out / "batches" / filename),
                                   "--out-text", str(text_path),
                                   "--out-json", str(outputs / (stem + ".events.jsonl")),
                                   "--model", args.model, "--thinking", args.thinking])
                failure = {"returncode": code, "reason": f"judge returned {code}"} if code else None
            except Exception as error:
                failure = {"returncode": None, "reason": f"{type(error).__name__}: {error}"}
            if failure:
                failures[filename] = failure
                failures_path.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
                print(f"WARNING: {filename}: {failure['reason']}", file=sys.stderr)
        result = collect(manifest, outputs, out / "verdicts.csv")
    else:
        print("Dry run: sources and prompts prepared; judge calls and collection skipped.")
    print(shlex.join(["python3", str(Path(__file__).resolve().parent / "score.py"),
                      "--checklist", args.checklist, "--verdicts", str(out / "verdicts.csv"),
                      "--plants", str(out / "batches" / "plants.csv"), "--run-meta", "<RUN_META.json>"]))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
