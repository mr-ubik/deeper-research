# Benchmark run protocol

This document is the rule set for every baseline run. A run that breaks a
rule is not a baseline run. Vocabulary: `CONTEXT.md` in the repo root.

## 1. Arms

| arm | instrument | launch |
| --- | --- | --- |
| `deeper` | deeper-research at the tag `v0.3.0`; the instrument set hash in `INSTRUMENT.sha256` | the `run` skill, or the Workflow tool on a frozen template copy |
| `builtin` | Claude Code's bundled `deep-research` workflow, extracted and routed; both hashes in the run folder | the Workflow tool on the routed copy, `args` = the question string |
| `floor` | the memory floor for each arm (section 5) | see section 5 |

The instrument does not change between the first baseline run and the
scored result. If it must change, the runs before the change are discarded.

## 2. Models

Every run records the exact model id of every role in its `notes.md`.
Aliases (`sonnet`, `haiku`) are not enough; copy the ids from the transcript.

- `deeper`: session model for scope, gap analysis, author, adjudicate;
  worker `sonnet`; verifier `haiku`; reviewer as configured (record the
  full `cli` command when one is used).
- `builtin`: session model for scope and synthesize; `sonnet` for search,
  fetch, verify. Enforced by the three `model: "sonnet"` edits in the
  routed script, never by a prompt sentence.

## 3. Per question, before the first run

- The brief and the decoy set are written once per question and reused for
  every `deeper` run of that question. Store them in
  `bench/questions/q{n}/brief.md` and `bench/questions/q{n}/decoys.json`.
  Reuse across runs of one question is deliberate: repeated runs must differ
  only in the pipeline's own variance.
- Angles are NOT pinned. Scope derivation is part of the instrument.
- The checklist `checklist.v1.json` is complete and passes
  `validate_checklist.py` before any run.

## 4. Run counts

- `deeper`: 2 to 3 runs per question.
- `builtin`: 1 run per question, and 2 runs on at least one question so
  run-to-run variance has one measurement. Without that, the comparison is
  descriptive only and the report must say so.

## 5. Floors

- `deeper` floor: one run with `retrievalOff: true` (author from memory, no
  review). Same brief, same question. Its report is judged like any other.
- `builtin` floor: a single bare prompt to the session model ("write a
  survey on the question from memory, cite what you can as Markdown
  footnotes"). Record it as an approximation; the builtin has no
  retrieval-off mode.
- Every metric is reported as a delta over the arm's floor, with the raw
  number beside it.

## 6. Run folder

`bench/runs/<run_id>/` holds: `notes.md` (models, instrument hashes, wall
time, anomalies), `cost.json` from `cost.py`, the report as produced
(`report_plain.md` for `deeper`; `result.json` plus the rendered
`report.md` from `render_builtin.py` for `builtin`), and the blinded copy
from `blind.py` with its label map.

A `deeper` run also keeps its own folder under `research/` with the ledger,
pages, and gate outputs. Every gate is CLEAN or explained before the run is
judged.

## 7. Judging

- Judges see only blinded reports. The judge model and thinking level are
  recorded per batch. Blinding is partial: register and structure still
  differ between arms (the builtin's rendered findings carry verifier
  evidence text; deeper's prose is survey register), so the judge prompts
  score items, never pipelines, and never ask which arm a report is from.
- Every batch carries calibration plants. `score.py` refuses a batch without
  them. Report plant detection with every score.
- M1 samples 15 sentences per report with a recorded seed. The judge sees
  the cited source's text: the archived page for `deeper`, a fresh fetch for
  `builtin`; a fetch that fails is scored `source_dead`, not skipped.
- A human spot-checks 10 percent of judge verdicts per question and every
  `discordant_justified_pending` verdict.

## 8. Reading the builtin's verdicts

The builtin's verifiers refute on source quality and datedness as well as
on content. A claim it lists as refuted is "not good enough by its rules",
not "false". Do not read its refuted list as an error count.
