#!/usr/bin/env python3
"""Post-run mechanical quote gate.

Re-greps every voted claim's evidence quote against the persisted page text in
{run_dir}/pages/ and compares the mechanical result with each vote's
quote_found field. Catches votes that credit a paraphrased quote as found, and
broken decoys (a decoy's fabricated quote must NOT be present on the page).
Missing quote_found fields are mismatches unless the vote verdict is "error".

Quotes are checked at two levels. STRICT is verbatim presence after
punctuation/whitespace normalization; LENIENT additionally collapses PDF
hyphenation artifacts ("verifi- cation" -> "verification") on both sides —
the dominant benign anomaly class for PDF-derived sources. Vote agreement and
the exit code are judged against LENIENT; strict-only misses are reported as
LENIENT-ONLY lines but do not fail the gate.

Usage: python3 check-quotes.py <run_dir>   (needs results.json + pages/)
Exit 0 = clean; exit 1 = mismatches found (tally always printed).
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

# Curly quotes, dashes, ligature-ish variants that differ between the page as
# persisted and the quote as the extractor re-typed it.
_PUNCT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
    "…": "...",
}


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for k, v in _PUNCT.items():
        text = text.replace(k, v)
    # Fetch tools persist pages as Markdown; a quote copies the link TEXT, not
    # the markup, so "[write-ahead log](wal.html)" must compare as "write-ahead log".
    # Extractors also drop or keep inline-code backticks and link brackets
    # inconsistently ("`visibility_timeout`", "[Redis transport has to emulate
    # it]"), so both markup characters are removed on both sides.
    text = _MD_LINK.sub(r"\1", text)
    text = text.replace("`", "").replace("[", "").replace("]", "")
    return re.sub(r"\s+", " ", text).strip()


def dehyphenate(text: str) -> str:
    """Collapse PDF line-break hyphenation left in normalized text.

    After normalize() a hyphenated line break survives as "word- rest";
    rejoining is safe for the quote-presence check (a genuine hyphenated
    compound is unaffected because it carries no space).
    """
    return re.sub(r"(?<=\w)- (?=\w)", "", text)


def quote_on_page(quote: str, page: str) -> str:
    """'strict', 'lenient', or 'absent' for the quote against the page.

    The page must arrive pre-normalized. Extractors splice discontiguous page
    fragments with '...'; treat each fragment as an independent verbatim
    requirement. Fragments too short to be evidence on their own are ignored —
    but shortness is measured in words AND characters: a code one-liner, URL,
    or identifier has few whitespace-separated words yet is highly specific,
    so a long fragment is kept regardless of its word count. 'lenient' means
    found only after dehyphenating both sides (PDF hyphenation artifacts).
    """
    normalized_quote = normalize(quote)
    fragments = [f.strip(" .,;:") for f in re.split(r"\.{3,}", normalized_quote)]
    fragments = [f for f in fragments if len(f.split()) > 3 or len(f) >= 20]
    if not fragments:
        fallback = normalized_quote.strip(" .,;:")
        if not fallback:
            return "absent"
        fragments = [fallback]
    if all(f in page for f in fragments):
        return "strict"
    lenient_page = dehyphenate(page)
    if all(dehyphenate(f) in lenient_page for f in fragments):
        return "lenient"
    return "absent"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    results = json.loads((run_dir / "results.json").read_text())

    mismatches = []          # (source_idx, kind, detail)
    lenient_only = []        # (source_idx, detail) — informational, not failing
    tally = {"votes_checked": 0, "agree": 0,
             "vote_said_found_page_disagrees": 0,
             "vote_said_missing_page_disagrees": 0,
             "votes_missing_quote_found": 0,
             "quotes_checked": 0, "quotes_strict": 0,
             "quotes_lenient_only": 0, "quotes_absent": 0,
             "quotes_short": 0,
             "decoys_checked": 0, "decoy_quote_reported_found": 0,
             "decoy_quotes_checked": 0, "decoy_quotes_on_page": 0,
             "decoy_quotes_unavailable": 0,
             "pages_missing": 0}

    for si, res in enumerate(results.get("results", [])):
        page_file = res.get("page_file") or ""
        page_path = Path(page_file)
        if not page_path.is_absolute():
            page_path = run_dir / page_file
        if page_file and not page_path.exists():
            # results.json records absolute paths; survive the run dir moving.
            page_path = run_dir / "pages" / Path(page_file).name
        if not page_file or not page_path.exists():
            if res.get("fetch_ok"):
                tally["pages_missing"] += 1
                mismatches.append((si, "page_missing", page_file or "<empty>"))
            continue
        page = normalize(page_path.read_text(errors="replace"))

        for ci, claim in enumerate(res.get("claims", [])):
            quote = claim.get("quote", "")
            normalized_quote = normalize(quote)
            candidates = [f.strip(" .,;:") for f in
                          re.split(r"\.{3,}", normalized_quote)]
            if (normalized_quote.strip(" .,;:") and not any(
                    len(f.split()) > 3 or len(f) >= 20 for f in candidates)):
                tally["quotes_short"] += 1
            level = quote_on_page(quote, page)
            found = level != "absent"
            tally["quotes_checked"] += 1
            tally["quotes_strict" if level == "strict" else
                  "quotes_lenient_only" if level == "lenient" else
                  "quotes_absent"] += 1
            if level == "lenient":
                lenient_only.append(
                    (si, f"claim {ci}: {claim.get('quote', '')[:100]!r}"))
            for vi, vote in enumerate(claim.get("votes", [])):
                if vote.get("verdict") == "error":
                    continue
                tally["votes_checked"] += 1
                if "quote_found" not in vote:
                    tally["votes_missing_quote_found"] += 1
                    mismatches.append(
                        (si, "vote_missing_quote_found",
                         f"claim {ci} vote {vi}: {quote[:100]!r}"))
                    continue
                if bool(vote["quote_found"]) == found:
                    tally["agree"] += 1
                elif vote["quote_found"]:
                    tally["vote_said_found_page_disagrees"] += 1
                    mismatches.append(
                        (si, "vote_found_but_absent",
                         f"claim {ci} vote {vi}: {claim.get('quote', '')[:100]!r}"))
                else:
                    tally["vote_said_missing_page_disagrees"] += 1
                    mismatches.append(
                        (si, "vote_missing_but_present",
                         f"claim {ci} vote {vi}: {claim.get('quote', '')[:100]!r}"))

        # Newer results persist the fabricated decoy quote, so grep it when
        # available. Older runs omit it and are tallied as unavailable. Every
        # decoy vote must independently report quote_found=false.
        cal = res.get("calibration")
        if cal:
            tally["decoys_checked"] += 1
            decoy_quote = cal.get("quote")
            if isinstance(decoy_quote, str) and decoy_quote.strip():
                tally["decoy_quotes_checked"] += 1
                decoy_level = quote_on_page(decoy_quote, page)
                if decoy_level != "absent":
                    tally["decoy_quotes_on_page"] += 1
                    mismatches.append(
                        (si, "decoy_quote_on_page", repr(decoy_quote[:100])))
            else:
                tally["decoy_quotes_unavailable"] += 1
            for vi, vote in enumerate(cal.get("votes", [])):
                if vote.get("quote_found"):
                    tally["decoy_quote_reported_found"] += 1
                    mismatches.append(
                        (si, "decoy_vote_quote_found",
                         f"vote {vi}: {str(cal.get('claim', ''))[:100]!r}"))

    print(json.dumps(tally, indent=2))
    for si, detail in lenient_only:
        print(f"LENIENT-ONLY s{si}: {detail}")
    for si, kind, detail in mismatches:
        print(f"MISMATCH s{si} {kind}: {detail}")
    if not mismatches:
        print("CLEAN: every vote's quote_found agrees with the persisted page "
              "(lenient level); every decoy vote reports quote_found=false.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
