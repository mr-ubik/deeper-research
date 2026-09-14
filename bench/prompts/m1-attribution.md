<!--
M1 attribution judge prompt. One batch = ONE cited source and every sampled
sentence that cites it. The harness fills the placeholders:
  {{RUN_ID}} {{QUESTION_ID}} — copied into every output row
  {{SOURCE_URL}}            — the footnote's URL, verbatim
  {{SOURCE_TEXT}}           — the fetched page text (plain text, complete);
                              the literal string SOURCE-DEAD when the URL
                              could not be fetched
  {{ITEMS}}                 — one block per sampled sentence:
                              [item_id=s.014]
                              SENTENCE: <the sentence as it appears in the
                              blinded report, with its footnote marks removed>
                              CONTEXT: <the sentence before and after it>
Calibration plants are ordinary items whose item_id starts with "plant."; the
judge is never told which ones they are. Plant kinds the harness uses:
  a sentence copied verbatim from the source          -> expected supported
  a sentence stating the opposite of a source passage -> expected unsupported
  a sentence about a topic the source never mentions  -> expected unverifiable
-->

You are judging whether sentences from a research report are supported by the
source they cite. Judge ONLY from the source text below. Do not use your own
knowledge of the topic to fill gaps: a true sentence that the source does not
state is "unverifiable", not "supported".

Verdicts, one per sentence:

- supported: the source states the sentence's claim, with the same scope,
  numbers, and hedging. A paraphrase counts. A stronger claim than the source
  makes does not.
- partial: the source supports part of the sentence, or supports it with a
  weaker or narrower claim (the sentence drops a hedge, widens the scope,
  rounds a number, or adds a causal reading the source does not make).
- unsupported: the source contradicts the sentence, or the sentence attributes
  to the source something the source does not say and the difference is not a
  matter of scope or strength.
- unverifiable: the source does not address the sentence's subject at all.
- source_dead: the source text is the string SOURCE-DEAD.

A sentence that is authorial synthesis ("taken together, these suggest...")
with a citation is judged on the part that is attributed to the source.

For each item write one CSV row. The evidence_note is one sentence quoting the
source passage that decided the verdict (or "no passage" for unverifiable).
Quote no more than 25 words. Escape double quotes in the note by doubling them
and wrap the note in double quotes.

Output ONLY the CSV rows, no header, no commentary, one row per item, in the
order given:

{{RUN_ID}},{{QUESTION_ID}},M1,<item_id>,<verdict>,gpt,"<evidence_note>"

If the source text is SOURCE-DEAD, output source_dead for every item with the
note "source dead".

SOURCE URL: {{SOURCE_URL}}

--- SOURCE TEXT BEGIN ---
{{SOURCE_TEXT}}
--- SOURCE TEXT END ---

--- ITEMS BEGIN ---
{{ITEMS}}
--- ITEMS END ---
