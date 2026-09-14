#!/usr/bin/env python3
"""Run a single pi judgment and save its event stream and final text."""

import argparse
import json
import subprocess
import sys


def extract_text(stream):
    """Return the judge's final answer text from a `pi --mode json` event stream.

    pi emits the assistant's answer in three places, checked in this order:
    1. the last `message_end` whose message.role is "assistant": the text
       content blocks of that message (thinking blocks are skipped);
    2. `message_update` events carrying assistantMessageEvent.type
       "text_delta" with a `delta` field, concatenated;
    3. legacy top-level `text` / `text_delta` events with a `text` field.
    """
    final, deltas, legacy_texts, legacy_deltas = None, [], [], []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                blocks = [b.get("text", "") for b in (message.get("content") or [])
                          if isinstance(b, dict) and b.get("type") == "text"]
                if any(blocks):
                    final = "".join(blocks)
        elif kind == "message_update":
            sub = event.get("assistantMessageEvent") or {}
            if sub.get("type") == "text_delta" and isinstance(sub.get("delta"), str):
                deltas.append(sub["delta"])
        elif kind == "text" and isinstance(event.get("text"), str):
            legacy_texts.append(event["text"])
        elif kind == "text_delta" and isinstance(event.get("text"), str):
            legacy_deltas.append(event["text"])
    if final:
        return final
    if deltas:
        return "".join(deltas)
    return legacy_texts[-1] if legacy_texts else "".join(legacy_deltas)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out-text", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--model", default="openai-codex/gpt-5.6-sol")
    parser.add_argument("--thinking", default="high")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--from-events", help="recover the text from a saved event stream instead of calling pi")
    args = parser.parse_args(argv)
    if args.from_events:
        with open(args.from_events, encoding="utf-8") as handle:
            text = extract_text(handle.read())
        if not text:
            print("ERROR: no assistant text in the event stream", file=sys.stderr)
            return 1
        with open(args.out_text, "w", encoding="utf-8") as handle:
            handle.write(text)
        return 0
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
