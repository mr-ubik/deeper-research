<!--
M3 (claim coverage) and M4 (conclusion concordance) judge prompt. One batch =
ONE blinded report against ONE question's checklist. The harness fills:
  {{RUN_ID}} {{QUESTION_ID}}
  {{QUESTION}}     — the research question
  {{REPORT}}       — the blinded report (bench/blind.py output)
  {{CLAIMS}}       — one block per checklist claim:
                     [item_id=q1.c001] kind=must-have|trap|hedge-required
                     CLAIM: <text>
                     ACCEPTANCE: <what counts as covered>
  {{CONCLUSIONS}}  — one block per checklist conclusion:
                     [item_id=q1.k01]
                     CONCLUSION: <text>
Calibration plants are ordinary items whose item_id starts with "plant.";
the judge is never told which. Plant kinds the harness uses:
  a must-have claim copied verbatim from the report -> expected covered
  a must-have claim on a topic absent from the report -> expected absent
  a trap the report explicitly refutes             -> expected trap_avoided
  a conclusion the report states in its own words  -> expected concordant
-->

You are judging a research report against a checklist. Judge ONLY from the
report text below. Do not reward a claim for being true; reward it for being
present in the report as the checklist describes.

Part 1 — claims (metric M3). The verdict vocabulary depends on the claim's
kind:

- kind=must-have: covered (the report states it, meeting the ACCEPTANCE line,
  in any wording), partial (stated in a narrower, weaker, or incomplete form,
  or only implied), absent (not in the report).
- kind=trap: a trap is a plausible false statement. trap_avoided (the report
  does not assert it, or explicitly refutes or hedges it), trap_asserted (the
  report states it as fact).
- kind=hedge-required: a statement that must not be asserted flatly. hedged
  (the report presents it with uncertainty, attribution, or as disputed, or
  omits it), hedge_violated (the report asserts it without qualification).

Part 2 — conclusions (metric M4). Each conclusion is a position the reference
survey takes. Verdicts:

- concordant: the report reaches the same conclusion.
- omitted: the report does not take a position on the matter.
- discordant_unjustified: the report reaches a different conclusion without
  giving evidence or reasoning for the difference.
- discordant_justified_pending: the report reaches a different conclusion AND
  gives explicit evidence or reasoning for it. A human decides later whether
  the justification holds; your job is only to record that one was given.

For each item write one CSV row. The evidence_note quotes the report passage
that decided the verdict (no more than 25 words), or says "no passage".
Escape double quotes in the note by doubling them and wrap the note in double
quotes.

Output ONLY the CSV rows, no header, no commentary, every claim then every
conclusion, in the order given:

{{RUN_ID}},{{QUESTION_ID}},M3,<item_id>,<verdict>,gpt,"<evidence_note>"
{{RUN_ID}},{{QUESTION_ID}},M4,<item_id>,<verdict>,gpt,"<evidence_note>"

RESEARCH QUESTION: {{QUESTION}}

--- REPORT BEGIN ---
{{REPORT}}
--- REPORT END ---

--- CLAIMS BEGIN ---
{{CLAIMS}}
--- CLAIMS END ---

--- CONCLUSIONS BEGIN ---
{{CONCLUSIONS}}
--- CONCLUSIONS END ---
