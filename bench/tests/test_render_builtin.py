import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render_builtin = load("render_builtin")

RESULT = {
    "question": "How do A and B differ?",
    "summary": "A differs from B  in two ways.",
    "findings": [
        {"claim": "A is faster.", "confidence": "high",
         "sources": ["https://x.example/a", "https://y.example/b"],
         "evidence": "Both docs say so.", "vote": "3-0"},
        {"claim": "B is safer.", "confidence": "medium",
         "sources": ["https://y.example/b"], "evidence": "One doc says so."},
    ],
    "caveats": "Docs only.",
    "openQuestions": ["What about C?", ""],
    "refuted": [{"claim": "A is free.", "source": "https://z.example/c"}],
    "sources": [{"url": "https://z.example/c"}],
}


class RenderBuiltinTests(unittest.TestCase):
    def test_footnotes_one_per_url_in_first_citation_order(self):
        md = render_builtin.render(RESULT)
        # First finding cites a then b -> 1, 2; second finding reuses b -> [^2].
        self.assertIn("### 1. A is faster.[^1][^2]", md)
        self.assertIn("### 2. B is safer.[^2]", md)
        self.assertIn("[^1]: https://x.example/a", md)
        self.assertIn("[^2]: https://y.example/b", md)
        self.assertEqual(md.count("]: http"), 2)

    def test_refuted_claims_and_their_sources_are_not_rendered(self):
        md = render_builtin.render(RESULT)
        self.assertNotIn("A is free", md)
        self.assertNotIn("z.example", md)

    def test_sections_and_whitespace(self):
        md = render_builtin.render(RESULT)
        self.assertTrue(md.startswith("# How do A and B differ?\n\n## Summary\n\nA differs from B in two ways."))
        self.assertIn("## Caveats\n\nDocs only.", md)
        self.assertIn("## Open questions\n\n- What about C?\n", md)
        self.assertNotIn("- \n", md)  # the empty open question is dropped

    def test_cli_writes_file_and_reports_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "result.json")
            out = os.path.join(tmp, "report.md")
            with open(src, "w") as handle:
                json.dump(RESULT, handle)
            self.assertEqual(render_builtin.main([src, "--out", out]), 0)
            self.assertIn("[^1]: https://x.example/a", open(out).read())


if __name__ == "__main__":
    unittest.main()
