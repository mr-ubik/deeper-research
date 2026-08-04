---
name: plan
description: Lock a deeper-research plan before launch — grilling interview, drafted brief + angle set, adversarial pre-launch review grounded in the seed documents, adjudicated into a frozen plan that run executes.
disable-model-invocation: true
---

# deeper-research: plan

Lock the scope of a research run before any retrieval tokens are spent. The
output is a stamped run folder holding `brief.md` and `plan.md` — the locked
question, constraints, and a hardcoded angle set that has survived adversarial
review. `/deeper-research:run <RUN_ID>` then executes it, skipping its own
interview and in-pipeline scope derivation.

Planning is optional: `run` alone still works for one-shot and `quick` runs.
Plan when the question deserves scrutiny before the spend — angle quality
bounds recall, and this is the only stage where a bad decomposition is cheap
to fix.

`$ARGUMENTS` may carry the question and seed URLs/paths.

## 1. Config

Read `research/config.json`. If it doesn't exist, run the same setup interview
as run's step 1 and write it. Plan reviewers come from the `planReviewers`
key — an array of reviewer objects with the same shapes as `reviewer`:

```json
"planReviewers": [
  { "type": "claude", "model": "inherit" }
]
```

That single fresh-context reviewer is the default when the key is absent —
never nag an existing config for it. Users with a working Codex CLI can append
a `codex-cli` entry (same `{type, label, command}` shape and same permission
prefix-rule caveats as run's external reviewer); different model families have
different blind spots, so a two-reviewer panel is the high-trust setup.

Done when: config is loaded and the reviewer panel is known.

## 2. Interview

If a user-side grilling skill is available in this session, literally invoke
it — prefer `grill-with-docs`, fall back to `grilling` — passing the question
and any seed sources as its subject. If neither exists, run the built-in
interview from run's step 2: blind open questions first (deliverable shape,
audience, constraints, non-goals, seed sources, depth — one at a time,
recommendation included), then reveal your scope-sketch and let the user
correct it.

Either way, before moving on, confirm every brief field is actually captured:
question wording, deliverable, audience, constraints, non-goals, seeds, depth.
A grill session that skipped one gets a follow-up question, not a guess.

Done when: the user has confirmed the pre-run understanding and depth.

## 3. Stamp and draft

1. `RUN_ID=$(date +"%Y%m%d%H%M%S")`; create `{runsDir}/{RUN_ID}/`. (run will
   add `pages/`, the `.gitignore`, the frozen template, and fresh decoys at
   launch — those are launch-time artifacts, not plan-time ones.)
2. If any seed source is URL-only, fetch it now and save the text as
   `{runsDir}/{RUN_ID}/seeds/seed{n}.txt` so every reviewer grounds in the
   same copy. Local-file seeds are used in place. The run re-ingests seeds
   properly (round 0) at launch; these snapshots exist only to ground the
   review.
3. Read the seed documents, then draft the brief (same fields as `brief.md`)
   and the angle set — angle count from the depth preset (`quick` 4 /
   `standard` 6 / `deep` 9). Each angle must meet the bar the in-pipeline
   Scope agent is held to: self-contained (a search agent sees ONLY the angle
   text — never "the seed" or "the brief"); one facet each, no overlap;
   phrased to retrieve primary sources; ending with "Source modality most
   needed: ..." naming the source kind that best evidences that facet.
   Jointly the angles must cover the question's own pillars plus any the
   brief or seeds establish.

Done when: the run folder exists and you hold a draft brief + numbered angles.

## 4. Adversarial review

Every configured plan reviewer attacks the draft independently, in parallel.
Each reviewer receives: the question, the draft brief, the numbered angles,
and the seed documents as file paths it MUST read before judging — a
quote-blind reviewer just does entailment on your summary. The attack surface:

- **Coverage** — pillars of the question or seed themes no angle retrieves;
  angles that overlap; angles phrased so they'll surface secondary/SEO
  content instead of primary sources.
- **Brief coherence** — deliverable/audience mismatch, ambiguous question
  wording, constraints that contradict the angles, unstated assumptions.
- **Grounding** — anything the seeds contradict or treat as central that the
  plan ignores.

Each reviewer returns findings (severity + the evidence behind each) plus
candidate questions for the user — only questions whose answer would change
the plan. Instruct every reviewer: "If you find nothing material, say so
explicitly" — an invented finding is worse than none.

- `claude` reviewers: a fresh-context subagent (Agent tool; `inherit` = omit
  the model override). They may WebFetch URL seeds directly.
- `codex-cli` reviewers: write the prompt (with inline file paths) to a
  uniquely named file in the run folder yourself, then spawn a relay subagent
  on the entry's `wrapperModel` (default `opus` — the external model does the
  reviewing, so the relay never runs on the session model), name prefixed
  `[codex]`. Its ONLY job: run `<command> "$(cat <file>)"` as ONE Bash call —
  a single line, no compounds, no heredocs (the allowlist matches the prefix)
  — and return stdout verbatim; never retry, and on error or empty output
  return an explicit error string instead of a review. The CLI's read-only
  sandbox has no network, which is why step 3 snapshots URL seeds to disk.

Done when: every reviewer has returned findings (or an explicit nothing-found).

## 5. Adjudicate

Reviewers overreach — findings are applied through judgment, never blindly:

1. For each finding, decide **applied** or **rejected** with a one-line
   reason. Apply only findings the question, brief, or seeds actually
   support.
2. Dedup the candidate questions across reviewers, drop any the brief already
   answers, and ask the user only the survivors — one at a time,
   recommendation first.
3. Revise the brief and angles from the applied findings and the user's
   answers. If the revision is material (angles added/removed, deliverable
   changed), show the user the final angle set for a last confirmation.

Done when: brief and angles are final and user-confirmed.

## 6. Persist and deliver

1. `brief.md` — the locked brief, including the sketch/plan elements the user
   rejected (same convention as run's).
2. `plan.md` — the execution half:
   - question, depth, seed list;
   - the locked, numbered angle set (this is what run passes as
     `args.angles`);
   - per-reviewer findings, each marked applied/rejected with its reason;
   - the questions asked in step 5 and the user's answers.

Tell the user the plan is locked: the folder path, the final angle count, one
line per reviewer on what their review changed (or "no material findings"),
and that `/deeper-research:run {RUN_ID}` launches it.
