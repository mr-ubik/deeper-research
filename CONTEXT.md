# CONTEXT — deeper-research ubiquitous language

Glossary only. No implementation details — those live in the skill and the
workflow template.

## Pre-run

- **Brief** — the locked pre-run understanding between user and orchestrator:
  question wording, seeds, constraints, audience/register, explicit non-goals.
  Produced by a short interview (blind open questions first, scope-sketch
  second), persisted as `brief.md` in the run folder.
- **Scope-sketch** — the orchestrator's informal, non-binding read of question +
  seeds (candidate angles + assumed deliverable), drafted *before* interviewing
  the user, revealed only after the blind open questions. Rejected elements are
  persisted inside the brief.
- **Seed source** — a user-provided grounding source, ingested at the head of
  the run, verified and citable like any other source (round tag 0).
- **Plan** — the locked pre-run scope artifact: the brief plus a hardcoded,
  adversarially reviewed angle set, persisted as `plan.md` in a stamped run
  folder. A run launched from a plan skips the interview and the in-pipeline
  scope derivation.
- **Plan reviewer** — an adversarial agent attacking the draft brief + angles
  before launch (coverage, coherence, grounding), reading the seed documents
  before judging. Findings are adjudicated, never blindly applied.
- **Depth preset** — a named bundle of caps (`quick` / `standard` / `deep`)
  controlling angles, fetch budgets, rounds, and votes.

## In-run

- **Run** — one execution of the pipeline on one question, identified by a
  timestamp `run_id`, with all artifacts frozen in `{runsDir}/{run_id}/`.
- **Scope** — the in-pipeline derivation of search angles from question +
  brief + seeds. Exactly one deterministic angle-derivation per run.
- **Angle** — one independent search direction; the unit of search fan-out.
- **Ledger** — the run's structured claims record: sources keyed `S{i}`, each
  with verified claims (with votes) and an unverified tail. The only evidence
  base synthesis may draw from. Decoys never enter it.
- **Verifier** — the model casting per-claim support votes, page-grounded
  (reads the archived page, checks the quote is present).
- **Vote** — one verifier judgment on one claim: verdict + `quote_found`.
- **Decoy** — a known-false, in-domain claim with a fabricated quote, injected
  into verification to measure the verifier. Detection tallies: **strict**
  (refuted), **soft** (refuted or unverifiable), **fooled** (supported).
- **Calibration** — the per-run decoy-detection tally; the standing measurement
  that makes the verifier trusted. An unmeasured verifier is untrusted.
- **Unverified lead** — a claim carried in the ledger without full support
  (beyond the vote cap, split/failed votes, or quote not found); citable only
  with the sentence itself hedged to say so.
- **Control run** — a run with `retrievalOff`: no scope, search, fetch, or
  verification; the author writes from model memory alone and no review
  runs. Exists to measure the memory floor a benchmark compares against.
- **Adjudication** — the revision pass over reviewer findings: apply a finding
  only if the evidence supports it (the ledger for report review, the
  brief/seeds for plan review); reviewers can overreach.
- **Canonical report** — the run's one official report artifact (`report.md`):
  the adjudicated final (or the unreviewed draft when review failed) plus the
  mechanical verification appendix, assembled by script after the run.
- **Plain report** — `report_plain.md`: the canonical report without the
  Methodology section and the appendix, for blind comparison with reports
  from other pipelines.

## Gates and checks

- **Gate** — a mechanical pass/fail check that can reject a run: a run does not
  count as passed until every gate is CLEAN or every anomaly is explained.
  Steps *produce*; gates *reject*.
- **Quote gate** — the post-run recheck that every vote's evidence quote
  actually appears in the archived page, and that decoy votes report the quote
  absent.
- **Citation check** — the mechanical validation of the report's footnotes
  against the ledger: every footnote reference has a definition and every
  definition is referenced, every definition carries exactly one ledger URL
  verbatim, and no source is defined twice. The URL is the join key; footnote
  numbers carry no ledger identity.
- **Methodology check** — the mechanical validation that the report includes
  the generated Methodology section verbatim.
