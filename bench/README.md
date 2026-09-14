# Research Pipeline Benchmark

This directory contains a small benchmark for research reports. It compares the `deeper` and `builtin` pipelines.

## Layout

`questions/` contains the checklist schema and versioned question checklists.

`tests/fixtures/` contains synthetic input files. The unit tests do not call an LLM.

## Verdict CSV

The verdict header is `run_id,question_id,metric,item_id,verdict,judge,evidence_note`.

Each row records one judgment for M1, M2, M3, or M4. The judge value is `gpt` or `human`.

Plant item identifiers start with `plant.`. The plants file uses `metric,item_id,expected_verdict`.

## Commands

Validate a checklist:

```sh
python3 bench/validate_checklist.py bench/questions/q0/checklist.v1.json
```

Score verdict files:

```sh
python3 bench/score.py --checklist CHECKLIST --verdicts VERDICTS --plants PLANTS --run-meta RUN
```

Blind a report:

```sh
python3 bench/blind.py REPORT --out BLINDED --map LABEL_MAP
```

Summarize costs:

```sh
python3 bench/cost.py TRANSCRIPT_DIR --judge-usage EVENTS
```

Run one judge call:

```sh
python3 bench/judge.py --prompt PROMPT --out-text REVIEW --out-json EVENTS
```

Run the unit tests from the repository root:

```sh
python3 -m unittest discover bench/tests
```
