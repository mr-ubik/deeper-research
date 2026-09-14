#!/usr/bin/env python3
"""Summarize token use from workflow and judge event streams."""

import argparse
import glob
import json
import os
import sys


FIELDS = ("input", "cache_creation", "cache_read", "output", "turns")


def empty_usage():
    return {field: 0 for field in FIELDS}


def json_lines(path):
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try: yield json.loads(line)
                except (json.JSONDecodeError, TypeError): continue
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error


def add(target, usage):
    target["input"] += usage.get("input_tokens", 0)
    target["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
    target["cache_read"] += usage.get("cache_read_input_tokens", 0)
    target["output"] += usage.get("output_tokens", 0)
    target["turns"] += 1


def summarize(directory, judge_paths):
    phases = {}
    for event in json_lines(os.path.join(directory, "journal.jsonl")):
        if event.get("type") == "started" and event.get("agentId"):
            phases[str(event["agentId"])] = event.get("phase") or event.get("label") or "unknown"
    agent_files = sorted(glob.glob(os.path.join(directory, "agent-*.jsonl")))
    by_model, by_phase, totals = {}, {}, empty_usage()
    for path in agent_files:
        agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        phase = phases.get(agent_id, "unknown")
        for event in json_lines(path):
            message = event.get("message", {}) if event.get("type") == "assistant" else {}
            usage = message.get("usage")
            if not isinstance(usage, dict): continue
            model = message.get("model", "unknown")
            add(by_model.setdefault(model, empty_usage()), usage)
            add(by_phase.setdefault(phase, empty_usage()), usage)
            add(totals, usage)
    equivalent = totals["cache_read"] * 0.1 + totals["cache_creation"] * 1.25 + totals["input"] + totals["output"] * 5
    judge = None
    if judge_paths:
        judge = {"input": 0, "output": 0, "total": 0, "calls": 0}
        for path in judge_paths:
            for event in json_lines(path):
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    usage = event.get("message", {}).get("usage") if isinstance(event.get("message"), dict) else None
                if isinstance(usage, dict) and "input" in usage and "output" in usage:
                    judge["input"] += usage["input"]
                    judge["output"] += usage["output"]
                    judge["total"] += usage.get("totalTokens", usage["input"] + usage["output"])
                    judge["calls"] += 1
    return {"agents": len(agent_files), "by_model": by_model, "by_phase": by_phase,
            "totals": totals, "sonnet_input_equivalent": float(equivalent), "judge": judge}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow_transcript_dir")
    parser.add_argument("--judge-usage", action="append", default=[])
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try: result = summarize(args.workflow_transcript_dir, args.judge_usage)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr); return 2
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle: handle.write(output)
    else: sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
