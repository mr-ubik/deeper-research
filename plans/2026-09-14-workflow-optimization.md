# Plan: deeper-research instrument fixes, pi relay, benchmark scaffold

Status: APPROVED 2026-09-14 (human), revised the same day after fetching
origin/main (v0.2.0). Date: 2026-09-14.

Progress (2026-09-14, end of first session):
- WP1 done: branch `fix/gates-testable`, 4 commits, 18 tests.
- WP2 done: branch `fix/instrument-v0.3` (stacked on WP1), 1 commit.
  Reviewed by GPT-5.6-sol (12 findings, all adjudicated and applied).
- WP3 done locally: branch `release/v0.3.0` (stacked on WP2) bumps to
  0.3.0 and adds INSTRUMENT.sha256 (set hash b0b6b966…).
- WP4 done: branch `bench/scaffold` off main, 2 commits, 7 tests, judge
  prompt templates written by Fable.
- Two test runs completed on the frozen template (research/20260914144206
  quick, research/20260914145552 standard with the pi reviewer). Both
  PASSED with explained anomalies; four gate defects found and fixed.
- Snippet triage graft moved from post-baseline to pre-freeze (human
  approved 2026-09-14): landed on `fix/instrument-v0.3` (5e96e2f, 9acead0),
  validated in `research/20260914173554` (73 candidates triaged vs 10
  before; all gates CLEAN). Release re-hashed (set a617e9f6…).
- PRs open and ready for review: #1 bench, #2 gates, #3 instrument, #4
  release (stack #5). Nothing merged.
- Routing change: the human dropped the Codex CLI; GPT models go through
  `pi` only, and `gpt-6-astra` is the peer-level model.
- WP5 builtin pilot done (research/pilot-builtin-20260914183937): routing
  enforceable by three `model: "sonnet"` edits to the extracted bundled
  script (hashes recorded); transcripts show per-agent models; one routed
  run = 99 agents, ~8.2M Sonnet-eq tokens, 6.4 min; output is JSON, not
  Markdown, so the builtin arm needs `bench/render-builtin.py` (deterministic
  JSON→Markdown with footnotes) before blind judging.
- Bench branch `bench/harness` (after the pilot): `render_builtin.py`
  (deterministic JSON→Markdown with footnotes, validated on the pilot
  output), `PROTOCOL.md`, and the judge harness (`sample_m1`,
  `fetch_sources`, `make_batches`, `collect`, `judge_run`; written by
  gpt-6-astra via pi, reviewed, dry-run on run 20260914144206).
- NOT done: a live judge calibration pass (one real judge_run on a test
  report to measure plant detection before any baseline); question
  checklists q1–q4 (human). benchmark-plan.md: disregarded per the human.
Supersedes the F1–F6 list in the earlier handoff where the two differ.
Register: STE. Vocabulary per `CONTEXT.md`.

## 0. Findings that drive the plan

Measured against the code and the two archived runs (20260730145008,
20260731161733):

1. The codex-cli reviewer relay passes ledger + draft as ONE shell argument.
   Linux caps one argument at 128 KiB. Run 2's review prompt was ~116 KB at
   `standard` depth. `deep` depth exceeds the cap and the relay fails with
   exit 127 and no review.
2. Every cap uses `|| default`, so a cap of 0 becomes the default. A
   retrieval-off control run is impossible.
3. `checkCitations` and the appendix append live inside the workflow script.
   They cannot be unit-tested without slicing the template.
4. Author, reviewer, and adjudicator each echo the full report text back
   through structured output. That doubles output tokens on the session
   model (Fable) three times per run, for text that is already on disk.
5. The relay agent for the external reviewer has no `model`, so it runs on
   the session model to execute one Bash command.
6. The quote gate reports a quote of <= 3 words as "absent" (run 2 anomaly 1).
7. `results.json` does not record the session model. Baseline records need
   exact model strings for every role.
8. Decoy calibration mostly measures whether the verifier greps. The decoy's
   quote is the only absent quote in a batch, so `quote_found=false` implies
   the verdict. Soft detection is 100% almost by construction.
9. `research/config.json` in this repo is not the stock config (`opus`
   workers and reviewer). No archived run used the stock config.
10. `pi -p @file --mode json` runs the Codex-subscription models with ~700
    tokens of overhead and returns per-call usage. `omp` does the same with
    ~24k tokens of overhead. `codex exec - < file` reads stdin and also
    avoids the argument cap.

## 0a. Revision after fetching origin/main (v0.2.0)

The review and the first draft of this plan were written against a stale
local checkout (050596e). origin/main (e67c7ef, tag v0.2.0) already holds:

- `skills/plan` (plan skill, `planReviewers` config, `plan.md` artifact).
  The handoff's references to it were correct; the review's "phantom
  references" finding was wrong on that point.
- The stdin relay fix for the codex reviewer (finding 1 is fixed upstream).
- `pipelineVersion` and `templateSha256` stamped into runs.
- A partial short-quote fix in the quote gate (fragments >= 20 chars are
  kept). `16.0.0 (2026-05-27)` is 19 chars and still reports absent, so
  WP1's whole-quote fallback stays.
- `wrapperModel` for the codex relay (default `opus`).

Consequences:
- Freeze target is v0.3.0, as the handoff said.
- WP2 generalises the reviewer to `type: 'cli'` with a `{prompt}`
  placeholder in BOTH `skills/run` and `skills/plan`; the plan skill's relay
  still uses `"$(cat file)"` and gets the same treatment.
- `wrapperModel` default changes from `opus` to the worker model; the relay
  is mechanical.
- The remaining findings (2 through 10) stand.

## 1. Work packages

Each package is one branch and one PR. No package edits the benchmark and
the instrument together.

### WP1 — gates out of the script, tests first (branch `fix/gates-testable`)

Files: `skills/run/scripts/check-quotes.py` (edit),
`skills/run/scripts/check-report.py` (new), `skills/run/scripts/tests/`
(new), `skills/run/scripts/assemble-report.py` (new).

- `check-report.py <runDir>`: footnote-aware citation check and methodology
  verbatim check, run post-hoc by the skill. Rules:
  - every inline `[^label]` has a definition; every definition is referenced.
  - every definition contains exactly one ledger source URL verbatim; every
    ledger URL appears in at most one definition. URL is the join key; the
    footnote label carries no ledger identity.
  - methodology: the `methodology` string from `results.json` appears
    verbatim in the report when the profile is `full`; recorded as
    `not-applicable` under `plain`.
- `check-quotes.py`: a vote with no `quote_found` is a MISMATCH; each decoy's
  persisted `quote` is grepped against the page and a hit is a MISMATCH
  (`decoy_quote_on_page`); a quote with no checkable fragment gets its own
  outcome `too_short` and is matched exact-string instead of being reported
  absent.
- `assemble-report.py <runDir>`: builds `report.md` from `final_report.md`
  (fallback `unreviewed_report.md`) plus the `appendix` string from
  `results.json`; also writes `report_plain.md` (no Methodology section, no
  appendix). Pure string work, no LLM.
- Tests: `python3 -m unittest discover skills/run/scripts/tests`. Fixtures:
  synthetic ledger, known-good report, known-bad reports (orphan footnote,
  missing definition, URL mismatch, absent quote, too-short quote, missing
  `quote_found`, decoy quote present on page). Hand-computed expectations.

Done when: tests pass; both archived runs re-check with the same verdicts as
their `notes.md`, except run 2 anomaly 1 which now reports `too_short` and
CLEAN.

### WP2 — template pre-freeze changes (branch `fix/instrument-v0.3`)

File: `skills/run/workflow-template.js`, plus `skills/run/SKILL.md`,
`agents/*.md`, `README.md`, `CONTEXT.md`.

Behavioral (change what agents are told):
- F5 footnotes. Body cites `[^n]`; one footnote per source; definitions carry
  the bibliography entry; no status markers in the body; hedging carries
  status. Edit sites: `SYNTHESIS_RULES`, `REPORT_STRUCTURE`,
  `REVIEW_CRITERIA` (status errors = hedging vs appendix mismatch),
  `REVISE_RULES`, the "Citation conventions" paragraph of `methodologyMd`,
  README (table + Trust model), `CONTEXT.md` (Unverified lead, Citation
  check).
- F1: `quote_found` required in `BATCH_VOTES_SCHEMA`.
- Reviewer sees the pages dir. Both reviewer paths get one sentence: page
  text is under `{PAGES_DIR}`; check a quote against the page before calling
  it a status error.

Structural (change plumbing, not instructions):
- Generic CLI reviewer. `reviewer.type: 'cli'` with `command` containing a
  `{prompt}` placeholder, e.g.
  `pi -p --no-tools --no-session --no-context-files --no-skills --no-extensions --no-prompt-templates --thinking high --model openai-codex/gpt-5.6-sol @{prompt}`
  or `codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-sol - < {prompt}`.
  `codex-cli` stays accepted as an alias that maps to the stdin form. The
  relay writes the prompt file, runs ONE single-line command, writes stdout
  to `review.md`. Relay agent runs on `WORKER` with low effort.
- Author, reviewer, adjudicator write their file and return `{ok, notes,
  bytes}` only. The workflow no longer holds report text. Citation check,
  methodology check, appendix append move to WP1 scripts. The workflow still
  returns `ledger`, `methodology`, `appendix`, `calibration`, `tally`,
  `report_source`.
- F2: decoy `quote` in each source's `calibration` object and in
  `calibration.details`.
- F4: vote counts next to every detection percentage in `methodologyMd`.
- Caps: `??` instead of `||`, so 0 is honored. `fetchMax: 0` = retrieval-off.
- `args.sessionModel` (informational string) recorded in `models`.
- F3 dropped. Decoy position stays last; the position is not the tell (see
  finding 8). The real calibration upgrade is post-baseline (section 3).

Skill changes (`SKILL.md`): step 5 runs `assemble-report.py`,
`check-report.py`, `check-quotes.py` in that order; config example shows the
pi reviewer; decoy guidance stays question-level (the page is not known at
crafting time); a `models` line in `notes.md` pins exact strings for
session, worker, verifier, reviewer.

Done when: template passes the `node --check` wrapper; one `quick` smoke run
completes with all three gates CLEAN or explained; one `standard` run with the
pi reviewer exercises the relay at real prompt size and `review.md` is a
real review.

### WP3 — freeze (branch `release/v0.3.0`)

- `plugin.json` version 0.3.0, tag `v0.3.0`.
- `INSTRUMENT.sha256`: one hash over `workflow-template.js`, the three
  scripts, the three agent files, and both `SKILL.md` files. The benchmark records this
  hash per run. After the tag, none of these files change until the
  baseline is scored.
- Reset `research/config.json` to stock, or have the bench pass explicit
  args. Decision recorded in the run notes.

### WP4 — benchmark scaffold (branch `bench/scaffold`)

Directory `bench/`, never touching `skills/`.

- `bench/benchmark-plan.md`: the methodology document, checked in.
- `bench/questions/q{n}/checklist.v1.json` per the handoff schema.
- `bench/score.py` + fixtures; refuses a judge batch without plant rows.
- `bench/prompts/`: M1 attribution protocol, M3/M4 checklist scoring.
- `bench/judge.sh`: ONE single-line pi call per batch,
  `pi -p --mode json --no-tools ... --model openai-codex/gpt-5.6-sol @prompt`,
  parses the JSON stream for the verdict text and the usage block.
- `bench/blind.py`: takes `report_plain.md` from either arm, relabels
  footnotes sequentially, strips arm-identifying headings. Output is what
  judges see.
- `bench/cost.py`: sums `message.usage` over a workflow run's
  `agent-*.jsonl` transcripts, plus pi usage from `judge.sh` output.
  `cost.estimated` becomes false.
- `bench/runs/<run_id>/notes.md` template: instrument hash, exact model
  strings, pinned brief and decoys, profile, arm.

Benchmark protocol deltas from the handoff:
- Per question, pin the brief and the decoy set and reuse them across that
  question's 2–3 deeper-research runs. Angles stay Scope-derived.
- Builtin arm: 2 runs on at least one question, so run-to-run variance has
  one measurement. Otherwise the comparison is descriptive only.
- Retrieval-off floor: deeper arm uses `fetchMax: 0` (real, after WP2);
  builtin arm uses a bare prompt (approximation, recorded).

### WP5 — pilot (one builtin `/deep-research` run)

Answers: (a) can model routing be enforced by editing the generated JS,
(b) does `/workflows` show per-agent models, (c) cost per run,
(d) does the builtin cite with footnotes. All four go in
`bench/runs/pilot/notes.md`. If (a) fails, stop and escalate.

## 2. Order and checkpoints

1. WP1 (no LLM calls; tests only).
2. WP2 (needs two test runs: one `quick`, one `standard` with pi reviewer).
3. Human review of PR1 + PR2. WP3 freeze after merge.
4. WP4 (no LLM calls except judge fixture smoke).
5. WP5 pilot (one builtin run). Report. Stop.
6. Human-owned: survey confirmation, tea rubric, PdM practitioner list.
7. Baseline runs only after the human reviews the pilot.

## 3. Roadmap (recorded, not this cycle)

- Misattribution decoys: a real verbatim quote from the page paired with a
  false claim it does not entail. Measures judgment, not grepping. Needs an
  in-workflow decoy assignment step, so it is behavioral and post-baseline.
- Second-family votes: a pi relay agent that casts a whole source's votes
  through `gpt-5.4-mini` in one call, as an optional third vote. Cost is one
  relay subagent per source; worth it only if haiku calibration degrades.
- Ledger-as-contract: versioned ledger schema; `assemble-report.py` becomes
  the first renderer over it.
- Snippet-triage graft (from the handoff), UC4 schema extraction (from the
  handoff).
