import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quotes = load("check-quotes")
reports = load("check-report")
assemble = load("assemble-report")


class QuoteTests(unittest.TestCase):
    def run_gate(self, results, pages):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pages").mkdir()
            (root / "results.json").write_text(json.dumps({"results": results}))
            for name, text in pages.items():
                (root / "pages" / name).write_text(text)
            old = sys.argv
            sys.argv = ["check-quotes.py", str(root)]
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    code = quotes.main()
            finally:
                sys.argv = old
            return code, out.getvalue(), json.JSONDecoder().raw_decode(out.getvalue())[0]

    @staticmethod
    def source(page="s0.txt", quote="The verified statement has enough words.",
               found=True, votes=None, calibration=None, fetch_ok=True):
        if votes is None:
            votes = [{"verdict": "supported", "quote_found": found}]
        value = {"page_file": f"pages/{page}", "fetch_ok": fetch_ok,
                 "claims": [{"quote": quote, "votes": votes}]}
        if calibration is not None:
            value["calibration"] = calibration
        return value

    def test_clean_two_sources(self):
        # 2 sources x 2 claims x 2 votes = 8 agreements; two absent decoys.
        results = []
        pages = {}
        for i in range(2):
            text = "Alpha evidence has enough words here. Beta evidence also has enough words."
            pages[f"s{i}.txt"] = text
            results.append({"page_file": f"pages/s{i}.txt", "fetch_ok": True,
                "claims": [
                    {"quote": "Alpha evidence has enough words here", "votes": [{"quote_found": True}] * 2},
                    {"quote": "Beta evidence also has enough words", "votes": [{"quote_found": True}] * 2}],
                "calibration": {"quote": "Fabricated absent decoy quotation", "votes": [{"quote_found": False}]}})
        code, _, tally = self.run_gate(results, pages)
        self.assertEqual(code, 0)
        self.assertEqual(tally["agree"], 8)
        self.assertEqual(tally["votes_checked"], 8)
        self.assertEqual(tally["decoy_quotes_checked"], 2)
        self.assertEqual(tally["decoy_quotes_on_page"], 0)

    def test_vote_disagreements(self):
        code, out, _ = self.run_gate([self.source(found=True)], {"s0.txt": "unrelated"})
        self.assertEqual(code, 1); self.assertIn("vote_found_but_absent", out)
        code, out, _ = self.run_gate([self.source(found=False)], {"s0.txt": "The verified statement has enough words."})
        self.assertEqual(code, 1); self.assertIn("vote_missing_but_present", out)

    def test_missing_quote_found_and_error_skip(self):
        votes = [{"verdict": "supported"}, {"verdict": "error"}]
        code, out, tally = self.run_gate([self.source(votes=votes)], {"s0.txt": "The verified statement has enough words."})
        self.assertEqual(code, 1); self.assertIn("vote_missing_quote_found", out)
        self.assertEqual(tally["votes_missing_quote_found"], 1)
        self.assertEqual(tally["votes_checked"], 1)

    def test_decoy_quote_and_vote(self):
        cal = {"quote": "A fabricated decoy is actually here", "votes": [{"quote_found": True}]}
        page = "The verified statement has enough words. A fabricated decoy is actually here."
        code, out, tally = self.run_gate([self.source(calibration=cal)], {"s0.txt": page})
        self.assertEqual(code, 1); self.assertIn("decoy_quote_on_page", out)
        self.assertIn("decoy_vote_quote_found", out); self.assertEqual(tally["decoy_quotes_on_page"], 1)

    def test_short_quotes_and_lenient(self):
        code, _, tally = self.run_gate([self.source(quote="16.0.0 (2026-05-27)")],
                                       {"s0.txt": "Version 16.0.0 (2026-05-27) is current."})
        self.assertEqual(code, 0); self.assertEqual(tally["quotes_short"], 1)
        self.assertEqual(tally["quotes_strict"], 1)
        self.assertEqual(quotes.quote_on_page("tiny quote", quotes.normalize("nothing")), "absent")
        code, out, tally = self.run_gate([self.source(quote="PDF verification works with several words")],
            {"s0.txt": "PDF verifi- cation works with several words"})
        self.assertEqual(code, 0); self.assertIn("LENIENT-ONLY", out)
        self.assertEqual(tally["quotes_lenient_only"], 1)

    def test_missing_page(self):
        code, out, tally = self.run_gate([self.source(page="gone.txt")], {})
        self.assertEqual(code, 1); self.assertIn("page_missing", out)
        self.assertEqual(tally["pages_missing"], 1)


class ReportTests(unittest.TestCase):
    sources = [
        {"key": "S0", "source": "https://example.org/a", "title": "A", "fetch_ok": True},
        {"key": "S1", "source": "https://example.org/b", "title": "B", "fetch_ok": True},
        {"key": "S2", "source": "https://example.org/c", "title": "C", "fetch_ok": False},
    ]

    def inspect(self, report, methodology="Exact method 123", sources=None):
        data = {"ledger": {"sources": sources or self.sources}, "methodology": methodology}
        return reports.inspect_report(report, data)

    def test_good_and_labels(self):
        text = "Exact method 123\nFacts [^1] and more [^S3].\n\n[^1]: A https://example.org/a\n[^S3]: B https://example.org/b"
        got = self.inspect(text)
        self.assertTrue(got["ok"]); self.assertEqual(got["sources_cited"], ["S0", "S1"])
        self.assertEqual(got["inline_labels"], ["1", "S3"])

    def test_each_problem_list(self):
        base = "Exact method 123\nFact [^1].\n[^1]: A https://example.org/a"
        cases = [
            ("Exact method 123\nFact [^4].", "refs_without_definition", "4"),
            (base + "\n[^2]: B https://example.org/b", "definitions_never_referenced", "2"),
            (base + "\n[^1]: duplicate https://example.org/a", "duplicate_labels", "1"),
            ("Exact method 123\nFact [^1].\n[^1]: https://outside.test/x", "definitions_without_ledger_url", "1"),
            ("Exact method 123\nFact [^1].\n[^1]: https://example.org/a https://example.org/b", "definitions_with_multiple_urls", "1"),
            (base + " More [^2].\n[^2]: again https://example.org/a", "duplicate_source_definitions", "https://example.org/a"),
        ]
        for text, key, value in cases:
            with self.subTest(key=key):
                got = self.inspect(text); self.assertFalse(got["ok"]); self.assertIn(value, got[key])

    def test_prefix_methodology_appendix_and_definition_exclusion(self):
        src = [
            {"key": "S0", "source": "https://example.org/a", "fetch_ok": True},
            {"key": "S1", "source": "https://example.org/a/b", "fetch_ok": True}]
        got = self.inspect("Exact method 123\nFact [^x].\n[^x]: https://example.org/a/b", sources=src)
        self.assertTrue(got["ok"]); self.assertEqual(got["sources_cited"], ["S1"])
        got = self.inspect("Exact method 124\nFact [^1].\n[^1]: https://example.org/a")
        self.assertFalse(got["methodology_ok"]); self.assertFalse(got["ok"])
        got = self.inspect("Exact method 123\nFact [^1].\n[^1]: https://example.org/a\n## Appendix A: Verification ledger\nstray [^9]")
        self.assertNotIn("9", got["inline_labels"])
        got = self.inspect("Exact method 123\n[^1]: https://example.org/a")
        self.assertEqual(got["inline_labels"], []); self.assertFalse(got["ok"])


class AssembleTests(unittest.TestCase):
    def run_assemble(self, files):
        tmp = tempfile.TemporaryDirectory(); root = Path(tmp.name)
        for name, text in files.items(): (root / name).write_text(text)
        old = sys.argv; sys.argv = ["assemble-report.py", str(root)]; out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out): code = assemble.main()
        finally: sys.argv = old
        return tmp, root, code, out.getvalue()

    def test_final_and_plain(self):
        source = "# Report\n" + "x" * 210 + "\n## Methodology\nremove me\n## Findings\nkeep me\n"
        tmp, root, code, out = self.run_assemble({"final_report.md": source, "results.json": '{"appendix":"APPENDIX"}'})
        try:
            self.assertEqual(code, 0); self.assertEqual(json.loads(out)["report_source"], "final")
            self.assertTrue((root / "report.md").read_text().endswith("APPENDIX\n"))
            plain = (root / "report_plain.md").read_text()
            self.assertNotIn("## Methodology", plain); self.assertNotIn("APPENDIX", plain); self.assertIn("## Findings", plain)
        finally: tmp.cleanup()

    def test_draft_missing_and_no_methodology(self):
        source = "# Draft\n" + "d" * 210
        tmp, root, code, out = self.run_assemble({"unreviewed_report.md": source, "results.json": "{}"})
        try:
            self.assertEqual(code, 0); self.assertEqual(json.loads(out)["report_source"], "draft")
            self.assertEqual((root / "report_plain.md").read_text(), source + "\n")
            self.assertFalse(json.loads(out)["methodology_stripped"])
        finally: tmp.cleanup()
        tmp, _, code, out = self.run_assemble({})
        try: self.assertEqual(code, 1); self.assertEqual(out.strip(), "NO-REPORT")
        finally: tmp.cleanup()


if __name__ == "__main__":
    unittest.main()



class ReviewFollowupTests(unittest.TestCase):
    """Cases added after the adjudicated review of the v0.3 instrument."""

    def run_module(self, module, name, root):
        old = sys.argv
        sys.argv = [name, str(root)]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = module.main()
        finally:
            sys.argv = old
        return code, out.getvalue()

    def make_run(self, root, results, files):
        (root / "results.json").write_text(json.dumps(results))
        for name, text in files.items():
            (root / name).write_text(text)

    def test_assemble_honors_recorded_report_source(self):
        big = "# Report\n\n" + ("x" * 300) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A stale final from an earlier attempt must lose to the recorded draft.
            self.make_run(root, {"appendix": "", "report_source": "draft"},
                          {"final_report.md": big.replace("Report", "STALE"),
                           "unreviewed_report.md": big})
            code, out = self.run_module(assemble, "assemble-report.py", root)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.splitlines()[0])["report_source"], "draft")
            self.assertNotIn("STALE", (root / "report.md").read_text())

    def test_assemble_none_means_no_report(self):
        big = "# Report\n\n" + ("x" * 300) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_run(root, {"appendix": "", "report_source": "none"},
                          {"unreviewed_report.md": big})
            code, out = self.run_module(assemble, "assemble-report.py", root)
            self.assertEqual(code, 1)
            self.assertIn("NO-REPORT", out)

    def test_check_report_retrieval_off_skips_ledger_url_checks(self):
        report = ("# R\n\nA fact.[^1]\n\n[^1]: Someone (2020). A memory source. "
                  "https://memory.example/x\n\nM\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_run(root, {"retrieval_off": True, "results": [],
                                 "methodology": "M"}, {"report.md": report})
            code, out = self.run_module(reports, "check-report.py", root)
            data = json.JSONDecoder().raw_decode(out)[0]
            self.assertEqual(code, 0)
            self.assertTrue(data["ok"])
            self.assertEqual(data["ledger_checks"], "not-applicable (retrieval off)")
            self.assertEqual(data["definitions_without_ledger_url"], [])


    def test_quote_matches_through_markdown_link_markup(self):
        page = "Applies when SQLite is not using a [write-ahead log](wal.html). More words."
        quote = "Applies when SQLite is not using a write-ahead log."
        self.assertEqual(quotes.quote_on_page(quote, quotes.normalize(page)), "strict")

    def test_check_report_flags_authored_appendix(self):
        report = ("# R\n\nA fact.[^1]\n\n## Appendix A: Claims and verdicts\n\nstuff\n\n"
                  "[^1]: T. https://x.example/a\n\nM\n\n"
                  "## Appendix A: Verification ledger\n\nmechanical\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_run(root, {"results": [{"source": "https://x.example/a", "title": "T",
                                             "fetch_ok": True}], "methodology": "M"},
                          {"report.md": report})
            code, out = self.run_module(reports, "check-report.py", root)
            data = json.JSONDecoder().raw_decode(out)[0]
            self.assertEqual(code, 1)
            self.assertEqual(data["authored_appendix"], ["## Appendix A: Claims and verdicts"])
            self.assertIn("PROBLEM authored_appendix", out)

    def test_quote_matches_through_inline_code_and_bracket_markup(self):
        page = "copied back into the queue (after `visibility_timeout` seconds), whereas [Redis transport has to emulate it](https://x)."
        self.assertEqual(quotes.quote_on_page(
            "copied back into the queue (after visibility_timeout seconds), whereas",
            quotes.normalize(page)), "strict")
        self.assertEqual(quotes.quote_on_page(
            "whereas [Redis transport has to emulate it].", quotes.normalize(page)), "strict")
