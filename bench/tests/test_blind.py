import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BlindTests(unittest.TestCase):
    def test_sections_identity_and_footnotes(self):
        with tempfile.TemporaryDirectory() as directory:
            output, labelmap = Path(directory) / "out.md", Path(directory) / "map.json"
            result = subprocess.run([sys.executable, str(BENCH / "blind.py"), str(FIXTURES / "report.md"),
                                     "--out", str(output), "--map", str(labelmap)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text()
            self.assertIn("Opening [^1] and another [^2] then again [^1].", text)
            self.assertIn("[^1]: Source seven.", text)
            self.assertIn("[^2]: Source two.", text)
            self.assertNotIn("Methodology", text)
            self.assertNotIn("Verification ledger", text)
            self.assertNotIn("deeper-research", text.lower())
            self.assertNotIn("Unused source", text)
            self.assertEqual(json.loads(labelmap.read_text()), {"7": "1", "2": "2"})


if __name__ == "__main__": unittest.main()
