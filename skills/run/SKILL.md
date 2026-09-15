---
name: run
description: Run a grounded deep-research investigation — brief interview, verified evidence ledger, adversarially reviewed report with mechanical citation gates.
disable-model-invocation: true
---

# deeper-research: run

Produce a grounded research report on the user's question. The pipeline archives
every source verbatim, verifies claims with page-grounded votes, measures the
verifier with planted decoys, adversarially reviews the draft, and mechanically
checks every citation. You (the orchestrating session) own the interview, the
launch, and the persistence; the workflow owns everything between.

`$ARGUMENTS` may carry the question, seed URLs/paths, the word `quick`
(= skip the interview, use the `quick` depth preset), or a **plan reference**:
a RUN_ID or run-folder path produced by `/deeper-research:plan`. Invoked bare,
check whether the latest folder under `{runsDir}` holds a locked plan
(`plan.md` present, no `report.md`) and offer to run it.

## 1. Config

Read `research/config.json` in the project root. If it exists, use it and skip
to step 2. If not, ask the user (one question at a time, recommendation first)
which reviewer and default depth they want, then write the file:

```json
{
  "runsDir": "research",
  "workerModel": "sonnet",
  "verifierModel": "haiku",
  "reviewer": { "type": "claude", "model": "inherit" },
  "depth": "standard",
  "blocklist": []
}
```

Those are the sane defaults — a user who says "defaults are fine" gets exactly
this file. `reviewer.model: "inherit"` means the session's model reviews from a
fresh context. Users with a command-line agent for a second model family (the
`pi` coding agent, the OpenAI Codex CLI) can opt into a second-model review
instead:

```json
"reviewer": { "type": "cli", "label": "gpt-5.6-sol",
              "command": "pi -p --no-tools --no-session --no-context-files --no-skills --no-extensions --no-prompt-templates --thinking high --model openai-codex/gpt-5.6-sol @{prompt}",
              "wrapperModel": "sonnet" }
```

The verifier can also be a command-line model. Replace `verifierModel` with:

```json
"verifier": { "type": "cli", "label": "gpt-5.6-luna",
              "command": "pi -p --no-tools --no-session --no-context-files --no-skills --no-extensions --no-prompt-templates --thinking low --model openai-codex/gpt-5.6-luna @{prompt} @{page}",
              "wrapperModel": "sonnet" }
```

`{page}` is the archived page file, attached by the tool itself, so the relay
never reads it. Decoy calibration measures a `cli` verifier exactly as it
measures a Claude one, and the quote gate rechecks its `quote_found` claims
against the page. Pass the object as `args.verifier` at launch.

`command` is ONE line containing the placeholder `{prompt}`; the relay replaces
it with the staged prompt file's path and appends a stdout redirect into
`review.md`. The text before the placeholder must be the exact prefix their
permission allowlist matches (see README → External reviewer). For the Codex
CLI the command is `codex exec --skip-git-repo-check --sandbox read-only -m <model> -c model_reasoning_effort=\"high\" - < {prompt}`;
the legacy `"type": "codex-cli"` with a bare prefix still works and gets the
stdin form appended. `wrapperModel` (default: the worker model) is the relay
agent that stages the prompt and runs the CLI — the external model does the
reviewing, so the relay is deliberately cheap. Never select a `cli` reviewer
for a user who hasn't confirmed the command works in their environment.

Depth presets (a config `caps` object with the same keys as the template's
`args.caps` overrides any preset):

| preset     | angles | fetch r1 | round 2         | verify per source |
| ---------- | ------ | -------- | --------------- | ----------------- |
| `quick`    | 4      | 3–5      | off             | 3 claims × 2 votes |
| `standard` | 6      | 3–6      | 2 angles, 2–4   | 4 claims × 2 votes |
| `deep`     | 9      | 4–8      | 3 angles, 3–5   | 5 claims × 3 votes |

Done when: config values are loaded, either from the file or from answers the
user just gave (which you have written back to `research/config.json`).

## 2. Brief

**From a plan:** if a plan reference was given (or accepted), read `brief.md`
and `plan.md` from its folder — the brief, depth, seeds, and the locked angle
set are all decided; skip the interview entirely and go to step 3.

**Without a plan**, the brief is the locked pre-run understanding between you
and the user. Run a short grilling interview — unless the user passed `quick`
or says "just run it", in which case the question itself is the whole brief
(record depth and move on).

1. **Blind questions first**, one at a time, recommendation included: What
   should the deliverable look like (survey, comparison, decision memo)? Who
   reads it? Any constraints or explicit non-goals? Any seed sources — URLs or
   local files the research must be grounded in? Which depth (recommend the
   config default)?
2. **Then reveal your scope-sketch** — your candidate angles and assumed
   deliverable, drafted only after their answers — and let them correct it.
3. Persist the locked understanding to `{runsDir}/{run_id}/brief.md` (after
   step 3 creates the folder): question wording, seeds, constraints,
   audience/register, non-goals, and the sketch elements the user rejected.

Done when: the user has confirmed the brief (or waived the interview) and depth
is decided.

## 3. Stamp the run

1. Planned run: keep the plan's folder and its RUN_ID — never re-stamp.
   Otherwise `RUN_ID=$(date +"%Y%m%d%H%M%S")`; run folder is
   `{runsDir}/{RUN_ID}/`.
2. `mkdir -p {runsDir}/{RUN_ID}/pages`, and write `{runsDir}/{RUN_ID}/.gitignore`
   containing `pages/` (archived page text is bulky and stays out of version
   control; reports and ledgers stay committable).
3. Copy `workflow-template.js` from this skill's directory into the run folder
   as `{RUN_ID}-deeper-research.js` — VERBATIM, no edits ever: the copy is the
   run's frozen reproducibility artifact, and all configuration travels in
   `args`. Then record the instrument's identity: read the plugin version from
   the skill path (`.../deeper-research/<version>/skills/...`; falls back to
   the plugin's `plugin.json`) and compute
   `sha256sum {runsDir}/{RUN_ID}/{RUN_ID}-deeper-research.js` — these become
   `args.pipelineVersion` and `args.templateSha256`, and the workflow stamps
   them into `results.json` and the report's Methodology block. A run whose
   instrument version is unknown can't be compared against later runs when a
   pipeline bug is found.
4. **Craft 3–5 fresh decoys** — this run, every run, no reuse: decoy detection
   is the only standing measurement of the verifier, and a reused decoy
   measures memory, not judgment. Each decoy is `{claim, quote}`: a
   plausible-sounding, definitely-false claim in-domain for the question, with
   a fabricated supporting quote (≥15 words) that no real page contains. Vary
   the probe type across the set: one the verifier might believe from priors,
   one a fake niche statistic, one whose quote almost-but-not-quite entails the
   claim. Decoys exist only to be caught — they are excluded from the ledger,
   the report, and the review by the workflow itself.

Done when: the run folder exists with `pages/`, `.gitignore`, `brief.md`, the
frozen template copy, and you hold the decoy list.

## 4. Launch

Build the `args` object — the template's header documents every field — and
launch:

- `question`, `runTag: RUN_ID`, `runDir`/`pagesDir` as ABSOLUTE paths,
  `runDate` (today's date at launch, YYYY-MM-DD — a plan may be older than its
  launch), `decoys`, `brief` (the brief.md content, `''` if waived),
  `seedSources` (`[{url, title, localPath}]`, `localPath: ''` unless the user
  gave a local file), `angles` (the locked set from plan.md; omit without a
  plan and the workflow's Scope agent derives them), `blocklist`, `caps` from
  the depth preset, `workerModel`, `verifierModel` (or the `verifier` object),
  `reviewer` from config,
  `pipelineVersion` and `templateSha256` from step 3.3, and `sessionModel`
  (the exact model id of this session — informational, recorded so the run
  record names every role's model). `retrievalOff: true` exists only for
  benchmark control runs (author writes from memory, no retrieval, no
  review); never set it for a research run.

Launch with the Workflow tool: `{ scriptPath: <absolute path to the frozen
copy>, args }` — pass `args` as a real JSON object, never a stringified one.
Iterate on a failed run by relaunching with `resumeFromRunId` — completed
agents replay free from cache.

If the run's search/fetch/verify agents fail with "agent type
'deeper-research:dr-search' not found" (or dr-fetch / dr-verify), the session
predates the plugin's agent registry — tell the user to start a fresh session
and invoke the skill again; nothing is lost.

Done when: the workflow has returned its result object.

## 5. Persist and gate

The workflow cannot write files; you persist its return value and assemble the
report from the files its tail agents wrote. The tail agents wrote
`unreviewed_report.md`, `review.md`, and `final_report.md` into the run folder
(a failed review leaves `review.md` starting with `REVIEW-ERROR:`; a failed
adjudication leaves no `final_report.md`). Let `SCRIPTS` be
`<this skill's directory>/scripts`.

1. `results.json` — the full return object, pretty-printed. Its
   `report_source` says which file is canonical (`final`, or `draft` when
   review or adjudication failed).
2. `python3 $SCRIPTS/assemble-report.py <runDir>` — writes `report.md`
   (the canonical file plus the mechanical "Appendix A: Verification
   ledger") and `report_plain.md` (no Methodology section, no appendix; the
   file to hand to a blind comparison). Prints which source it promoted.
3. `python3 $SCRIPTS/check-report.py <runDir>` — the citation gate: every
   footnote reference has a definition and vice versa, every definition
   carries exactly one ledger URL verbatim, no source is defined twice, and
   the Methodology block appears verbatim. Prints a JSON summary plus one
   `PROBLEM` line per fault.
4. `python3 $SCRIPTS/check-quotes.py <runDir>` — the quote gate.
5. `notes.md` — always include: a `models` line with the exact model id of
   every role (session, worker, verifier, reviewer, relay), the calibration
   tally (strict/soft detection with vote counts, fooled count), the
   check-report summary, round-2 stats (gaps found, angles, new sources), the
   quote-gate tally including the strict/lenient split, and one line per
   anomaly with its explanation.

A run passes only when every gate is CLEAN or every flagged line in `notes.md`
has an explanation: LENIENT-ONLY lines are benign PDF-hyphenation absorptions;
`PROBLEM` and MISMATCH lines must each be investigated and explained before the
run counts as passed. A decoy vote marked `supported` means the verifier was
fooled — report it prominently, never quietly. A `decoy_quote_on_page`
mismatch means a decoy was not false — that decoy's votes measure nothing.

Done when: `results.json`, `report.md`, `report_plain.md`, and `notes.md` are
written and every gate is CLEAN or explained.

## 6. Deliver

Tell the user, leading with the outcome: where `report.md` is, the headline
answer in one sentence, then the trust line — sources fetched (by round),
claims verified, calibration detection rate, and gate status. Offer the run
folder's artifacts (brief, unreviewed draft, review, final) for anyone who
wants to audit the trail.
