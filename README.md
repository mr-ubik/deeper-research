# deeper-research

A [Claude Code](https://code.claude.com) plugin for **grounded deep research**:
give it a question (and optionally your own source documents) and it returns a
survey-grade report in which every factual statement is traceable to an
archived source, every verification step is measured, and every citation is
mechanically checked.

Claude Code ships a built-in `/deep-research` workflow. This plugin is the same
idea taken further — for when you need to *trust* the output, not just receive
it:

| | built-in `/deep-research` | `deeper-research` |
| --- | --- | --- |
| Source handling | fetched, then discarded | full page text archived verbatim per run |
| Claim verification | votes on claims | votes grounded in the archived page, with a mechanical quote-presence check |
| Verifier trust | assumed | **measured every run**: known-false decoy claims are planted and the detection rate is reported |
| Your own documents | — | seed sources: ingested, verified, and citable like any retrieved source |
| Retrieval | one pass | two rounds — a gap analysis of round-1 evidence targets round 2 |
| Report | cited summary | survey register, footnote citations with verification status carried by hedged prose, adversarial review, per-claim verification appendix |
| Checks | — | mechanical citation, methodology, and quote gates run by plain scripts after the run; failures reported, never auto-fixed |

## Install

From a Claude Code session:

```
/plugin marketplace add mr-ubik/deeper-research
/plugin install deeper-research@deeper-research
/reload-plugins
```

Then **start a fresh session** (the run's worker agents register at session
start) and you're ready. Requires Claude Code v2.1.154+ with dynamic workflows
available on your plan, the WebSearch tool, and `python3` for the post-run
quote gate.

What those commands do: a Claude Code *marketplace* is just a catalog file a
repo can host, and this repo is its own single-plugin marketplace — the first
command registers the catalog, the second installs the plugin from it (the
syntax is `<plugin>@<marketplace>`; both are named `deeper-research` here).
Installation caches a copy of the repo locally and loads the plugin in every
session; when new versions are released, `/plugin marketplace update` picks
them up. The commands fetch this repo over git with your credentials, so they
work for any copy of the repo you can clone.

For local development (or to skip the install machinery entirely): clone this
repo and launch with `claude --plugin-dir ./deeper-research` — that loads your
working copy directly, uncommitted changes included.

## Use

Two skills. `plan` locks the scope of a run under adversarial review; `run`
executes it. Planning is optional — `run` on its own still interviews you and
derives search angles in-pipeline — but angle quality bounds what the run can
retrieve, and planning is the only stage where a bad decomposition is cheap to
fix.

```
/deeper-research:plan How do the major vector databases handle index rebuilds under sustained writes?
/deeper-research:run 20260730143000        # execute the locked plan
```

or, skipping the planning stage:

```
/deeper-research:run How do the major vector databases handle index rebuilds under sustained writes?
```

What `plan` does:

1. **Interview** — grills you on scope (invoking your own grilling skill if
   you have one installed): deliverable shape, audience, constraints,
   non-goals, seed sources, depth.
2. **Draft** — a brief plus the full search-angle set, drafted from your
   answers and the seed documents.
3. **Adversarial review** — each configured plan reviewer independently
   attacks the draft (coverage gaps, overlapping angles, ambiguities,
   conflicts with the seeds), having read the seed documents first. Findings
   are adjudicated — applied only when the evidence supports them — surviving
   questions come back to you, and the result is locked into `brief.md` +
   `plan.md` in a stamped run folder.

What `run` does:

1. **Brief** — reads the plan if you pass one; otherwise a short interview
   locks a `brief.md` the pipeline honors. Add `quick` to your invocation to
   skip the interview and run small.
2. **Run** — a background workflow fans out search angles, archives and
   claim-extracts each source, verifies claims with independent page-grounded
   votes (with planted decoys measuring the verifier), analyzes gaps, retrieves
   a second round, then drafts, adversarially reviews, and adjudicates the
   report. Watch progress with `/workflows`.
3. **Deliver** — the report plus its full audit trail land in
   `research/<run_id>/` in your project:

```
research/
├── config.json              # your standing configuration
└── 20260730143000/
    ├── report.md            # the deliverable (ends with a per-claim verification appendix)
    ├── report_plain.md      # the same report without the Methodology section and appendix
    ├── brief.md             # the locked pre-run understanding
    ├── plan.md              # locked angles + adjudicated review findings (planned runs only)
    ├── results.json         # full structured run record (ledger, votes, calibration, methodology)
    ├── unreviewed_report.md # draft before adversarial review
    ├── review.md            # the adversarial review
    ├── final_report.md      # draft after adjudicated revision
    ├── notes.md             # calibration tally, gate results, explained anomalies
    ├── <run_id>-deeper-research.js  # frozen workflow copy (reproducibility artifact)
    └── pages/               # archived verbatim page text (gitignored)
```

Reports are committable; the bulky `pages/` archive is excluded by a dropped
`.gitignore`.

## Configure

`research/config.json` is generated by a short setup interview on your first
run and hand-editable after:

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

- **depth** — `quick` (4 angles, single round) / `standard` (6 angles, two
  rounds) / `deep` (9 angles, two rounds, 3 votes per claim). A `caps` object
  overrides any preset field.
- **verifierModel** — the model casting verification votes. A small model works
  well here *because* votes are page-grounded and decoy-calibrated: every run
  reports how often the verifier caught planted-false claims, so you see its
  reliability instead of assuming it.
- **reviewer** — who adversarially reviews the draft. Default: the session's
  model in a fresh context (a reviewer that never saw the author's reasoning).
- **planReviewers** — the panel that attacks a plan before launch (an array;
  each entry has the same shape as `reviewer`). Default when absent:
  `[{ "type": "claude", "model": "inherit" }]`. Append a `codex-cli` entry for
  a two-model panel — different model families have different blind spots.

### External reviewer (optional)

A second model family can review instead — different models have different
blind spots. Any command-line agent that reads a prompt from a file works;
the `pi` coding agent on the Codex subscription is the leanest relay we have
measured (about 700 tokens of overhead per call):

```json
"reviewer": {
  "type": "cli",
  "label": "gpt-5.6-sol",
  "command": "pi -p --no-tools --no-session --no-context-files --no-skills --no-extensions --no-prompt-templates --thinking high --model openai-codex/gpt-5.6-sol @{prompt}",
  "wrapperModel": "sonnet"
}
```

`command` is one line with a `{prompt}` placeholder: the relay replaces it
with the staged prompt file's path and redirects stdout into `review.md`.
For the OpenAI Codex CLI use
`codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-sol -c model_reasoning_effort=\"high\" - < {prompt}`
(the legacy `"type": "codex-cli"` with a bare prefix still works). The same
shape works as a `planReviewers` entry.

`wrapperModel` sets the relay agent that stages the prompt and runs the CLI
(default: the worker model): the external model does the reviewing, so the
relay is deliberately cheap.

Add a matching prefix rule to your permission allowlist (e.g.
`Bash(pi -p *)` or `Bash(codex exec --skip-git-repo-check --sandbox read-only *)`
in `.claude/settings.json`) — permission rules are prefix rules, and the
review call is made non-interactively from a background agent, so an unlisted
command cannot prompt you and the review degrades to the unreviewed draft.
Only enable this if the command already works in your environment.

## Trust model

The design premise: an LLM research pipeline earns trust by *measuring* its own
weakest links instead of asserting them.

- **Verbatim archives.** Verification against a paraphrase is hearsay; every
  fetched page is persisted verbatim, and votes read the archive, not the
  claim's say-so.
- **Decoy calibration.** Every run plants known-false claims with fabricated
  quotes among the real ones. The report's Methodology section states the
  detection rate. An unmeasured verifier is untrusted.
- **Footnoted sources, hedged prose.** Every ledger-derived statement carries
  a Markdown footnote to its source; how well it was verified is stated in
  the sentence itself (a claim with full supported votes reads plainly, an
  unverified lead reads as one), and an uncited substantive sentence is
  explicitly authorial judgment. The reviewer polices the hedging against
  the ledger, and a script checks the footnote wiring.
- **Adversarial review, adjudicated.** A separate context reviews the draft
  against the evidence ledger; the adjudicator applies only findings the
  ledger supports — reviewers overreach too.
- **Mechanical gates.** Citation wiring, methodology verbatimness, and
  quote-presence are checked by plain code after the run. Gates reject; they
  never auto-fix.

Vocabulary (ledger, decoy, gate, brief, angle…) is defined in
[CONTEXT.md](CONTEXT.md).

## Cost

A run is a multi-agent workflow: expect tens of subagent calls (mostly small,
cheap models — search/fetch on `sonnet`, votes on `haiku`) plus a handful of
session-model calls (scope, gap analysis, author/review/adjudicate). `quick`
depth exists to scope a question cheaply before committing to `deep`. Progress,
per-agent tokens, and a stop control are in `/workflows`.

## License

Apache-2.0 — see [LICENSE](LICENSE). © Michele "Ubik" De Simoni.
