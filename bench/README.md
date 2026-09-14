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

## Judge harness

The sampler selects cited sentences from a blinded report in reproducible document order.

```sh
python3 bench/sample_m1.py blinded.md --n 15 --seed 1 --out items.json
```

The source cache reuses deeper archives when available and fetches remaining URLs once.

```sh
python3 bench/fetch_sources.py --items items.json --run-dir RUN_DIR --out sources/
```

The batch builder fills attribution and checklist prompts with shuffled calibration plants.

```sh
python3 bench/make_batches.py --items items.json --sources sources/ --report blinded.md --checklist checklist.v1.json --run-id R --question-id Q --out batches/
```

The collector combines completed judge outputs after each batch has been judged with `judge.py`.

```sh
python3 bench/collect.py --manifest batches/manifest.json --outputs judge-outputs/ --out verdicts.csv
```

The orchestrator performs the complete sequence, preserves completed batches, records failures without retrying, and prints the scoring command.

```sh
python3 bench/judge_run.py --report blinded.md --checklist checklist.v1.json --run-id R --question-id Q --out judge-run/ --run-dir RUN_DIR
```
