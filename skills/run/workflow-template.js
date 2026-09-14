// deeper-research workflow template.
//
// This script runs on the Claude Code dynamic-workflow runtime (the same layer the
// Agent SDK exposes as the Workflow tool): the runtime executes it in an isolated
// environment and injects the orchestration globals used below —
//   agent(prompt, opts)  spawn one subagent, resolves to its (schema-validated) result
//   parallel(thunks)     run tasks concurrently, barrier until all settle
//   pipeline(items, ...) run each item through stages with NO barrier between stages
//   phase(title)         group subsequent agents in the progress display
//   log(msg)             emit a progress line to the user
//   args                 the value passed to the Workflow tool at launch (all config)
//
// The script itself has no filesystem or network access; agents do the reading,
// fetching, and writing. Vanilla JS only — no TypeScript syntax, and no
// Date.now()/Math.random()/new Date() (nondeterminism breaks workflow resume;
// timestamps arrive via args).
//
// DO NOT EDIT the copy of this file inside a run folder: it is frozen there as the
// run's reproducibility artifact. The invoking skill copies it verbatim and passes
// all per-run configuration through `args`:
//
//   {
//     question:     the research question (required)
//     runTag:       unique run id; namespaces this run's staged files (required)
//     runDir:       ABSOLUTE path to the run folder; report artifacts land here (required)
//     pagesDir:     ABSOLUTE path to the run's pages/ dir, already created (required)
//     runDate:      'YYYY-MM-DD' run date, used in bibliography entries (required)
//     pipelineVersion: deeper-research plugin version that produced this run, e.g.
//                   '0.2.0' — the launcher reads it from the plugin path or
//                   plugin.json ('' if unknown)
//     templateSha256: sha256 of the frozen template copy actually launched — pins
//                   the exact instrument bytes independent of version labels;
//                   the launcher computes it with sha256sum ('' if unknown)
//     decoys:       [{claim, quote}] known-false calibration claims (required, >= 1;
//                   crafted fresh per run — see the skill)
//     brief:        locked pre-run understanding from the interview ('' if none)
//     seedSources:  [{url, title, localPath}] user-provided grounding sources ([])
//     angles:       hardcoded search angles ([] -> a Scope agent derives them)
//     nAngles:      how many angles Scope should derive (when angles is [])
//     blocklist:    URL substrings to exclude from search results ([])
//     caps:         { fetchMin, fetchMax, r2Angles, fetchMinR2, fetchMaxR2,
//                     verifyClaimsPerSource, votesPerClaim }  (0 is honored)
//     retrievalOff: true = control run: no scope, search, fetch, or verify; the
//                   author writes from model memory alone and the tail is
//                   author-only. Exists for benchmark floors (default false)
//     sessionModel: informational — the model of the launching session, which
//                   runs every agent without an explicit model (scope, gap,
//                   author, review, adjudicate). Recorded, never used ('' ok)
//     workerModel:  model for search/fetch workers (default 'sonnet')
//     verifierModel: model casting verification votes (default 'haiku')
//     reviewer:     { type: 'claude', model: 'inherit'|<model>, label }
//                   | { type: 'cli', command, label, wrapperModel }
//                       command: ONE line containing the placeholder {prompt},
//                       which the relay replaces with the staged prompt file's
//                       absolute path, e.g.
//                         'pi -p --no-tools --no-session --no-context-files --no-skills --no-extensions --no-prompt-templates --thinking high --model openai-codex/gpt-5.6-sol @{prompt}'
//                         'codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-sol -c model_reasoning_effort="high" - < {prompt}'
//                       wrapperModel: the relay agent that stages the prompt and
//                       runs the CLI (default = workerModel; the external model
//                       does the reviewing, the relay is mechanical)
//                   | { type: 'codex-cli', command: <CLI prefix>, label, wrapperModel }
//                       legacy alias: command has no placeholder and gets
//                       ' - < {prompt}' appended
//   }
//
// Artifacts the tail agents write into runDir: unreviewed_report.md, review.md,
// final_report.md. The workflow never holds report text: agents write files and
// return short status objects. Everything else (ledger, tallies, calibration,
// methodology block, verification appendix) is carried in this script's return
// value; the orchestrating session persists results.json from it and runs the
// skill's scripts (assemble-report.py, check-report.py, check-quotes.py) to
// build report.md and gate the run (the workflow itself cannot write files).

export const meta = {
  name: 'deeper-research',
  description: 'Deep-research run: scoped search angles, gap-driven two-round retrieval with quality-adaptive caps, verbatim page archiving, ranked atomic claim extraction, page-grounded verification with mandatory decoy calibration, and a draft/adversarial-review/adjudicate synthesis tail with mechanical citation checks',
  phases: [
    { title: 'Scope', detail: 'derive search angles from the question + brief + seed sources (skipped when angles are hardcoded)' },
    { title: 'Search', detail: 'one search worker per angle (dr-search), then dedup, re-rank, and quality-adaptive cap' },
    { title: 'Fetch', detail: 'fetch each source, persist verbatim page text, extract ranked atomic claims + bibliographic metadata (dr-fetch)' },
    { title: 'Verify', detail: 'independent page-grounded votes per claim (dr-verify), with planted decoys measuring the verifier' },
    { title: 'Gap', detail: 'gap analysis of the round-1 ledger proposes targeted round-2 angles; retrieval repeats' },
    { title: 'Synthesize', detail: 'author drafts from the ledger, a separate context adversarially reviews, the adjudicator applies only ledger-supported findings' },
  ],
}

// ------------------------------------------------------------------ Config
// Everything comes from args; fail fast and loudly on anything unusable so a
// misconfigured launch dies here, not five agents in. A stringified args
// object (a common launcher slip) is parsed rather than rejected.
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
for (const k of ['question', 'runTag', 'runDir', 'pagesDir', 'runDate']) {
  if (!A[k] || typeof A[k] !== 'string') throw new Error(`args.${k} is required (string)`)
}
if (!Array.isArray(A.decoys) || !A.decoys.length) {
  // Decoy calibration is not optional: it is the standing measurement that makes
  // the verifier trusted. An unmeasured verifier is untrusted.
  throw new Error('args.decoys must be a non-empty array of {claim, quote} — craft fresh decoys per run')
}
const QUESTION = A.question
const RUN_TAG = A.runTag
const RUN_DIR = A.runDir
const PAGES_DIR = A.pagesDir
const RUN_DATE = A.runDate
const PIPELINE_VERSION = A.pipelineVersion || ''
const TEMPLATE_SHA256 = A.templateSha256 || ''
const BRIEF = A.brief || ''
const SEED_SOURCES = A.seedSources || []
const ANGLES = A.angles || []
const N_ANGLES = A.nAngles || 6
const BLOCKLIST = A.blocklist || []
const caps = A.caps || {}
// `??`, not `||`: a cap of 0 is a real setting (a benchmark floor run fetches
// nothing), not a request for the default.
const FETCH_MIN = caps.fetchMin ?? 3
const FETCH_MAX = caps.fetchMax ?? 6
const R2_ANGLES = caps.r2Angles ?? 2
const FETCH_MIN_R2 = caps.fetchMinR2 ?? 2
const FETCH_MAX_R2 = caps.fetchMaxR2 ?? 4
const VERIFY_CLAIMS_PER_SOURCE = caps.verifyClaimsPerSource ?? 4
const VOTES_PER_CLAIM = caps.votesPerClaim ?? 2
const RETRIEVAL_OFF = A.retrievalOff === true
if (!RETRIEVAL_OFF && !(Number.isInteger(VOTES_PER_CLAIM) && VOTES_PER_CLAIM >= 1)) {
  // A claim with zero votes would enter the ledger as "verified" with 0/0
  // support. Verification is the point; a run without votes is not a run.
  throw new Error('caps.votesPerClaim must be an integer >= 1 (use retrievalOff for a control run)')
}
const SESSION_MODEL = A.sessionModel || ''
const WORKER = A.workerModel || 'sonnet'
const VERIFIER = A.verifierModel || 'haiku'
// Reviewer normalization: 'codex-cli' is the legacy spelling of a 'cli'
// reviewer whose prompt goes to stdin. After this block REVIEWER.type is
// 'claude' or 'cli', and a 'cli' command always carries the {prompt} placeholder.
const REVIEWER_IN = A.reviewer || { type: 'claude', model: 'inherit' }
if ((REVIEWER_IN.type === 'codex-cli' || REVIEWER_IN.type === 'cli') &&
    (typeof REVIEWER_IN.command !== 'string' || !REVIEWER_IN.command.trim())) {
  throw new Error('args.reviewer.command is required (string) for a cli / codex-cli reviewer')
}
const REVIEWER = REVIEWER_IN.type === 'codex-cli'
  ? Object.assign({}, REVIEWER_IN, { type: 'cli', command: `${REVIEWER_IN.command} - < {prompt}` })
  : REVIEWER_IN
if (REVIEWER.type === 'cli') {
  if (!REVIEWER.command || !REVIEWER.command.includes('{prompt}')) {
    throw new Error("args.reviewer.command must be a single line containing the {prompt} placeholder (or use type 'codex-cli' with a bare CLI prefix)")
  }
  if (/[\r\n]/.test(REVIEWER.command)) throw new Error('args.reviewer.command must be a single line')
}
const REVIEWER_LABEL = REVIEWER.label ||
  (REVIEWER.type === 'cli' ? 'an external reviewer model' : 'an independent Claude reviewer')
const RELAY_MODEL = REVIEWER.wrapperModel || WORKER
const DECOY_CLAIMS = A.decoys
// Plugin-provided agent types are namespaced by the plugin name in the
// session's registry.
const T_SEARCH = 'deeper-research:dr-search'
const T_FETCH = 'deeper-research:dr-fetch'
const T_VERIFY = 'deeper-research:dr-verify'

// ------------------------------------------------------------------ Schemas
// Structured-output schemas: the runtime validates each agent's return against
// these, so downstream code never parses free text.
const SEARCH_SCHEMA = {
  type: 'object',
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          url: { type: 'string' },
          title: { type: 'string' },
          relevance: { type: 'string' },
        },
        required: ['url', 'title', 'relevance'],
      },
    },
  },
  required: ['results'],
}

const RANK_SCHEMA = {
  type: 'object',
  properties: {
    ranking: { type: 'array', items: { type: 'integer' } },
    high_quality_count: { type: 'integer' },
  },
  required: ['ranking', 'high_quality_count'],
}

const SCOPE_SCHEMA = {
  type: 'object',
  properties: {
    angles: { type: 'array', items: { type: 'string' } },
  },
  required: ['angles'],
}

const CLAIMS_SCHEMA = {
  type: 'object',
  properties: {
    fetch_ok: { type: 'boolean' },
    page_file: { type: 'string' },
    biblio: {
      type: 'object',
      properties: {
        authors: { type: 'array', items: { type: 'string' } },
        venue: { type: 'string' },
        year: { type: 'string' },
      },
      required: ['authors', 'venue', 'year'],
    },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          quote: { type: 'string' },
        },
        required: ['claim', 'quote'],
      },
    },
  },
  required: ['fetch_ok', 'page_file', 'biblio', 'claims'],
}

const BATCH_VOTES_SCHEMA = {
  type: 'object',
  properties: {
    votes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim_index: { type: 'integer' },
          vote_index: { type: 'integer' },
          verdict: { type: 'string', enum: ['supported', 'refuted', 'unverifiable', 'error'] },
          confidence: { type: 'number' },
          reasoning: { type: 'string' },
          quote_found: { type: 'boolean' },
        },
        // quote_found is required: a vote that omits it cannot be checked by the
        // post-run quote gate, and an uncheckable vote is worth nothing.
        required: ['claim_index', 'vote_index', 'verdict', 'confidence', 'reasoning', 'quote_found'],
      },
    },
  },
  required: ['votes'],
}

const GAP_SCHEMA = {
  type: 'object',
  properties: {
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          facet: { type: 'string' },
          why: { type: 'string' },
        },
        required: ['facet', 'why'],
      },
    },
    new_angles: { type: 'array', items: { type: 'string' } },
  },
  required: ['gaps', 'new_angles'],
}

// The synthesis tail returns STATUS, never text: each agent writes its file
// and reports that it did. Echoing a 30 KB report back through structured
// output doubled the most expensive output tokens of the run for text that
// was already on disk; the orchestrating session assembles the report from
// the files afterwards.
const WRITTEN_SCHEMA = {
  type: 'object',
  properties: {
    written: { type: 'boolean' },
    bytes: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['written', 'bytes', 'notes'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    review_ok: { type: 'boolean' },
    bytes: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['review_ok', 'bytes', 'notes'],
}

// ---------------------------------------------------------------- Search
// Dedup is global across ALL rounds and keyed CANONICALLY, not by raw URL string:
// the same document often appears under several renderings (arXiv /abs/, /pdf/,
// /html/), and treating them as distinct sources double-spends the fetch budget
// on duplicates.
function urlKey(u) {
  const m = u.match(/arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5})/)
  if (m) return 'arxiv:' + m[1]
  return u.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/+$/, '')
}
const seenUrls = new Set()
const allFound = []

// One round of search fan-out: one worker per angle, then dedup + blocklist +
// re-rank + cap. Re-ranking before the cap matters: without it the fetch budget
// goes to whatever was discovered first, an arbitrary selection at exactly the
// point where recall is decided. The cap is quality-adaptive: the ranker
// certifies how many candidates are genuinely high-quality and the fetch count
// follows that certification within [fetchMin, fetchMax].
async function searchRound(angles, roundLabel, fetchMin, fetchMax) {
  const batches = await parallel(angles.map((angle, i) => () =>
    agent(
      `Run 1-2 web searches on ONE angle of the research question "${QUESTION}".\n` +
      `Your angle: ${angle}\n\n` +
      `Return the 3 most relevant sources you find. Prefer primary sources over secondhand coverage — ` +
      `but "primary" depends on the angle: peer-reviewed/preprint papers for research findings, engineering ` +
      `blogs or postmortems from the teams that built the systems for practice claims, benchmark ` +
      `leaderboards/repos for evaluation claims, official docs or standards for specification claims. ` +
      `Vary query phrasing to reach the source types your angle needs; do not return 3 hits of the same ` +
      `modality when the angle spans several. Avoid news aggregators and SEO content farms. ` +
      (BLOCKLIST.length
        ? `Exclude any source whose URL contains "${BLOCKLIST.join('" or "')}", and any source that primarily ` +
          `summarizes or discusses content from those domains. `
        : '') +
      `For each source give url, title, and a one-line relevance note. ` +
      `If searches fail, return an empty results array.`,
      { label: `search:${roundLabel}:${i}`, phase: 'Search', agentType: T_SEARCH, model: WORKER, effort: 'low', schema: SEARCH_SCHEMA }
    )
  ))

  // Barrier justified: dedup + blocklist need the whole round's batches before ranking.
  const fresh = []
  for (const batch of batches.filter(Boolean)) {
    for (const r of batch.results) {
      if (!r.url || BLOCKLIST.some(b => r.url.includes(b))) continue
      if (seenUrls.has(urlKey(r.url))) continue
      seenUrls.add(urlKey(r.url))
      fresh.push(r)
      allFound.push(r)
    }
  }

  let picked
  let reranked = false
  let dropped = []
  let highQuality = null
  if (fresh.length > fetchMin) {
    const rankResult = await agent(
      `Rank candidate sources for the research question "${QUESTION}".\n\n` +
      `Below are ${fresh.length} sources found by parallel searches on different angles of the ` +
      `question. Between ${fetchMin} and ${Math.min(fetchMax, fresh.length)} of them will be ` +
      `fetched and read — how many depends on YOUR quality call — so the ranking decides coverage.\n\n` +
      fresh.map((s, i) => `[${i}] ${s.url}\n    title: ${s.title}\n    relevance: ${s.relevance}`).join('\n') +
      `\n\nRank ALL indices best-first by: (a) direct relevance to the research question, ` +
      `(b) primary literature over secondary commentary, (c) diversity — the fetched set together ` +
      `should cover as many distinct facets of the question as possible, so demote a source that ` +
      `duplicates a facet already covered by a better source above it. ` +
      `ALSO return high_quality_count: counting from the top of YOUR ranking, how many candidates ` +
      `you certify as genuinely high-quality for this question — primary, authoritative, ` +
      `substantive. Be honest: do not pad the count to fill the budget, and do not lowball it if ` +
      `the pool really is strong; only certified sources above the floor get fetched. ` +
      `Judge ONLY from the url/title/relevance text given; do not search or fetch anything. ` +
      `Return every index exactly once in the ranking array.`,
      { label: `rerank:${roundLabel}`, phase: 'Search', model: WORKER, effort: 'low', schema: RANK_SCHEMA }
    )
    // Sanitize the ranking defensively: keep the first occurrence of each valid
    // index, append anything the ranker omitted, and fall back to discovery
    // order (floor count) if ranking failed entirely. Drops are always logged —
    // a silent cap reads as "covered everything" when it didn't.
    const order = []
    const seenIdx = new Set()
    for (const i of ((rankResult && rankResult.ranking) || [])) {
      if (Number.isInteger(i) && i >= 0 && i < fresh.length && !seenIdx.has(i)) {
        seenIdx.add(i)
        order.push(i)
      }
    }
    for (let i = 0; i < fresh.length; i++) if (!seenIdx.has(i)) order.push(i)
    reranked = !!(rankResult && rankResult.ranking && rankResult.ranking.length)
    highQuality = reranked && Number.isInteger(rankResult.high_quality_count)
      ? Math.max(0, rankResult.high_quality_count) : null
    const take = reranked
      ? Math.min(fetchMax, Math.max(fetchMin, highQuality === null ? fetchMin : highQuality), fresh.length)
      : Math.min(fetchMin, fresh.length)
    picked = order.slice(0, take).map(i => fresh[i])
    dropped = order.slice(take).map(i => fresh[i].url)
    log(`Cap (${roundLabel}): fetching ${take} of ${fresh.length} new sources (${reranked ? `ranker certified ${highQuality} high-quality, bounds [${fetchMin}, ${fetchMax}]` : 'RERANK FAILED, floor count in discovery order'}); dropped: ${dropped.join(', ')}`)
  } else {
    picked = fresh.slice(0, fetchMax)
    dropped = fresh.slice(fetchMax).map(s => s.url)
    log(`Fetching ${picked.length} of ${fresh.length} new sources (${roundLabel}, at or below the floor, no re-rank)${dropped.length ? `; dropped by fetchMax: ${dropped.join(', ')}` : ''}`)
  }
  return { picked: picked, found: fresh.length, reranked: reranked, dropped: dropped, high_quality: highQuality }
}

// ------------------------------------------------------- Fetch -> Verify
// Verification is PAGE-GROUNDED: every vote reads the page text the fetch worker
// persisted and mechanically checks that the claim's supporting quote actually
// appears there. Without that grounding, a verifier shown a claim plus a
// fabricated quote tends to do entailment on the fabrication ("does the quote
// imply the claim?") instead of fact-checking against the source — grounding
// closes exactly that hole, and the planted decoys measure that it stays closed.
function votePrompt(batch, src, vi, pageFile) {
  const claimBlocks = batch.map((c, ci) =>
    `[claim_index=${ci}]\nCLAIM: ${c.claim}\nEVIDENCE (quote attributed to ${src.url}): ${c.quote}`
  ).join('\n\n')
  const pageBlock = pageFile
    ? `The full text of the source page is persisted at ${pageFile} — read it with the Read tool ` +
      `(use the Grep tool on that file for the quote checks) BEFORE judging any claim.\n` +
      `For each claim do BOTH checks and ground your verdict in them:\n` +
      `1. QUOTE CHECK (mechanical): search the page file for the claim's EVIDENCE quote (allow ` +
      `whitespace/markup differences). Report the result as quote_found. A quote absent from the ` +
      `page is strong evidence the claim was fabricated or misattributed.\n` +
      `2. SUPPORT CHECK: judge whether the ACTUAL PAGE TEXT supports the claim as stated (scope, ` +
      `hedging, and numbers included), and weigh it against your own knowledge for external plausibility.`
    : `No persisted page text is available for this source; assess each claim against its evidence ` +
      `quote and your own knowledge only, and set quote_found to false.`
  return (
    `You are an adversarial verifier. Actively look for reasons each claim could be wrong, but do ` +
    `not refute claims merely for being surprising. Judge each claim INDEPENDENTLY.\n\n` +
    pageBlock + '\n\n' +
    `CLAIMS TO VERIFY (${batch.length}):\n\n${claimBlocks}\n\n` +
    `Return in your structured output one vote per claim: claim_index as given above, ` +
    `vote_index=${vi} for every vote, verdict ("supported" | "refuted" | "unverifiable"), ` +
    `confidence (0..1), reasoning (one sentence), quote_found (true | false). ` +
    `Every claim_index from 0 to ${batch.length - 1} must appear exactly once.`
  )
}

// The votesPerClaim votes for a claim come from SEPARATE agent contexts (one
// agent per vote index), so votes are independent judgments, not one context
// repeating itself.
function runVotes(batch, src, si, pageFile) {
  return parallel(Array.from({ length: VOTES_PER_CLAIM }, (_, vi) => () =>
    agent(votePrompt(batch, src, vi, pageFile), {
      label: `votes s${si} v${vi} (${batch.length})`,
      phase: 'Verify',
      agentType: T_VERIFY,
      model: VERIFIER,
      effort: 'low',
      schema: BATCH_VOTES_SCHEMA,
    })
  )).then(parts => {
    const votes = []
    for (const p of parts.filter(Boolean)) for (const v of (p.votes || [])) votes.push(v)
    return { votes: votes }
  })
}

// arXiv /abs/ and /pdf/ renderings yield PDF-derived text with hyphenation and
// column-interleaving artifacts that break verbatim quote checking; /html/ is
// the rendering meant for machine reading. Only the FETCH TARGET is rewritten —
// src.url stays the canonical citation/dedup url.
function fetchTarget(u) {
  const m = u.match(/arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,5}(?:v\d+)?)/)
  return m ? 'https://arxiv.org/html/' + m[1] : u
}

// Fetch + extract + verify for one round's picked sources. pipeline(), not
// parallel(): each source flows fetch->verify independently, so a slow fetch
// never stalls another source's votes. The verify cap applies HERE, not at
// extraction — extraction is uncapped (ranked most->least central) because cost
// and variance live in the vote fan-out, not in reading; claims beyond the cap
// are carried as the ledger's "unverified" tail rather than dropped.
function fetchVerifyRound(picked, siBase, roundNo) {
  return pipeline(
    picked,
    (src, _item, i) => agent(
      (src.localPath
        ? `This is a user-provided SEED source: ${src.url} (title: "${src.title}"). An ` +
          `already-scraped copy exists at ${src.localPath} — Read that file with the Read tool ` +
          `instead of fetching; treat its document text as "the page" everywhere below (strip any ` +
          `scrape framing, access notes, or bibtex blocks that are not the document's own prose).\n`
        : fetchTarget(src.url) === src.url
          ? `Fetch this URL: ${src.url} (title: "${src.title}").\n`
          : `Fetch this URL: ${fetchTarget(src.url)} (title: "${src.title}") — it is the arXiv HTML ` +
            `rendering of ${src.url}. If it is unavailable or clearly broken (404, "HTML is not ` +
            `available", empty or truncated body), fall back to fetching ${src.url} instead.\n`) +
      `FIRST, persist the page (verification depends on this): write the complete readable ` +
      `text content of the fetched page (plain text, boilerplate/navigation stripped, but ALL substantive ` +
      `content — do not summarize or truncate) to the file ${PAGES_DIR}/s${siBase + i}.txt using the Write tool, ` +
      `and return that exact path as page_file. The persisted text must be the page's own words VERBATIM ` +
      `— never a paraphrase, reconstruction, or your notes on it. If your fetch tool returns processed or ` +
      `summarized content instead of the actual text, try fetching the raw page another way (e.g. curl and ` +
      `strip markup yourself); if you cannot obtain verbatim text at all, set fetch_ok=false and ` +
      `page_file to an empty string rather than persisting a paraphrase. If the fetch fails, return ` +
      `page_file as an empty string.\n` +
      `ALSO capture bibliographic metadata from the page for the bibliography: biblio.authors (author ` +
      `names exactly as listed on the page, [] if none listed), biblio.venue (journal, conference, or ` +
      `publishing site as the page names it, "" if unclear), biblio.year (publication year "YYYY", "" if ` +
      `not stated). Read these from the page only; never guess or infer them from the URL.\n` +
      `THEN extract the atomic, independently checkable claims from the page that are central to the research ` +
      `question "${QUESTION}". List them ordered from most to least central. Extract as many as the page ` +
      `genuinely supports — a dense paper might yield 6-8, a thin page 1-2. Do NOT pad with marginal claims ` +
      `to reach a count, and do NOT truncate genuinely central ones. Prefer specific, falsifiable claims ` +
      `(numbers, named results, direct findings) over vague summaries.\n` +
      `ATOMICITY rules (violations are the most common verification failure):\n` +
      `- One claim = ONE independently checkable statement. Never fuse a measurement with its ` +
      `interpretation: if the page reports numbers/results AND a causal or explanatory story about them, ` +
      `extract the finding and the interpretation as SEPARATE claims.\n` +
      `- Preserve the page's own epistemic strength. Correlational or benchmark-specific findings must ` +
      `stay so in your wording ("is associated with", "on benchmark X"); never strengthen hedged language ` +
      `into causal or universal claims.\n` +
      `- Numeric fidelity: claims containing numbers must carry the page's raw figures verbatim. Never ` +
      `compute, convert, or characterize a delta yourself — no percentage-points read off a relative %, ` +
      `no "majority"/"most" summarizing counts, no rounding like "~8" — unless the page states it in ` +
      `exactly those terms. If a derived reading matters, extract the raw numbers as one claim and the ` +
      `page's own derivation (if it makes one) as a separate claim.\n` +
      `For each claim include a verbatim supporting quote from the page: ONE contiguous passage of at ` +
      `least 15 words (shorter only when the page's own complete sentence is shorter) — never stitched ` +
      `fragments, never a clipped phrase too short to be checkable evidence. Quotes must be COPIED from the ` +
      `persisted file, not retyped from memory: before returning, mechanically check each quote against ` +
      `the file (e.g. grep -F); if one is not found verbatim, replace it with a passage copied from the ` +
      `file, or drop the claim if nothing on the page supports it. Set fetch_ok=false and claims=[] ` +
      `if the fetch fails or the page is unusable.`,
      { label: `fetch:s${siBase + i}`, phase: 'Fetch', agentType: T_FETCH, model: WORKER, effort: 'low', schema: CLAIMS_SCHEMA }
    ),
    (extracted, src, i) => {
      const si = siBase + i
      const allClaims = (extracted && extracted.fetch_ok ? extracted.claims : [])
      const claims = allClaims.slice(0, VERIFY_CLAIMS_PER_SOURCE)
      const pageFile = (extracted && extracted.page_file) || ''
      const biblio = (extracted && extracted.biblio) || null
      if (!pageFile && claims.length) {
        log(`No persisted page for ${src.url}; votes fall back to shallow (quote-blind) mode`)
      }
      if (allClaims.length > claims.length) {
        log(`Verify cap: ${src.url} yielded ${allClaims.length} claims, verifying top ${claims.length}, dropped: ${allClaims.slice(claims.length).map(c => c.claim.slice(0, 60)).join(' | ')}`)
      }
      if (!claims.length) {
        // Nothing to vote on: either the page yielded nothing, or the verify
        // cap is 0 — in which case every extracted claim is an unverified lead.
        log(allClaims.length ? `Verify cap 0: ${src.url} yielded ${allClaims.length} claims, all carried as unverified leads` : `No usable claims from ${src.url}`)
        return { source: src.url, title: src.title, round: roundNo, biblio: biblio, fetch_ok: !!(extracted && extracted.fetch_ok), page_file: pageFile, extracted_total: allClaims.length, claims: [], unverified: allClaims.map(c => ({ claim: c.claim, quote: c.quote })), calibration: null }
      }
      // One decoy is appended to each source's verify batch, round-robin by
      // GLOBAL source index (spans all rounds, so every decoy gets exercised).
      // The decoy rides at claim_index === claims.length; its votes are tallied
      // separately below and NEVER enter the ledger, synthesis, or review.
      const decoy = DECOY_CLAIMS.length ? DECOY_CLAIMS[si % DECOY_CLAIMS.length] : null
      const batch = decoy ? claims.concat([decoy]) : claims
      return runVotes(batch, src, si, pageFile).then(res => ({
        source: src.url,
        title: src.title,
        round: roundNo,
        biblio: biblio,
        fetch_ok: true,
        page_file: pageFile,
        extracted_total: allClaims.length,
        unverified: allClaims.slice(claims.length).map(c => ({ claim: c.claim, quote: c.quote })),
        claims: claims.map((c, ci) => ({
          claim: c.claim,
          quote: c.quote,
          votes: ((res && res.votes) || [])
            .filter(v => v.claim_index === ci)
            .sort((a, b) => a.vote_index - b.vote_index)
            .map(v => ({ verdict: v.verdict, confidence: v.confidence, reasoning: v.reasoning, quote_found: v.quote_found })),
        })),
        // The decoy's fabricated quote is persisted so the post-run quote gate
        // can grep it against the page: a hit means the decoy was not false.
        calibration: decoy ? {
          claim: decoy.claim,
          quote: decoy.quote,
          votes: ((res && res.votes) || [])
            .filter(v => v.claim_index === claims.length)
            .sort((a, b) => a.vote_index - b.vote_index)
            .map(v => ({ verdict: v.verdict, confidence: v.confidence, reasoning: v.reasoning, quote_found: v.quote_found })),
        } : null,
      }))
    }
  )
}

// ---------------------------------------------------------------- Scope
// Exactly one deterministic angle-derivation per run: either the launcher
// hardcoded the angles (removes a variance source for controlled comparisons),
// or one scoping agent derives them from question + brief + seeds. The angles
// are the unit of search fan-out, so their quality bounds recall.
let runAngles = ANGLES
if (RETRIEVAL_OFF) {
  log('Retrieval OFF: control run — no scope, search, fetch, or verification; the author writes from memory')
} else if (!runAngles.length) {
  phase('Scope')
  const scope = await agent(
    `You are the scoping agent of a deep-research pipeline. Derive the search angles for this ` +
    `research question:\n"${QUESTION}"\n\n` +
    (BRIEF
      ? `The locked pre-run BRIEF (user-approved constraints, audience, and non-goals; the angle set ` +
        `must respect it — treat its non-goals as exclusions):\n--- BRIEF BEGIN ---\n${BRIEF}\n--- BRIEF END ---\n\n`
      : '') +
    (SEED_SOURCES.length
      ? `The user provided ${SEED_SOURCES.length} grounding seed source(s):\n` +
        SEED_SOURCES.map(s => `- "${s.title}" — ${s.url}${s.localPath ? ` (read the local copy: ${s.localPath})` : ''}`).join('\n') +
        `\nRead them with the Read tool BEFORE deciding the angles: the angle set must jointly ` +
        `cover both the question's own pillars AND the themes the seed source(s) treat as central. ` +
        `Naming specific systems or papers mentioned by the seeds in angle text is allowed and useful.\n\n`
      : '\n') +
    `Return exactly ${N_ANGLES} search angles. Each angle must be: self-contained (a search agent ` +
    `sees ONLY the angle text — never refer to "the post" or "the seed"); focused on one facet ` +
    `(angles must not overlap); phrased to retrieve primary sources; and ending with "Source ` +
    `modality most needed: ..." naming the kind of source that best evidences that facet (papers / ` +
    `engineering postmortems from the teams that built the systems / benchmark and evaluation ` +
    `reports / official documentation). Jointly the angles must cover the question's own major ` +
    `pillars — decompose the question yourself — plus any additional pillars the brief or the seed ` +
    `source(s) establish.`,
    { label: 'scope', phase: 'Scope', schema: SCOPE_SCHEMA }
  )
  runAngles = ((scope && scope.angles) || []).slice(0, N_ANGLES)
  if (!runAngles.length) {
    log('SCOPE FAILED: no angles generated and none hardcoded — aborting run')
    throw new Error('scope stage produced no angles')
  }
  log(`Scope: ${runAngles.length} angles generated from question + ${SEED_SOURCES.length} seed source(s)`)
}

// ------------------------------------------------- Seeds (round 0) + Round 1
// Seed sources are user-provided grounding: ingested ahead of round 1, verified
// and citable like any other source (round tag 0). Their urls enter the dedup
// set FIRST so searches re-surfacing them dedup away instead of double-fetching.
const seedPicked = SEED_SOURCES.map(s => ({
  url: s.url, title: s.title, relevance: 'user-provided seed source', localPath: s.localPath || '',
}))
for (const s of seedPicked) { seenUrls.add(urlKey(s.url)); allFound.push(s) }
const EMPTY_ROUND = { picked: [], found: 0, reranked: false, dropped: [], high_quality: null }
let results0 = []
let r1 = EMPTY_ROUND
let results1 = []
if (!RETRIEVAL_OFF) {
  results0 = seedPicked.length ? await fetchVerifyRound(seedPicked, 0, 0) : []
  phase('Search')
  r1 = await searchRound(runAngles, 'r1', FETCH_MIN, FETCH_MAX)
  results1 = await fetchVerifyRound(r1.picked, seedPicked.length, 1)
}

// ---------------------------------------------------- Gap analysis + Round 2
// Recall, not precision, is usually the binding constraint on survey quality;
// multi-round retrieval driven by identified gaps is what makes research
// "deep" rather than one search pass. The gap agent reads everything verified
// so far and proposes a few sharp, targeted round-2 angles; failure or an
// empty proposal degrades gracefully to a single round.
function gapPrompt(roundResults, dropped) {
  const summary = roundResults.filter(Boolean).map((r, i) => {
    const claimLines = r.claims.map(c => {
      const sup = c.votes.filter(v => v.verdict === 'supported').length
      return `    - [${sup}/${c.votes.length} supported] ${c.claim}`
    }).join('\n')
    const leadLines = r.unverified.map(u => `    - (unverified lead) ${u.claim}`).join('\n')
    return `[S${i}] ${r.title} — ${r.source} (fetch_ok=${r.fetch_ok})\n${claimLines}${leadLines ? '\n' + leadLines : ''}`
  }).join('\n')
  return (
    'You are the gap analyst in a deep-research pipeline. Round 1 of evidence-gathering is done; ' +
    'your job is to decide what a targeted second retrieval round should look for.\n\n' +
    `Research question:\n"${QUESTION}"\n\n` +
    `Round-1 search angles:\n${runAngles.map(a => '- ' + a).join('\n')}\n\n` +
    `Evidence so far (seed sources first, then round-1; verified claims and unverified leads per source):\n${summary}\n\n` +
    (dropped.length ? `Sources found in round 1 but not fetched (cap): ${dropped.join(', ')}\n\n` : '') +
    'Identify the most important GAPS: facets of the research question with no or thin evidence, ' +
    'pillars resting on a single source, claims that need independent corroboration, and missing ' +
    'source modalities (papers vs engineering practice vs benchmarks/evaluations vs official docs). ' +
    `Then write up to ${R2_ANGLES} NEW search angles targeted at those gaps. Each angle must be ` +
    'self-contained (a search agent sees only the angle text, not this analysis), must not ' +
    'duplicate a round-1 angle, and should name the source modality it most needs. ' +
    'Fewer, sharper angles beat broad ones. If round 1 already covers the question well, return ' +
    'fewer angles or none.'
  )
}

let gapAnalysis = null
let r2 = EMPTY_ROUND
let results2 = []
const preGapResults = results0.filter(Boolean).concat(results1.filter(Boolean))
if (!RETRIEVAL_OFF && R2_ANGLES > 0 && preGapResults.length) {
  phase('Gap')
  gapAnalysis = await agent(gapPrompt(preGapResults, r1.dropped), {
    label: 'gap-analysis',
    phase: 'Gap',
    schema: GAP_SCHEMA,
  })
  const newAngles = ((gapAnalysis && gapAnalysis.new_angles) || []).slice(0, R2_ANGLES)
  if (newAngles.length) {
    log(`Gap analysis: ${((gapAnalysis && gapAnalysis.gaps) || []).length} gaps -> ${newAngles.length} round-2 angles`)
    r2 = await searchRound(newAngles, 'r2', FETCH_MIN_R2, FETCH_MAX_R2)
    if (r2.picked.length) {
      results2 = await fetchVerifyRound(r2.picked, seedPicked.length + r1.picked.length, 2)
    } else {
      log('Round 2 search found no new sources')
    }
  } else {
    log('Gap analysis proposed no new angles; running single-round')
  }
} else if (R2_ANGLES > 0 && !RETRIEVAL_OFF) {
  log('No seed or round-1 results; skipping gap analysis and round 2')
}
const gapAngles = ((gapAnalysis && gapAnalysis.new_angles) || []).slice(0, R2_ANGLES)

// ------------------------------------------------------------- Tally
const flat = preGapResults.concat((results2 || []).filter(Boolean))
let totalClaims = 0
let totalVotes = 0
const voteCounts = { supported: 0, refuted: 0, unverifiable: 0, error: 0 }
for (const srcRes of flat) {
  for (const c of srcRes.claims) {
    totalClaims += 1
    for (const v of c.votes) {
      totalVotes += 1
      if (voteCounts[v.verdict] !== undefined) voteCounts[v.verdict] += 1
    }
  }
}

// Calibration tally — decoy votes only, kept out of the main counts and the
// ledger. Detection levels: STRICT = the decoy was refuted; SOFT = refuted or
// unverifiable; a "supported" vote on a decoy means the verifier was fooled.
// A verifier that gets fooled by planted-false claims is credulous, and its
// "supported" verdicts on real claims are worth proportionally less — this
// tally is what makes the run's verification trustworthy, or visibly not.
const calCounts = { supported: 0, refuted: 0, unverifiable: 0, error: 0 }
const calDetails = []
for (const srcRes of flat) {
  if (!srcRes.calibration) continue
  calDetails.push({ source: srcRes.source, claim: srcRes.calibration.claim, quote: srcRes.calibration.quote || '', votes: srcRes.calibration.votes })
  for (const v of srcRes.calibration.votes) {
    if (calCounts[v.verdict] !== undefined) calCounts[v.verdict] += 1
  }
}
const calVoteTotal = calCounts.supported + calCounts.refuted + calCounts.unverifiable + calCounts.error
const calibration = {
  decoys_configured: DECOY_CLAIMS.length,
  total_decoy_votes: calVoteTotal,
  vote_counts: calCounts,
  strict_detection_rate: calVoteTotal ? calCounts.refuted / calVoteTotal : null,
  soft_detection_rate: calVoteTotal ? (calCounts.refuted + calCounts.unverifiable) / calVoteTotal : null,
  details: calDetails,
}
log(`Calibration: ${calVoteTotal} decoy votes, strict detection ${calCounts.refuted}/${calVoteTotal}, fooled(supported) ${calCounts.supported}/${calVoteTotal}`)
log(`Done verifying: ${flat.length} sources (${results0.filter(Boolean).length} seed + ${results1.filter(Boolean).length} r1 + ${(results2 || []).filter(Boolean).length} r2), ${totalClaims} claims, ${totalVotes} ${VERIFIER} votes (${JSON.stringify(voteCounts)})`)

const tally = { total_claims: totalClaims, total_votes: totalVotes, vote_counts: voteCounts }

// ------------------------------------------------------------- Ledger
// The ledger is the run's structured evidence record and the ONLY evidence base
// synthesis may draw from. Decoys are stripped before it is built — a report
// citing a planted-false claim would be contamination. Every source carries a
// stable citation key S{i}; reports cite by key, and the bibliography is
// mechanically checked against these urls after synthesis.
const ledger = {
  question: QUESTION,
  caps: { fetch_min: FETCH_MIN, fetch_max: FETCH_MAX, fetch_min_r2: FETCH_MIN_R2, fetch_max_r2: FETCH_MAX_R2, r2_angles: R2_ANGLES, seeds: SEED_SOURCES.length, verifier: VERIFIER, verify_claims_per_source: VERIFY_CLAIMS_PER_SOURCE, votes_per_claim: VOTES_PER_CLAIM, extraction: 'uncapped, ranked by centrality' },
  sources: flat.map((r, i) => ({
    key: 'S' + i,
    source: r.source,
    title: r.title,
    round: r.round,
    biblio: r.biblio,
    fetch_ok: r.fetch_ok,
    extracted_total: r.extracted_total,
    claims: r.claims,
    unverified: r.unverified,
  })),
  tally: tally,
}
const ledgerJson = JSON.stringify(ledger)

// --------------------------------------------- Methodology (mechanical)
// Built by plain JS from run config + measured tallies. The synthesis agents
// must include it verbatim and may not edit its numbers or wording: the
// pipeline's measured procedure is part of the report's credibility, and a
// model paraphrasing its own audit trail would defeat the point.
function pct(x) { return x === null ? 'n/a' : Math.round(x * 100) + '%' }
const methodologyMd = [
  'This report was produced by an automated multi-stage research pipeline (deeper-research' +
  (PIPELINE_VERSION ? ` v${PIPELINE_VERSION}` : '') +
  (TEMPLATE_SHA256 ? `; template sha256 ${TEMPLATE_SHA256.slice(0, 12)}` : '') +
  '). Procedure and measured parameters for this run:',
  '',
  RETRIEVAL_OFF
    ? `- **Grounding**: none. No source was ingested${SEED_SOURCES.length ? ` (${SEED_SOURCES.length} seed source${SEED_SOURCES.length === 1 ? ' was' : 's were'} listed but not read)` : ''}.`
    : SEED_SOURCES.length
    ? `- **Grounding**: the query was grounded in ${SEED_SOURCES.length} user-provided seed ` +
      `source${SEED_SOURCES.length === 1 ? '' : 's'}, ingested, claim-extracted, and verified ` +
      `like every other source, and used to scope the retrieval.`
    : '- **Grounding**: no user-provided seed sources; scope derives from the question alone.',
  RETRIEVAL_OFF
    ? '- **Retrieval**: none. This is a retrieval-off control run: no search, fetch, extraction, ' +
      'or verification was performed. The text rests on the authoring model\'s memory alone, and ' +
      'its citations are unverified.'
    : `- **Retrieval, round 1**: ${runAngles.length} independent search angles ` +
      `(${ANGLES.length ? 'fixed for this run' : 'derived by a scoping pass from the question and seed material'}) ` +
      `were queried in parallel; ${r1.found} unique sources were found after deduplication and ` +
      `blocklisting and ranked for relevance, primary-source quality, and facet diversity` +
      (r1.high_quality === null
        ? `; ${r1.picked.length} were fetched in full.`
        : `; the ranker certified ${r1.high_quality} candidates as high-quality and ` +
          `${r1.picked.length} were fetched in full (quality-adaptive budget, bounds ` +
          `${FETCH_MIN}–${FETCH_MAX}).`),
  RETRIEVAL_OFF ? null : gapAngles.length
    ? `- **Retrieval, round 2 (gap-driven)**: an analysis of the evidence so far identified ` +
      `${((gapAnalysis && gapAnalysis.gaps) || []).length} coverage gaps and generated ` +
      `${gapAngles.length} targeted follow-up angle${gapAngles.length === 1 ? '' : 's'}; ` +
      `${r2.found} further unique sources were found and ${r2.picked.length} were fetched` +
      (r2.high_quality === null ? '.' : ` (${r2.high_quality} certified high-quality, bounds ${FETCH_MIN_R2}–${FETCH_MAX_R2}).`)
    : '- **Retrieval, round 2**: not run (no gap-driven angles were generated for this run).',
  RETRIEVAL_OFF ? null :
  `- **Extraction**: from each fetched page, atomic claims were extracted (uncapped, ordered by ` +
  `centrality) under fidelity rules — one checkable statement per claim, the page's own hedging ` +
  `preserved, numeric figures carried verbatim, and every supporting quote mechanically checked ` +
  `against the archived page text.`,
  RETRIEVAL_OFF ? null :
  `- **Verification**: the top ${VERIFY_CLAIMS_PER_SOURCE} claims per source each received ` +
  `${VOTES_PER_CLAIM} independent adversarial votes (verifier model: ${VERIFIER}), each vote ` +
  `grounded in the archived page text with a mechanical quote-presence check. ` +
  `This run: ${totalClaims} claims, ${totalVotes} votes (${voteCounts.supported} supported, ` +
  `${voteCounts.refuted} refuted, ${voteCounts.unverifiable} unverifiable, ${voteCounts.error} error).`,
  // Every detection rate carries its denominator: a percentage over a handful
  // of votes reads very differently from one over forty.
  RETRIEVAL_OFF ? null :
  `- **Verifier calibration**: ${calibration.decoys_configured} known-false decoy claims with ` +
  `fabricated quotes were planted among the verify batches (excluded from all evidence). ` +
  `Detection this run over ${calVoteTotal} decoy votes: strict (refuted) ` +
  `${pct(calibration.strict_detection_rate)} (${calCounts.refuted}/${calVoteTotal}), soft ` +
  `(refuted or unverifiable) ${pct(calibration.soft_detection_rate)} ` +
  `(${calCounts.refuted + calCounts.unverifiable}/${calVoteTotal}); ` +
  `${calCounts.supported}/${calVoteTotal} decoy votes were fooled.`,
  RETRIEVAL_OFF
    ? '- **Synthesis**: the report was written by the authoring model from memory, without ' +
      'adversarial review or mechanical citation validation.'
    : `- **Synthesis**: the report was drafted from the evidence ledger and submitted for adversarial ` +
      `review by ${REVIEWER_LABEL} in a separate context; where the review completed, each finding ` +
      `was adjudicated against the evidence before revision (the run record states whether this is ` +
      `the revised or the unreviewed version). Citations were mechanically validated against the ` +
      `source registry.`,
  '',
  RETRIEVAL_OFF
    ? 'Citation conventions: sources are cited as Markdown footnotes from the authoring model\'s ' +
      'memory; none was retrieved or verified.'
    : 'Citation conventions: sources are cited as Markdown footnotes, one footnote per source, ' +
      'with the bibliography entry in the footnote definition. A citation marks where a statement ' +
      'comes from, not how well it was verified: the prose hedges statements that rest on ' +
      'unverified leads, split votes, or a quote the verifier could not locate, and Appendix A ' +
      'lists every claim with its verdicts. Substantive statements without a citation are ' +
      'authorial synthesis.',
].filter(line => line !== null).join('\n')

// ------------------------------------------------ Synthesis rules (shared)
// Citations say WHERE a statement comes from (a Markdown footnote per source);
// PROSE says how well it is verified (hedging that matches the ledger status);
// the ABSENCE of a footnote on a substantive sentence signals authorial
// judgment. The reviewer polices hedging against the ledger, and the post-run
// check-report.py script validates the footnote wiring against the ledger.
const SYNTHESIS_RULES =
  'Grounding and status rules (MANDATORY):\n' +
  '- Your ONLY evidence base is the ledger. Never add outside facts as evidence.\n' +
  '- Citation form (mechanically checked downstream): GitHub-style Markdown footnotes. Put a ' +
  'footnote reference like [^3] immediately after every substantive factual statement drawn from ' +
  'the ledger. ONE footnote per source: number footnotes in order of first citation, and reuse the ' +
  'same number every later time you cite that source. Several sources on one statement: ' +
  '[^2][^5], never [^2, 5]. Footnote references carry NO status marks of any kind.\n' +
  '- Status is carried by prose, not by citation form. A statement resting on a claim that ' +
  `received ${VOTES_PER_CLAIM}/${VOTES_PER_CLAIM} supported votes may be stated plainly. A statement resting on ` +
  'an unverified lead (a claim from the unverified tail), on a claim whose votes disagreed or ' +
  'failed, or on a claim whose quote the verifier did not locate (quote_found=false) MUST be ' +
  'hedged in the sentence itself ("one source reports, uncorroborated here, that…", "a claim the ' +
  'evidence review could not confirm holds that…"), stating what the verification accepted and ' +
  'rejected. Claims whose votes were refuted may be used only to discuss the refutation itself, ' +
  'with the disagreement stated in prose.\n' +
  '- Your own inference, cross-source synthesis, or design recommendation carries NO footnote: ' +
  'in this report an uncited substantive sentence explicitly signals authorial judgment. Never ' +
  'attach a footnote to your own inference, and never leave a ledger-derived fact uncited.\n' +
  '- Register: formal survey prose throughout. No first person ("I", "my", "we recommend"). No ' +
  'pipeline jargon in body prose — "ledger", "votes", "extraction", "quote_found" belong ' +
  'only in the Methodology section. Express epistemic strength through precise hedging ' +
  '("one study reports…", "a practitioner account attributes…", "this remains uncorroborated") ' +
  'rather than status tags.\n' +
  '- No absolutes ("never", "always", "requires", "guarantees") built on correlational or ' +
  'single-benchmark evidence. Keep benchmark-bounded findings bounded ("on benchmark X", ' +
  '"in the evaluated systems"). Preserve the hedges the ledger claims carry.\n' +
  '- Multiple ledger claims restating one underlying result are ONE piece of evidence; do not ' +
  'present them as independent corroboration.\n' +
  '- Numbers measured on different models, benchmarks, or settings must not be juxtaposed as if ' +
  'directly comparable without saying so.\n' +
  '- Include ledger material that contradicts or complicates your narrative.\n' +
  '- Footnote definitions go at the very END of the document, one per cited source, in numeric ' +
  'order, no heading above them, format: ' +
  '"[^3]: {authors} ({year}). {title}. {venue}. {url} (accessed ' + RUN_DATE + ')" — authors from ' +
  'the ledger biblio field ("First Author et al." beyond three names; omit the authors/year/venue ' +
  'parts gracefully when the ledger biblio is empty), and append ", fetch failed" after the date ' +
  'where the ledger marks fetch_ok=false. Copy the title VERBATIM from the ledger "title" field and ' +
  'the url VERBATIM and COMPLETE from the ledger "source" field — the url is the key the ' +
  'mechanical check joins on. Every referenced ' +
  'footnote has exactly one definition; no definitions for sources you never cited; no two ' +
  'definitions for one source.\n'

const REPORT_STRUCTURE =
  'Structure (MANDATORY):\n' +
  '- Executive summary that OPENS with a ranked "what matters most" — the reader must get the ' +
  'prioritized answer before any caveat. Discipline must not bury the lede.\n' +
  '- Immediately after the executive summary: a "## Methodology" section containing EXACTLY the ' +
  'text of the METHODOLOGY BLOCK provided with this task, verbatim — do not edit its numbers or ' +
  'wording.\n' +
  '- Body sections organized by the major facets of the question (they will usually mirror the ' +
  'search angles); order them by importance to the answer.\n' +
  '- "## Systems compared": when two or more concrete systems, tools, or approaches appear in the ' +
  'evidence, a comparison table — rows = systems, columns = approach, headline result (with its ' +
  'benchmark named in the cell), and evidence status — followed by a short "Comparability" note ' +
  'stating explicitly which numbers must NOT be read head-to-head (different benchmarks, ' +
  'backbones, or metric suites). Omit the whole section if fewer than two systems appear.\n' +
  '- Where the question calls for criteria or recommendations: a distilled list of measurable ' +
  'criteria, each with its evidence basis in parentheses, using the citation conventions.\n' +
  '- Limitations of the evidence base, including which parts of the question the evidence ' +
  'under-covers.\n' +
  '- The footnote definitions last, as specified above. Do NOT write a "Sources" or "References" ' +
  'section and do NOT write an appendix — a verification appendix is attached mechanically after ' +
  'authoring.\n'

const REVIEW_CRITERIA =
  'The report claims to: ground every factual statement in the evidence ledger; cite sources as ' +
  'Markdown footnotes (one footnote per source, definitions at the end copying title/url verbatim ' +
  'from the ledger); carry NO footnote on authorial interpretation; hedge, in the sentence itself, ' +
  `every statement that rests on less than ${VOTES_PER_CLAIM}/${VOTES_PER_CLAIM} supported votes (unverified-tail claims, ` +
  'split or failed votes, quote_found=false) and state disagreements where votes were refuted; ' +
  'include a verbatim Methodology block; include a "## Systems compared" table with an explicit ' +
  'comparability note when two or more systems appear; and use formal survey register (no first ' +
  'person, no pipeline jargon in body prose).\n\n' +
  'Review adversarially for: (1) grounding violations — outside knowledge smuggled in as evidence, ' +
  'or ledger-derived facts left uncited; (2) status errors — a statement stated plainly whose ' +
  'ledger claim lacks full supported votes, a hedge that overstates or understates what the votes ' +
  'said, refuted or disputed claims used without stating the disagreement, miscounted votes, ' +
  'misstated numbers; (3) overreach — absolutes or causal language stronger than the ledger ' +
  'warrants, restated results counted as independent corroboration, authorial judgment written as ' +
  'if evidenced; (4) cherry-picking — ledger material that complicates the narrative but was ' +
  'omitted; (5) citation errors — a footnote whose source\'s ledger claims do not support the ' +
  'statement it is attached to, a footnote reference with no definition or a definition never ' +
  'referenced, a definition whose title/url differ from the ledger, two definitions for one ' +
  'source; (6) internal inconsistencies; (7) genre and structure — Methodology block missing or ' +
  'edited, comparison table missing or lacking its comparability note, register violations ' +
  '(first person, jargon in body prose), does it answer the question, are the criteria usable.\n\n' +
  'NOT a finding: the absence of "Appendix A" (the per-claim verification ledger the Methodology ' +
  'block refers to). That appendix is attached mechanically AFTER review and adjudication; the ' +
  'draft must not contain one, and a draft that does contain an appendix is the fault.\n\n' +
  'For every finding: quote the offending passage, state the category, cite the ledger evidence, ' +
  'rate severity (critical/major/minor). Do not pad with trivia; say briefly where the report is ' +
  'sound. End with an overall verdict (faithful / partially faithful / unfaithful) and the 3 most ' +
  'important fixes.'

const REVISE_RULES =
  'Adjudicate every review finding against the ledger (ground truth). The reviewer can overreach ' +
  'too: apply a fix only if the ledger supports the finding; where you reject a finding, leave the ' +
  'passage as is — no note needed. Keep the mandatory structure, register, footnote-citation, and ' +
  'hedging rules; the Methodology section stays verbatim; the ranked "what matters most" answer ' +
  'stays up front — do NOT let the revision bury the lede. Never add an appendix, ' +
  'a "Sources" section, or any per-claim verdict listing: the verification appendix is attached ' +
  'mechanically after you finish, and a review finding that asks for one is rejected.'

const LEDGER_SHAPE =
  'Per source the ledger holds: a citation key, url ("source"), title, retrieval round, biblio ' +
  'metadata (authors/venue/year), verified claims (each with a verbatim quote and adversarial ' +
  'votes), and an "unverified" tail of claims extracted beyond the verify cap.'

const LEDGER_BLOCK = '--- LEDGER BEGIN ---\n' + ledgerJson + '\n--- LEDGER END ---'
const METHODOLOGY_BLOCK = '--- METHODOLOGY BEGIN ---\n' + methodologyMd + '\n--- METHODOLOGY END ---'

// ------------------------------------ Synthesize: draft -> review -> adjudicate
// Three separate contexts on purpose. The author and the adjudicator work FOR
// the report; the reviewer works AGAINST it from a fresh context — same-model
// cross-context review reliably catches real status errors, and a second model
// family (a 'cli' reviewer) adds blind-spot diversity when configured. The
// adjudicator, not the reviewer, decides what gets applied: reviewers
// overreach, and a finding is applied only when the ledger supports it.
//
// Every tail agent WRITES its artifact to disk and returns status only (see
// WRITTEN_SCHEMA); later agents Read earlier artifacts from disk. The workflow
// never holds report text.
phase('Synthesize')
const DRAFT_PATH = `${RUN_DIR}/unreviewed_report.md`
const REVIEW_PATH = `${RUN_DIR}/review.md`
const FINAL_PATH = `${RUN_DIR}/final_report.md`
let draft = null
let review = null
let reviewOk = false
let final = null
const draftOk = () => !!(draft && draft.written && draft.bytes > 0)
const finalOk = () => !!(final && final.written && final.bytes > 0)

if (RETRIEVAL_OFF) {
  // Control run: author-only, from memory. Same structure rules, no ledger; the
  // Methodology block states exactly what was (not) done, and the rest of the
  // tail is skipped — a review against no evidence would measure nothing.
  draft = await agent(
    'You are the author in a deep-research pipeline running in RETRIEVAL-OFF control mode: no ' +
    'sources were retrieved, so you write from your own knowledge alone. Do NOT run git commands, ' +
    'and do NOT search, fetch, or read anything.\n\n' +
    'The METHODOLOGY BLOCK for the mandatory "## Methodology" section is between the METHODOLOGY ' +
    'BEGIN/END markers at the bottom (markers excluded).\n\n' +
    `Write a synthesis report in Markdown answering:\n"${QUESTION}"\n\n` +
    (BRIEF ? 'Honor the locked pre-run BRIEF (audience, register, non-goals):\n--- BRIEF BEGIN ---\n' + BRIEF + '\n--- BRIEF END ---\n\n' : '') +
    'Rules (MANDATORY):\n' +
    '- Cite with GitHub-style Markdown footnotes: [^n] inline after each substantive factual ' +
    'statement, ONE footnote per source, numbered in order of first citation and reused for later ' +
    'citations of that source; definitions at the very END of the document, format ' +
    '"[^n]: {authors} ({year}). {title}. {venue}. {url}", naming only sources you believe really ' +
    'exist. Never invent a source to fill a footnote — leave the statement uncited instead.\n' +
    '- Hedge in the sentence itself every statement you are not sure of. Formal survey register, no ' +
    'first person, no absolutes built on thin evidence.\n' +
    REPORT_STRUCTURE + '\n' +
    `Write the complete report to ${DRAFT_PATH} with the Write tool (overwrite any existing ` +
    'content). Return in your structured output: written=true and bytes=the size of the file you ' +
    'wrote (written=false, bytes=0 if you could not), and notes (anomalies, one line each; empty ' +
    'string if none). Do NOT return the report text.\n\n' +
    METHODOLOGY_BLOCK,
    { label: 'author (retrieval off)', phase: 'Synthesize', schema: WRITTEN_SCHEMA }
  )
  if (!draftOk()) log('Author wrote no report (retrieval-off control run)')
} else if (flat.length) {
  draft = await agent(
    'You are the author in a deep-research pipeline: draft a synthesis report from an evidence ' +
    'ledger. Do NOT run git commands.\n\n' +
    'The ledger is between the LEDGER BEGIN/END markers at the bottom. ' + LEDGER_SHAPE + '\n\n' +
    'The METHODOLOGY BLOCK for the mandatory "## Methodology" section is between the METHODOLOGY ' +
    'BEGIN/END markers at the bottom (markers excluded).\n\n' +
    `Write a synthesis report in Markdown answering:\n"${QUESTION}"\n\n` +
    (BRIEF ? 'Honor the locked pre-run BRIEF (audience, register, non-goals):\n--- BRIEF BEGIN ---\n' + BRIEF + '\n--- BRIEF END ---\n\n' : '') +
    SYNTHESIS_RULES + '\n' + REPORT_STRUCTURE + '\n' +
    `Write the complete draft to ${DRAFT_PATH} with the Write tool (overwrite any existing ` +
    'content from a previous attempt of this run — never reuse it).\n\n' +
    'Return in your structured output: written=true and bytes=the size of the file you wrote ' +
    '(written=false, bytes=0 if you could not), and notes (anomalies, one line each; empty string ' +
    'if none). Do NOT return the draft text.\n\n' +
    LEDGER_BLOCK + '\n\n' + METHODOLOGY_BLOCK,
    { label: 'author', phase: 'Synthesize', schema: WRITTEN_SCHEMA }
  )
  if (!draftOk()) log('Author wrote no draft; no report')
} else {
  log('No sources survived verification; skipping synthesis')
}

if (draftOk() && !RETRIEVAL_OFF) {
  const reviewTask =
    'You are an adversarial reviewer in a deep-research pipeline. Find genuine faults in a ' +
    'synthesis report by checking it against the evidence ledger it claims to be derived from. ' +
    'You did not write this report; your job is to break it, fairly.\n\n' +
    `The report answers the research question:\n"${QUESTION}"\n\n` +
    REVIEW_CRITERIA + '\n\n' +
    // The archived pages let a tool-equipped reviewer settle a doubt at the
    // source instead of at the ledger's summary of it.
    `Archived page text for every source is under ${PAGES_DIR} (s{i}.txt corresponds to ledger ` +
    'key S{i}). If you have file tools and a statement\'s support is in doubt, check the page ' +
    'before calling it a status error.'
  if (REVIEWER.type === 'cli') {
    // External-model review through a command-line tool (pi, codex, ...). The
    // invariants for this call are load-bearing: permission allow rules are
    // PREFIX rules, and an unmatched command from a background agent is not
    // denied — it silently runs in a no-network sandbox where the CLI produces
    // nothing. Hence: single line, starts with the configured command, prompt
    // staged in a file and passed by PATH (never "$(cat file)": large prompts
    // exceed Linux's ~128 KiB per-argument limit and die with exit 127), stdout
    // redirected straight into review.md, one Bash call, never retried.
    const promptPath = `${RUN_DIR}/review-prompt-${RUN_TAG}.txt`
    // Paths are single-quoted: a run dir with a space would otherwise split the
    // command. The shell strips the quotes, so `@'/path'` reaches pi as `@/path`.
    const command = REVIEWER.command.split('{prompt}').join(`'${promptPath}'`) + ` > '${REVIEW_PATH}' 2>/dev/null`
    review = await agent(
      'You are a relay: obtain an adversarial review of a report from an external reviewer model ' +
      'via a command-line tool. Do NOT run git commands. Do NOT review the report yourself.\n\n' +
      `(a) Read the draft at ${DRAFT_PATH} with the Read tool. Then write ONE file, ${promptPath}, ` +
      'with the Write tool (overwrite any existing content) containing, in this order: the text ' +
      'between the REVIEW-PROMPT BEGIN/END markers below (markers excluded); a line ' +
      '"--- DRAFT BEGIN ---"; the draft EXACTLY as read; a line "--- DRAFT END ---"; and finally ' +
      'the line: "Output ONLY the review in Markdown. If you cannot complete this, say so ' +
      'explicitly and state what you inspected."\n' +
      `(b) Run this as ONE Bash tool call with timeout 600000 ms:\n${command}\n` +
      'CRITICAL: the command must stay a SINGLE LINE exactly as given — no cd, echo, variables, ' +
      'heredocs, no combining with && or ; or |, and no "$(cat ...)". It may take several ' +
      'minutes; NEVER retry it, even on error or empty output.\n' +
      `(c) The command wrote its output to ${REVIEW_PATH}. Check that file with the Read tool. If ` +
      'it holds a review, return review_ok=true, bytes=its size, notes="". If it is empty, holds ' +
      'only an error message, or the command was denied, overwrite it with "REVIEW-ERROR: " plus ' +
      'what happened and return review_ok=false, bytes=0, notes=the reason.\n\n' +
      '--- REVIEW-PROMPT BEGIN ---\n' +
      reviewTask + '\n\n' +
      'The evidence ledger (ground truth) and the report under review follow.\n\n' +
      LEDGER_BLOCK + '\n' +
      '--- REVIEW-PROMPT END ---',
      // The relay is mechanical (stage file, one Bash call, check a file) — it
      // never inherits the main-loop model; the external model does the review.
      { label: `${REVIEWER.command.startsWith('codex') ? '[codex]' : '[cli]'} review`, phase: 'Synthesize',
        schema: REVIEW_SCHEMA, model: RELAY_MODEL, effort: 'low' }
    )
  } else {
    // Default: a fresh-context Claude reviewer. Separate context is the point —
    // it never saw the author's reasoning, only the ledger and the draft.
    const opts = { label: 'review', phase: 'Synthesize', schema: REVIEW_SCHEMA }
    if (REVIEWER.model && REVIEWER.model !== 'inherit') opts.model = REVIEWER.model
    review = await agent(
      reviewTask + '\n\n' +
      `Read the draft under review at ${DRAFT_PATH} with the Read tool. The ledger is between the ` +
      'LEDGER BEGIN/END markers at the bottom. ' + LEDGER_SHAPE + '\n\n' +
      `Write the complete review to ${REVIEW_PATH} with the Write tool (overwrite any existing ` +
      'content) and return review_ok=true, bytes=its size, and notes for anomalies (empty string ' +
      'if none). Do NOT return the review text. If you cannot complete the review, write ' +
      '"REVIEW-ERROR: " plus the reason to that file and return review_ok=false, bytes=0, notes=the ' +
      'reason.\n\n' +
      LEDGER_BLOCK,
      opts
    )
  }
  reviewOk = !!(review && review.review_ok && review.bytes > 0)
  if (!reviewOk) log(`Review unavailable (${review && review.notes ? review.notes : 'no details'}); the unreviewed draft is the canonical report`)
}

if (draftOk() && reviewOk) {
  final = await agent(
    'You are the adjudicator in a deep-research pipeline: revise a draft report by incorporating ' +
    'an adversarial review of it. Do NOT run git commands.\n\n' +
    REVISE_RULES + '\n\n' +
    'The ledger is between the LEDGER BEGIN/END markers at the bottom. ' + LEDGER_SHAPE + '\n' +
    `Read the draft at ${DRAFT_PATH} and the review at ${REVIEW_PATH} with the Read tool.\n\n` +
    `Write the complete final report to ${FINAL_PATH} with the Write tool (overwrite any existing ` +
    'content) and return written=true, bytes=its size, and notes listing each review finding you ' +
    'REJECTED and why, one line each (empty string if you applied everything). Do NOT return the ' +
    'report text.\n\n' +
    LEDGER_BLOCK,
    { label: 'adjudicate', phase: 'Synthesize', schema: WRITTEN_SCHEMA }
  )
  if (!finalOk()) log('Adjudicator wrote no report; the unreviewed draft is the canonical report')
}

// Which file the orchestrating session's assemble-report.py will promote to
// report.md. Recorded here so the run record and the file on disk agree.
const reportSource = finalOk() ? 'final' : draftOk() ? 'draft' : 'none'
if (reportSource === 'none') log('No report produced')

// ------------------------------------ Verification appendix (mechanical)
// Returned as a string; assemble-report.py appends it to the canonical
// report.md (the authored files on disk stay as authored). Per-claim verdicts
// live here instead of as inline status tags in prose, keeping the body
// readable while every claim stays auditable. check-report.py validates the
// footnote wiring and the Methodology block against this run record.
const appendixMd = RETRIEVAL_OFF ? '' : [
  '## Appendix A: Verification ledger',
  '',
  `Per-claim verification detail. Each verified claim received ${VOTES_PER_CLAIM} independent ` +
  'adversarial votes grounded in the archived page text ("quote located" = the supporting quote ' +
  'was mechanically found in the archived page). Unverified leads were extracted but not voted on.',
  '',
].concat(ledger.sources.map(s => {
  const head = `### ${s.key} — ${s.title} (${s.round === 0 ? 'user-provided seed' : 'round ' + s.round}${s.fetch_ok ? '' : ', fetch failed'})`
  const claimLines = s.claims.map((c, j) => {
    const verdicts = c.votes.map(v => `${v.verdict} ${v.confidence}`).join(' / ')
    const located = c.votes.filter(v => v.quote_found).length
    return `- **${s.key}.C${j}** [${verdicts}; quote located ${located}/${c.votes.length}] — ${c.claim}`
  })
  const leadLines = s.unverified.map((u, j) => `- **${s.key}.U${j}** [unverified lead] — ${u.claim}`)
  return [head, ''].concat(claimLines).concat(leadLines).join('\n')
})).join('\n\n')

// The full run record. The orchestrating session persists results.json (this
// whole object) and then runs assemble-report.py (report.md, report_plain.md),
// check-report.py, and check-quotes.py against the run folder.
return {
  question: QUESTION,
  blocklist: BLOCKLIST,
  run_tag: RUN_TAG,
  run_dir: RUN_DIR,
  pipeline: { version: PIPELINE_VERSION, template_sha256: TEMPLATE_SHA256 },
  retrieval_off: RETRIEVAL_OFF,
  caps: { fetch_min: FETCH_MIN, fetch_max: FETCH_MAX, fetch_min_r2: FETCH_MIN_R2, fetch_max_r2: FETCH_MAX_R2, r2_angles: R2_ANGLES, seeds: SEED_SOURCES.length, verifier: VERIFIER, verify_claims_per_source: VERIFY_CLAIMS_PER_SOURCE, votes_per_claim: VOTES_PER_CLAIM, extraction: 'uncapped, ranked by centrality' },
  models: {
    session: SESSION_MODEL,
    worker: WORKER,
    verifier: VERIFIER,
    reviewer: REVIEWER.type === 'cli' ? `cli:${REVIEWER_LABEL}` : `claude:${REVIEWER.model || 'inherit'}`,
    reviewer_command: REVIEWER.type === 'cli' ? REVIEWER.command : '',
    relay: REVIEWER.type === 'cli' ? RELAY_MODEL : '',
  },
  rounds: {
    r0: { seeds: seedPicked.map(s => s.url) },
    r1: { angles: RETRIEVAL_OFF ? [] : runAngles, angles_source: RETRIEVAL_OFF ? 'skipped' : ANGLES.length ? 'hardcoded' : 'scope-generated', unique_found: r1.found, high_quality: r1.high_quality, fetched: r1.picked.map(s => s.url), reranked: r1.reranked },
    r2: { angles: gapAngles, unique_found: r2.found, high_quality: r2.high_quality, fetched: r2.picked.map(s => s.url), reranked: r2.reranked },
  },
  gap_analysis: gapAnalysis,
  search_unique_sources: allFound.map(s => s.url),
  fetched: seedPicked.concat(r1.picked, r2.picked).map(s => s.url),
  results: flat,
  tally: tally,
  calibration: calibration,
  ledger: ledger,
  methodology: methodologyMd,
  appendix: appendixMd,
  synthesis: {
    draft_written: draftOk(),
    draft_bytes: draft ? draft.bytes : 0,
    review_ok: reviewOk,
    review_bytes: review ? review.bytes : 0,
    final_written: finalOk(),
    final_bytes: final ? final.bytes : 0,
    notes: [draft && draft.notes, review && review.notes, final && final.notes].filter(Boolean).join(' | '),
  },
  report_source: reportSource,
  report_files: { draft: DRAFT_PATH, review: REVIEW_PATH, final: FINAL_PATH },
}
