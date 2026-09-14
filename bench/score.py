#!/usr/bin/env python3
"""Aggregate benchmark verdict CSV files into one score document."""

import argparse
import csv
import json
import sys

from validate_checklist import validate


VERDICTS = {
    "M1": {"supported", "partial", "unsupported", "unverifiable", "source_dead"},
    "M2": {"found", "missed_closed", "missed_findable", "surplus_postcutoff", "surplus_contemporaneous"},
    "M3": {"covered", "partial", "absent", "trap_avoided", "trap_asserted", "hedged", "hedge_violated"},
    "M4": {"concordant", "omitted", "discordant_unjustified", "discordant_justified_pending"},
}
KIND_VERDICTS = {
    "must-have": {"covered", "partial", "absent"},
    "trap": {"trap_avoided", "trap_asserted"},
    "hedge-required": {"hedged", "hedge_violated"},
}
HEADER = ["run_id", "question_id", "metric", "item_id", "verdict", "judge", "evidence_note"]


class ScoreError(Exception):
    """A scoring input is invalid. `raw` = print the message without an ERROR: prefix."""

    def __init__(self, message, raw=False):
        super().__init__(message)
        self.raw = raw


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != HEADER:
            raise ScoreError(f"{path}: verdict header must be exactly {','.join(HEADER)}")
        return list(reader)


def choose_rows(rows, judge):
    selected = {}
    for row in rows:
        metric = row["metric"]
        if metric not in VERDICTS:
            raise ScoreError(f"unknown metric: {metric!r}")
        if row["verdict"] not in VERDICTS[metric]:
            raise ScoreError(f"unknown verdict for {metric}: {row['verdict']!r}")
        if row["judge"] not in {"gpt", "human"}:
            raise ScoreError(f"unknown judge: {row['judge']!r}")
        if judge != "all" and row["judge"] != judge:
            continue
        key = (metric, row["item_id"])
        old = selected.get(key)
        if old is not None and old["judge"] != row["judge"]:
            winner = row if row["judge"] == "human" else old
            print(f"WARNING: human verdict overrides gpt for {metric}/{row['item_id']}", file=sys.stderr)
            selected[key] = winner
        else:
            selected[key] = row
    return list(selected.values())


def score(checklist, rows, plants, meta):
    claims = {item["id"]: item for item in checklist["claims"]}
    refs = {item["id"]: item for item in checklist["references"]}
    conclusions = {item["id"] for item in checklist["conclusions"]}
    result = {
        "run_id": meta["run_id"], "question_id": meta["question_id"],
        "pipeline": meta["pipeline"], "floor_run": meta["floor_run"],
        "m1": {"mechanical_ok": meta["mechanical_ok"], "sampled": 0, "supported": 0,
               "partial": 0, "unsupported": 0, "unverifiable": 0, "source_dead": 0},
        "m2": {"load_bearing_total": sum(r["class"] == "load-bearing" for r in refs.values()),
               "found": 0, "missed_closed": 0, "missed_findable": 0,
               "surplus_postcutoff": 0, "surplus_contemporaneous": 0},
        "m3": {"claims": len(claims), "covered": 0, "partial": 0, "absent": 0,
               "traps_asserted": 0, "hedges_violated": 0},
        "m4": {"conclusions": len(conclusions), "concordant": 0, "omitted": 0,
               "discordant_unjustified": 0, "discordant_justified_pending": 0},
        "judge_calibration": {"plants": 0, "detected": 0}, "cost": meta["cost"],
    }
    nonplant_metrics, plant_metrics = set(), set()
    for row in rows:
        metric, item, verdict = row["metric"], row["item_id"], row["verdict"]
        if item.startswith("plant."):
            plant_metrics.add(metric)
            expected = plants.get((metric, item))
            if expected is not None:
                result["judge_calibration"]["plants"] += 1
                result["judge_calibration"]["detected"] += verdict == expected
            continue
        nonplant_metrics.add(metric)
        if metric == "M1":
            result["m1"]["sampled"] += 1
            result["m1"][verdict] += 1
        elif metric == "M2":
            if item.startswith("surplus."):
                if not verdict.startswith("surplus_"):
                    raise ScoreError(f"M2 surplus item {item!r} has non-surplus verdict {verdict!r}")
                result["m2"][verdict] += 1
            else:
                if item not in refs:
                    raise ScoreError(f"unknown M2 reference id: {item!r}")
                if refs[item]["class"] != "load-bearing":
                    print(f"WARNING: ignoring background M2 reference {item}", file=sys.stderr)
                    continue
                if verdict.startswith("surplus_"):
                    raise ScoreError(f"M2 checklist reference {item!r} has surplus verdict {verdict!r}")
                result["m2"][verdict] += 1
        elif metric == "M3":
            if item not in claims:
                raise ScoreError(f"unknown M3 claim id: {item!r}")
            kind = claims[item]["kind"]
            if verdict not in KIND_VERDICTS[kind]:
                raise ScoreError(f"M3 verdict {verdict!r} is invalid for claim kind {kind!r}")
            target = {"trap_avoided": "covered", "hedged": "covered",
                      "trap_asserted": "traps_asserted", "hedge_violated": "hedges_violated"}.get(verdict, verdict)
            result["m3"][target] += 1
        else:
            if item not in conclusions:
                raise ScoreError(f"unknown M4 conclusion id: {item!r}")
            result["m4"][verdict] += 1
    if not nonplant_metrics:
        # An empty verdict set must never score as "zero everywhere, exit 0".
        raise ScoreError("REFUSED: no verdict rows for this run (judge outputs missing?)", raw=True)
    missing = sorted(nonplant_metrics - plant_metrics)
    if missing:
        raise ScoreError(f"REFUSED: metric {missing[0]} has no calibration plants", raw=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--checklist", required=True)
    parser.add_argument("--verdicts", required=True, nargs="+")
    parser.add_argument("--plants", required=True)
    parser.add_argument("--run-meta", required=True)
    parser.add_argument("--judge", choices=("gpt", "human", "all"), default="all")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        with open(args.checklist, encoding="utf-8") as handle: checklist = json.load(handle)
        errors = validate(checklist)
        if errors: raise ScoreError("invalid checklist: " + "; ".join(errors))
        with open(args.run_meta, encoding="utf-8") as handle: meta = json.load(handle)
        plant_map = {}
        with open(args.plants, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["metric", "item_id", "expected_verdict"]:
                raise ScoreError("plants header must be exactly metric,item_id,expected_verdict")
            for row in reader:
                if row["metric"] not in VERDICTS or row["expected_verdict"] not in VERDICTS[row["metric"]]:
                    raise ScoreError(f"invalid plant expectation: {row}")
                plant_map[(row["metric"], row["item_id"])] = row["expected_verdict"]
        raw = []
        for path in args.verdicts: raw.extend(read_csv(path))
        matching = []
        for row in raw:
            if row["run_id"] != meta["run_id"] or row["question_id"] != meta["question_id"]:
                print(f"WARNING: ignoring foreign row {row['run_id']}/{row['question_id']}", file=sys.stderr)
            else: matching.append(row)
        result = score(checklist, choose_rows(matching, args.judge), plant_map, meta)
        output = json.dumps(result, indent=2) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle: handle.write(output)
        else: sys.stdout.write(output)
        return 0
    except (OSError, json.JSONDecodeError, KeyError, ScoreError) as error:
        prefix = "" if isinstance(error, ScoreError) and getattr(error, "raw", False) else "ERROR: "
        print(prefix + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
