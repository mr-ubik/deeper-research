#!/usr/bin/env python3
"""Run a single pi judgment and save its event stream and final text."""

import argparse
import json
import subprocess
import sys


def extract_text(stream):
    """Return the last text event, or all text deltas when no text event exists."""
    texts, deltas = [], []
    for line in stream.splitlines():
        try: event = json.loads(line)
        except json.JSONDecodeError: continue
        if event.get("type") == "text" and isinstance(event.get("text"), str):
            texts.append(event["text"])
        elif event.get("type") == "text_delta" and isinstance(event.get("text"), str):
            deltas.append(event["text"])
    return texts[-1] if texts else "".join(deltas)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out-text", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--model", default="openai-codex/gpt-5.6-sol")
    parser.add_argument("--thinking", default="high")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args(argv)
    command = ["pi", "-p", "--mode", "json", "--no-tools", "--no-session",
               "--no-context-files", "--no-skills", "--no-extensions",
               "--no-prompt-templates", "--thinking", args.thinking,
               "--model", args.model, "@" + args.prompt]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr); return 1
    with open(args.out_json, "w", encoding="utf-8") as handle: handle.write(completed.stdout)
    text = extract_text(completed.stdout)
    if completed.returncode or not text:
        if completed.stderr: sys.stderr.write(completed.stderr)
        if not text: print("ERROR: pi produced no assistant text", file=sys.stderr)
        return 1
    with open(args.out_text, "w", encoding="utf-8") as handle: handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
