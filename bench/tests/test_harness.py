import contextlib
import csv
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BENCH = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harness"
sys.path.insert(0, str(BENCH))

import collect
import fetch_sources
import judge_run
import make_batches
import sample_m1
from score import HEADER


OPERATIONS = "https://example.invalid/operations"
PILOT = "https://example.invalid/pilot"
COST = "https://example.invalid/cost"


class HarnessCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=BENCH / "tests")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = (FIXTURES / "report.md").read_text(encoding="utf-8")
        self.items = json.loads((FIXTURES / "items.json").read_text(encoding="utf-8"))
        self.checklist_path = BENCH / "questions" / "q0" / "checklist.v1.json"
        self.checklist = json.loads(self.checklist_path.read_text(encoding="utf-8"))

    def prepare_sources(self):
        with mock.patch.object(fetch_sources, "fetch_url", return_value=(404, b"Not found", "text/html")):
            return fetch_sources.fetch_sources(self.items, self.root / "sources", FIXTURES / "run")

    def prepare_batches(self, seed=1, max_source_chars=60000):
        return make_batches.make_batches(self.items, self.root / "sources", self.report,
                                         self.checklist, "R", "Q", self.root / "batches",
                                         max_source_chars=max_source_chars, seed=seed)


class SampleTests(HarnessCase):
    def test_seeded_sample_in_document_order(self):
        items = sample_m1.sample_items(self.report, n=3, seed=1)
        self.assertEqual([i["item_id"] for i in items], ["s.001", "s.002", "s.003"])
        self.assertEqual([i["sentence"].split(",")[0] for i in items], ["First", "Third", "Fifth"])
        self.assertEqual([i["labels"] for i in items], [["1"], ["2", "1"], ["3"]])
        self.assertEqual([i["urls"] for i in items], [[OPERATIONS], [PILOT, OPERATIONS], [COST]])
        for item in items:
            self.assertNotIn("[^", item["sentence"] + item["context"])
            self.assertEqual(item["sentence"], " ".join(item["sentence"].split()))
        self.assertEqual(items[0]["context"],
                         "An introductory sentence provides context. Third-party monitoring remains important.")
        self.assertTrue(items[1]["context"].startswith("Second,"))
        self.assertIn("Fourth,", items[1]["context"])
        self.assertEqual(items, sample_m1.sample_items(self.report, n=3, seed=1))

    def test_all_sentences_and_cli(self):
        out = self.root / "items.json"
        self.assertEqual(sample_m1.main([str(FIXTURES / "report.md"), "--out", str(out)]), 0)
        items = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 8)
        self.assertTrue(items[-1]["context"].endswith("A closing sentence provides context."))
        for item in items:
            self.assertFalse(item["sentence"].startswith(("- ", "* ", "1. ")))
            self.assertNotIn("ignored", item["labels"])
        self.assertEqual(sample_m1.sample_items(self.report, n=0), [])
        with self.assertRaises(ValueError):
            sample_m1.sample_items(self.report, n=-1)

    def test_missing_definition_and_missing_url_warn(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            items = sample_m1.sample_items("Only cited sentence[^missing][^empty].\n\n[^empty]: A book.")
        self.assertEqual(items[0]["urls"], ["", ""])
        self.assertEqual(items[0]["context"], "")
        self.assertIn("WARNING", errors.getvalue())
        self.assertIn("missing", errors.getvalue())
        self.assertIn("empty", errors.getvalue())

    def test_definition_continuations_are_not_sentences(self):
        body, definitions = sample_m1.parse_report(self.report)
        self.assertNotIn("Archived transport evidence", body)
        self.assertNotIn("See https://", body)
        self.assertIn("https://example.invalid/cost", definitions["3"])
        self.assertEqual(len(sample_m1.sample_items(self.report, n=100)), 8)


class FetchTests(HarnessCase):
    def test_html_text_and_cache(self):
        html = (FIXTURES / "page.html").read_bytes()
        with mock.patch.object(fetch_sources, "fetch_url", return_value=(200, html, "text/html; charset=utf-8")) as fetch:
            index = fetch_sources.fetch_sources(self.items[:1], self.root / "sources")
        fetch.assert_called_once_with(OPERATIONS)
        entry = index[OPERATIONS]
        text = Path(entry["path"]).read_text(encoding="utf-8")
        self.assertEqual(text, "Buses & cities\nElectric buses reduce local emissions.\n"
                              "Charging needs planning.\nCosts depend on local conditions.")
        self.assertEqual(entry["status"], "fetched")
        self.assertEqual(entry["reason"], "")
        self.assertEqual(entry["bytes"], len(text.encode("utf-8")))
        self.assertEqual(Path(entry["path"]).name, hashlib.sha1(OPERATIONS.encode()).hexdigest() + ".txt")
        with mock.patch.object(fetch_sources, "fetch_url", side_effect=AssertionError("cache ignored")) as fetch:
            self.assertEqual(fetch_sources.fetch_sources(self.items[:1], self.root / "sources"), index)
        fetch.assert_not_called()

    def test_archive_fallback_dead_and_rerun(self):
        with mock.patch.object(fetch_sources, "fetch_url", return_value=(404, b"missing", "text/html")) as fetch:
            index = fetch_sources.fetch_sources(self.items, self.root / "sources", FIXTURES / "run")
        fetch.assert_called_once_with(COST)
        for url, filename in [(OPERATIONS, "operations.txt"), (PILOT, "pilot.txt")]:
            self.assertEqual(index[url]["status"], "archived")
            self.assertEqual(Path(index[url]["path"]).read_bytes(),
                             (FIXTURES / "run" / "pages" / filename).read_bytes())
        self.assertEqual(index[COST]["status"], "dead")
        self.assertEqual(index[COST]["reason"], "http-404")
        self.assertEqual(index[COST]["bytes"], 0)
        self.assertTrue(Path(index[COST]["path"]).exists())
        with mock.patch.object(fetch_sources, "fetch_url") as fetch:
            self.assertEqual(fetch_sources.fetch_sources(self.items, self.root / "sources"), index)
        fetch.assert_not_called()

    def test_existing_absolute_archive_path(self):
        run = self.root / "run"
        run.mkdir()
        page = self.root / "absolute.txt"
        page.write_bytes(b"Archived content.\r\nSecond line.\r\n")
        (run / "results.json").write_text(json.dumps({"ledger": {"sources": [{"source": OPERATIONS}]},
                                                     "results": [{"page_file": str(page)}]}), encoding="utf-8")
        with mock.patch.object(fetch_sources, "fetch_url") as fetch:
            index = fetch_sources.fetch_sources(self.items[:1], self.root / "sources", run)
        fetch.assert_not_called()
        self.assertEqual(index[OPERATIONS]["status"], "archived")
        self.assertEqual(Path(index[OPERATIONS]["path"]).read_bytes(), page.read_bytes())

    def test_fetch_request_settings(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"hello"
        response.headers = {"Content-Type": "text/plain"}
        with mock.patch.object(fetch_sources.urllib.request, "urlopen", return_value=response) as opening:
            self.assertEqual(fetch_sources.fetch_url(OPERATIONS), (200, b"hello", "text/plain"))
        request = opening.call_args.args[0]
        self.assertEqual(request.full_url, OPERATIONS)
        self.assertEqual(request.get_header("User-agent"), "deeper-research-bench/0.1")
        self.assertEqual(opening.call_args.kwargs["timeout"], 30)

    def test_non_text_exception_and_pdf_without_converter(self):
        cases = [((200, b"image", "image/png"), "non-text-content-type"),
                 (OSError("offline"), "offline"),
                 ((200, b"pdf", "application/pdf"), "pdf-no-pdftotext")]
        for number, (response, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                options = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with mock.patch.object(fetch_sources, "fetch_url", **options), \
                     mock.patch.object(fetch_sources.shutil, "which", return_value=None):
                    index = fetch_sources.fetch_sources(self.items[:1], self.root / str(number))
                self.assertEqual(index[OPERATIONS]["status"], "dead")
                self.assertIn(reason, index[OPERATIONS]["reason"])

    def test_pdf_converter_and_text_charset(self):
        with mock.patch.object(fetch_sources.shutil, "which", return_value="/bin/pdftotext"), \
             mock.patch.object(fetch_sources.subprocess, "run", return_value=mock.Mock(stdout=b"PDF text")) as run:
            self.assertEqual(fetch_sources.decode_source(b"%PDF", "application/pdf"), "PDF text")
        self.assertEqual(run.call_args.args[0], ["/bin/pdftotext", "-layout", "-", "-"])
        self.assertEqual(run.call_args.kwargs["input"], b"%PDF")
        self.assertEqual(fetch_sources.decode_source(b"caf\xe9", "text/plain; charset=iso-8859-1"), "café")


class BatchTests(HarnessCase):
    def setUp(self):
        super().setUp()
        self.prepare_sources()

    def test_prompts_plants_and_manifest(self):
        manifest = self.prepare_batches()
        self.assertEqual(manifest["run_id"], "R")
        self.assertEqual(manifest["question_id"], "Q")
        self.assertEqual([b["file"] for b in manifest["batches"]],
                         ["m1-1.md", "m1-2.md", "m1-3.md", "m3m4.md"])
        with (self.root / "batches" / "plants.csv").open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, ["metric", "item_id", "expected_verdict"])
            plants = {(p["metric"], p["item_id"]): p["expected_verdict"] for p in reader}
        for k in (1, 2):
            for kind, expected in [("verbatim", "supported"), ("negated", "unsupported"), ("foreign", "unverifiable")]:
                self.assertEqual(plants["M1", f"plant.m1-{k}.{kind}"], expected)
        self.assertNotIn(("M1", "plant.m1-3.verbatim"), plants)
        self.assertNotIn(("M1", "plant.m1-3.negated"), plants)
        self.assertEqual(plants["M3", "plant.m3.verbatim"], "covered")
        self.assertEqual(plants["M3", "plant.m3.absent"], "absent")
        self.assertEqual(plants["M4", "plant.m4.verbatim"], "concordant")
        all_ids = set()
        for batch in manifest["batches"]:
            prompt = (self.root / "batches" / batch["file"]).read_text(encoding="utf-8")
            self.assertFalse(prompt.startswith("<!--"))
            self.assertNotIn("{{", prompt)
            self.assertEqual(re.findall(r"\[item_id=([^\]]+)\]", prompt), batch["item_ids"])
            all_ids.update(batch["item_ids"])
        self.assertTrue({key[1] for key in plants}.issubset(all_ids))
        self.assertIn("s.003", manifest["batches"][0]["item_ids"])
        self.assertIn("s.003", manifest["batches"][2]["item_ids"])
        dead = (self.root / "batches" / "m1-3.md").read_text(encoding="utf-8")
        self.assertIn("--- SOURCE TEXT BEGIN ---\nSOURCE-DEAD\n", dead)
        m3m4 = (self.root / "batches" / "m3m4.md").read_text(encoding="utf-8")
        for item in self.checklist["claims"] + self.checklist["conclusions"]:
            self.assertIn("[item_id=" + item["id"] + "]", m3m4)
        self.assertIn(make_batches.ABSENT_CLAIM, m3m4)
        self.assertIn(self.report, m3m4)
        self.assertIn("ACCEPTANCE: the report states this", m3m4)

    def test_verbatim_negated_foreign_plants(self):
        self.prepare_batches()
        prompt = (self.root / "batches" / "m1-1.md").read_text(encoding="utf-8")
        blocks = dict((item_id, (sentence, context)) for item_id, sentence, context in
                      re.findall(r"\[item_id=([^\]]+)\]\nSENTENCE: (.*?)\nCONTEXT: (.*?)(?=\n\n|\n---)",
                                 prompt, flags=re.DOTALL))
        original = (FIXTURES / "run" / "pages" / "operations.txt").read_text(encoding="utf-8")
        foreign = (FIXTURES / "run" / "pages" / "pilot.txt").read_text(encoding="utf-8")
        verbatim = blocks["plant.m1-1.verbatim"][0]
        self.assertIn(verbatim, original)
        self.assertTrue(12 <= len(verbatim.split()) <= 40)
        self.assertGreaterEqual(original.index(verbatim), .1 * len(original))
        self.assertLessEqual(original.index(verbatim) + len(verbatim), .9 * len(original))
        self.assertEqual(blocks["plant.m1-1.negated"][0],
                         "Contrary to what is sometimes stated, it is not the case that " + verbatim[0].lower() + verbatim[1:])
        self.assertIn(blocks["plant.m1-1.foreign"][0], foreign)
        self.assertNotIn(blocks["plant.m1-1.foreign"][0], original)
        for item_id, (sentence, context) in blocks.items():
            if item_id.startswith("plant."):
                self.assertEqual(sentence, context)

    def test_shuffle_and_reproducibility(self):
        plant_before_real = False
        for seed in range(1, 6):
            manifest = self.prepare_batches(seed=seed)
            ids = manifest["batches"][0]["item_ids"]
            plant_before_real |= min(i for i, item in enumerate(ids) if item.startswith("plant.")) < max(
                i for i, item in enumerate(ids) if item.startswith("s."))
        self.assertTrue(plant_before_real)
        self.prepare_batches(seed=1)
        before = {p.name: p.read_bytes() for p in (self.root / "batches").iterdir()}
        self.prepare_batches(seed=1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / "batches").iterdir()})

    def test_truncation_cli_and_short_sources(self):
        out = self.root / "batches"
        self.assertEqual(make_batches.main([
            "--items", str(FIXTURES / "items.json"), "--sources", str(self.root / "sources"),
            "--report", str(FIXTURES / "report.md"), "--checklist", str(self.checklist_path),
            "--run-id", "R", "--question-id", "Q", "--out", str(out), "--max-source-chars", "80"]), 0)
        prompt = (out / "m1-1.md").read_text(encoding="utf-8")
        source = (FIXTURES / "run" / "pages" / "operations.txt").read_text(encoding="utf-8")
        self.assertIn("--- SOURCE TEXT BEGIN ---\n" + source[:80] + "\n[TRUNCATED at 80 chars]\n", prompt)
        self.assertNotIn("[item_id=plant.m1-1.verbatim]", prompt)
        self.assertNotIn("[item_id=plant.m1-1.negated]", prompt)
        foreign = re.search(r"\[item_id=plant.m1-1.foreign\]\nSENTENCE: (.*?)\nCONTEXT:", prompt).group(1)
        other_source = (FIXTURES / "run" / "pages" / "pilot.txt").read_text(encoding="utf-8")
        self.assertIn(foreign, make_batches.source_sentences(other_source))

    def test_report_without_eligible_calibration_sentence_is_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "no 12–40 word sentence"):
            make_batches.make_batches(self.items, self.root / "sources", "Too short.", self.checklist,
                                      "R", "Q", self.root / "batches")


class CollectTests(HarnessCase):
    def run_collect(self, ids, text):
        manifest = {"run_id": "R", "question_id": "Q", "batches": [
            {"file": "m1-1.md", "metrics": ["M1"], "item_ids": ids}]}
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        outputs = self.root / "outputs"
        outputs.mkdir(exist_ok=True)
        if text is not None:
            (outputs / "m1-1.txt").write_text(text, encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = collect.main(["--manifest", str(path), "--outputs", str(outputs),
                                 "--out", str(self.root / "verdicts.csv")])
        with (self.root / "verdicts.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], HEADER)
        return code, rows[1:], stdout.getvalue(), stderr.getvalue()

    def test_tolerant_output_and_warnings(self):
        text = ('```csv\n' + ','.join(HEADER) + '\n\nnot valid csv\n'
                'R,Q,M1,s.001,supported,gpt,"quotes ""a source"", correctly"\n'
                'R,Q,M1,s.002,partial,gpt,"limited evidence"\n'
                'R,Q,M1,foreign,supported,gpt,"wrong item"\n'
                'another,Q,M1,s.003,supported,gpt,"wrong run"\n'
                'R,another,M1,s.003,supported,gpt,"wrong question"\n'
                'R,Q,M1,s.003,supported,gpt\n```\n')  # 6 fields: malformed, dropped
        code, rows, stdout, stderr = self.run_collect(["s.001", "s.002", "s.003"], text)
        self.assertEqual(code, 0)
        self.assertEqual([r[3] for r in rows], ["s.001", "s.002"])
        self.assertEqual(rows[0][-1], 'quotes "a source", correctly')
        self.assertIn("unknown item_id 'foreign'", stderr)
        self.assertIn("missing expected items: s.003", stderr)
        self.assertIn("Rows kept: 2", stdout)
        self.assertIn("m1-1.md: expected 3, got 2", stdout)

    def test_zero_rows_and_missing_output_fail(self):
        for text in (None, "```\nmalformed\n```\n"):
            with self.subTest(text=text):
                code, rows, _, stderr = self.run_collect(["s.001"], text)
                self.assertEqual(code, 1)
                self.assertEqual(rows, [])
                self.assertIn("missing expected items: s.001", stderr)

    def test_more_than_half_missing_and_duplicates(self):
        row = 'R,Q,M1,s.001,supported,gpt,"evidence"\n'
        code, rows, _, _ = self.run_collect(["s.001", "s.002", "s.003"], row * 3)
        self.assertEqual(code, 1)
        self.assertEqual(len(rows), 3)
        code, _, _, _ = self.run_collect(["s.001", "s.002"], row)
        self.assertEqual(code, 0)


class OrchestratorTests(HarnessCase):
    def arguments(self):
        return ["--report", str(FIXTURES / "report.md"), "--checklist", str(self.checklist_path),
                "--run-id", "R", "--question-id", "Q", "--out", str(self.root / "out"),
                "--run-dir", str(FIXTURES / "run"), "--n", "15", "--seed", "1"]

    def fake_judge(self, argv):
        options = dict(zip(argv[::2], argv[1::2]))
        self.assertEqual(options["--model"], "openai-codex/gpt-6-astra")
        self.assertEqual(options["--thinking"], "high")
        filename = Path(options["--prompt"]).name
        manifest = json.loads((self.root / "out" / "batches" / "manifest.json").read_text(encoding="utf-8"))
        batch = next(b for b in manifest["batches"] if b["file"] == filename)
        with Path(options["--out-text"]).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            for item in batch["item_ids"]:
                metric = "M1" if filename.startswith("m1-") else (
                    "M4" if item.startswith(("q0.k", "plant.m4")) else "M3")
                verdict = {"M1": "supported", "M3": "covered", "M4": "concordant"}[metric]
                writer.writerow(["R", "Q", metric, item, verdict, "gpt", "fixture evidence"])
        Path(options["--out-json"]).write_text('{"type":"text","text":"fixture"}\n', encoding="utf-8")
        return 0

    def test_dry_run_has_no_judge_calls(self):
        stdout = io.StringIO()
        with mock.patch.object(fetch_sources, "fetch_url", return_value=(404, b"", "text/html")), \
             mock.patch.object(judge_run.judge, "main") as judge, contextlib.redirect_stdout(stdout):
            self.assertEqual(judge_run.main(self.arguments() + ["--dry-run"]), 0)
        judge.assert_not_called()
        self.assertTrue((self.root / "out" / "items.json").exists())
        self.assertTrue((self.root / "out" / "sources" / "index.json").exists())
        self.assertTrue((self.root / "out" / "batches" / "manifest.json").exists())
        self.assertFalse((self.root / "out" / "verdicts.csv").exists())
        command = stdout.getvalue().splitlines()[-1]
        self.assertIn("score.py", command)
        for flag in ("--checklist", "--verdicts", "--plants", "--run-meta"):
            self.assertIn(flag, command)

    def test_calls_judge_sequentially_and_rerun_skips(self):
        with mock.patch.object(fetch_sources, "fetch_url", return_value=(404, b"", "text/html")), \
             mock.patch.object(judge_run.judge, "main", side_effect=self.fake_judge) as judge, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(judge_run.main(self.arguments()), 0)
            self.assertEqual(judge.call_count, 4)
            self.assertEqual([Path(c.args[0][1]).name for c in judge.call_args_list],
                             ["m1-1.md", "m1-2.md", "m1-3.md", "m3m4.md"])
            judge.reset_mock()
            self.assertEqual(judge_run.main(self.arguments()), 0)
            judge.assert_not_called()
        outputs = self.root / "out" / "judge-outputs"
        self.assertEqual(len(list(outputs.glob("*.txt"))), 4)
        self.assertEqual(len(list(outputs.glob("*.events.jsonl"))), 4)
        self.assertEqual(json.loads((outputs / "failures.json").read_text(encoding="utf-8")), {})

    def test_failure_is_recorded_and_not_retried(self):
        def fail_first(argv):
            if Path(argv[1]).name == "m1-1.md":
                return 1
            if Path(argv[1]).name == "m1-2.md":
                raise OSError("synthetic judge failure")
            return self.fake_judge(argv)

        with mock.patch.object(fetch_sources, "fetch_url", return_value=(404, b"", "text/html")), \
             mock.patch.object(judge_run.judge, "main", side_effect=fail_first) as judge, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(judge_run.main(self.arguments()), 1)
            self.assertEqual(judge.call_count, 4)
            judge.reset_mock()
            self.assertEqual(judge_run.main(self.arguments()), 1)
            judge.assert_not_called()
        failures = json.loads((self.root / "out" / "judge-outputs" / "failures.json").read_text(encoding="utf-8"))
        self.assertEqual(failures["m1-1.md"]["returncode"], 1)
        self.assertIn("synthetic judge failure", failures["m1-2.md"]["reason"])
        self.assertTrue((self.root / "out" / "judge-outputs" / "m3m4.txt").exists())


class ParseRowRepairTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("collect_mod", Path(__file__).resolve().parents[1] / "collect.py")
        self.collect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.collect)

    def test_repairs_one_missing_closing_quote(self):
        # Real judge slip (2026-09-14 calibration): note ends with `.""` not `."""`.
        line = 'r,q,M1,plant.m1-2.verbatim,supported,gpt,"The source states: ""Under packet conditions.""'
        row = self.collect.parse_row(line)
        self.assertEqual(row[3], "plant.m1-2.verbatim")
        self.assertEqual(row[6], 'The source states: "Under packet conditions."')

    def test_well_formed_line_unchanged(self):
        line = 'r,q,M1,s.001,partial,gpt,"He said ""no"" twice."'
        self.assertEqual(self.collect.parse_row(line)[6], 'He said "no" twice.')

    def test_hopeless_line_is_none(self):
        self.assertIsNone(self.collect.parse_row('"a,"b"c",d"'))

if __name__ == "__main__":
    unittest.main()
