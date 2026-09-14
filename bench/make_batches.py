#!/usr/bin/env python3
"""Fill source-attribution and checklist judge prompts with calibration plants."""

import argparse
import csv
import json
import random
import re
from pathlib import Path

from sample_m1 import SENTENCE_BREAK, clean_sentence, parse_report, report_sentences


PROMPTS = Path(__file__).resolve().parent / "prompts"
ABSENT_CLAIM = ("The report quantifies the tonnage of supplies moved over the Chilkoot Pass "
                "during the 1898 Klondike gold rush.")


def fill_template(name, values):
    template = (PROMPTS / name).read_text(encoding="utf-8")
    template = re.sub(r"\A\s*<!--.*?-->\s*", "", template, count=1, flags=re.DOTALL)
    # One pass: source/report text containing braces is data, not another template.
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match.group(1)], template)


def source_sentences(text, middle=False):
    """Return verbatim sentences; eligible plants lie wholly in the middle 80%."""
    sentences = []
    start = 0
    for boundary in list(SENTENCE_BREAK.finditer(text)) + [None]:
        end = boundary.start() if boundary else len(text)
        raw = text[start:end]
        sentence = raw.strip()
        left = start + len(raw) - len(raw.lstrip())
        right = end - len(raw) + len(raw.rstrip())
        if sentence and (not middle or (len(text) * .1 <= left and right <= len(text) * .9
                                        and 12 <= len(sentence.split()) <= 40)):
            sentences.append(sentence)
        if boundary:
            start = boundary.end()
    return sentences


def item_block(item):
    return f"[item_id={item['item_id']}]\nSENTENCE: {item['sentence']}\nCONTEXT: {item['context']}"


def claim_block(item):
    return (f"[item_id={item['id']}] kind={item['kind']}\n"
            f"CLAIM: {item['text']}\nACCEPTANCE: {item['acceptance']}")


def conclusion_block(item):
    return f"[item_id={item['id']}]\nCONCLUSION: {item['text']}"


def make_batches(items, sources, report, checklist, run_id, question_id, out,
                 max_source_chars=60000, seed=1):
    if max_source_chars < 0:
        raise ValueError("max_source_chars must be nonnegative")
    rng = random.Random(seed)
    sources, out = Path(sources), Path(out)
    index = json.loads((sources / "index.json").read_text(encoding="utf-8"))
    grouped = {}
    for item in items:
        for url in dict.fromkeys(item["urls"]):
            grouped.setdefault(url, []).append(item)
    texts, originals, dead, truncated = {}, {}, {}, {}
    for url in grouped:
        entry = index.get(url, {"status": "dead"})
        dead[url] = entry["status"] == "dead"
        if dead[url]:
            texts[url], originals[url], truncated[url] = "", "", False
            continue
        path = Path(entry["path"])
        if not path.is_absolute():
            path = sources / path
        text = path.read_text(encoding="utf-8")
        originals[url] = text
        truncated[url] = len(text) > max_source_chars
        texts[url] = text[:max_source_chars]
    # Supported plants must be whole original sentences visible in the prompt.
    candidates = {url: [sentence for sentence in source_sentences(text, middle=True)
                        if sentence in texts[url]] for url, text in originals.items()}
    body, _ = parse_report(report)
    report_candidates = [clean_sentence(s) for s in report_sentences(body)
                         if 12 <= len(clean_sentence(s).split()) <= 40]
    if not report_candidates:
        raise ValueError("report body has no 12–40 word sentence for M3/M4 calibration plants")

    out.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "question_id": question_id, "batches": []}
    plants = []
    common = {"RUN_ID": run_id, "QUESTION_ID": question_id}

    def add_plant(metric, item_id, expected):
        plants.append({"metric": metric, "item_id": item_id, "expected_verdict": expected})

    def save_batch(filename, metrics, item_ids, prompt):
        (out / filename).write_text(prompt, encoding="utf-8")
        manifest["batches"].append({"file": filename, "metrics": metrics, "item_ids": item_ids})

    for k, (url, real_items) in enumerate(grouped.items(), 1):
        batch_items = list(real_items)

        def add_m1(kind, sentence, expected):
            # Archived pages carry line breaks mid-sentence; the SENTENCE slot is one line.
            sentence = " ".join(sentence.split())
            item_id = f"plant.m1-{k}.{kind}"
            batch_items.append({"item_id": item_id, "sentence": sentence, "context": sentence})
            add_plant("M1", item_id, expected)

        if candidates[url] and not dead[url]:
            sentence = rng.choice(candidates[url])
            add_m1("verbatim", sentence, "supported")
            add_m1("negated", "Contrary to what is sometimes stated, it is not the case that "
                   + sentence[0].lower() + sentence[1:], "unsupported")
        foreign = [other for other in grouped if other != url and not dead[other] and originals[other].strip()]
        if foreign:
            other = rng.choice(foreign)
            sentence = rng.choice(candidates[other] or source_sentences(originals[other]))
            add_m1("foreign", sentence, "unverifiable")
        rng.shuffle(batch_items)
        source_text = "SOURCE-DEAD" if dead[url] else texts[url]
        if truncated[url]:
            source_text += f"\n[TRUNCATED at {max_source_chars} chars]"
        prompt = fill_template("m1-attribution.md", dict(common, SOURCE_URL=url, SOURCE_TEXT=source_text,
                               ITEMS="\n\n".join(item_block(item) for item in batch_items)))
        save_batch(f"m1-{k}.md", ["M1"], [item["item_id"] for item in batch_items], prompt)

    claims = list(checklist["claims"])
    conclusions = list(checklist["conclusions"])
    verbatim = rng.choice(report_candidates)
    another = rng.choice([s for s in report_candidates if s != verbatim] or report_candidates)
    claims.extend([
        {"id": "plant.m3.verbatim", "kind": "must-have", "text": verbatim,
         "acceptance": "the report states this"},
        {"id": "plant.m3.absent", "kind": "must-have", "text": ABSENT_CLAIM,
         "acceptance": "the report states this"},
    ])
    conclusions.append({"id": "plant.m4.verbatim", "text": another})
    add_plant("M3", "plant.m3.verbatim", "covered")
    add_plant("M3", "plant.m3.absent", "absent")
    add_plant("M4", "plant.m4.verbatim", "concordant")
    rng.shuffle(claims)
    rng.shuffle(conclusions)
    prompt = fill_template("m3-m4-checklist.md", dict(common, REPORT=report, QUESTION=checklist["question"],
                           CLAIMS="\n\n".join(claim_block(item) for item in claims),
                           CONCLUSIONS="\n\n".join(conclusion_block(item) for item in conclusions)))
    save_batch("m3m4.md", ["M3", "M4"], [item["id"] for item in claims + conclusions], prompt)
    with (out / "plants.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "item_id", "expected_verdict"])
        writer.writeheader()
        writer.writerows(plants)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--checklist", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-source-chars", type=int, default=60000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    if args.max_source_chars < 0:
        parser.error("--max-source-chars must be nonnegative")
    make_batches(json.loads(Path(args.items).read_text(encoding="utf-8")), args.sources,
                 Path(args.report).read_text(encoding="utf-8"),
                 json.loads(Path(args.checklist).read_text(encoding="utf-8")),
                 args.run_id, args.question_id, args.out, args.max_source_chars, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
