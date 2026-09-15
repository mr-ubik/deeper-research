import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEADER = ["run_id", "question_id", "metric", "item_id", "verdict", "judge", "evidence_note"]


class ScoreTests(unittest.TestCase):
    def run_score(self, verdict_path):
        return subprocess.run([
            sys.executable, str(BENCH / "score.py"),
            "--checklist", str(BENCH / "questions/q0/checklist.v1.json"),
            "--verdicts", str(verdict_path), "--plants", str(FIXTURES / "plants.csv"),
            "--run-meta", str(FIXTURES / "run.json")], capture_output=True, text=True)

    def write_rows(self, rows):
        temporary = tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False)
        with temporary:
            writer = csv.DictWriter(temporary, fieldnames=HEADER)
            writer.writeheader(); writer.writerows(rows)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return temporary.name

    def test_full_happy_path_foreign_ignored_and_human_overrides(self):
        result = self.run_score(FIXTURES / "verdicts.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        expected = {
            "run_id": "run-0", "question_id": "q0", "pipeline": "deeper", "floor_run": False,
            "m1": {"mechanical_ok": True, "sampled": 2, "supported": 0, "partial": 1,
                   "unsupported": 1, "unverifiable": 0, "source_dead": 0},
            "m2": {"load_bearing_total": 2, "found": 1, "missed_closed": 1,
                   "missed_findable": 0, "surplus_postcutoff": 0, "surplus_contemporaneous": 1},
            "m3": {"claims": 3, "covered": 2, "partial": 0, "absent": 0,
                   "traps_asserted": 0, "hedges_violated": 1},
            "m4": {"conclusions": 2, "concordant": 1, "omitted": 1,
                   "discordant_unjustified": 0, "discordant_justified_pending": 0},
            "judge_calibration": {"plants": 4, "detected": 4},
            "cost": {"tokens": 123, "wall_seconds": 4.5, "estimated": False},
        }
        self.assertEqual(actual, expected)
        self.assertIn("ignoring foreign row", result.stderr)
        self.assertIn("human verdict overrides gpt", result.stderr)

    def test_refuses_metric_without_plant(self):
        rows = [{"run_id": "run-0", "question_id": "q0", "metric": "M1", "item_id": "s.1",
                 "verdict": "supported", "judge": "gpt", "evidence_note": ""}]
        result = self.run_score(self.write_rows(rows))
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED: metric M1 has no calibration plants", result.stderr)

    def test_rejects_verdict_outside_claim_kind(self):
        rows = [
            {"run_id": "run-0", "question_id": "q0", "metric": "M3", "item_id": "q0.c002",
             "verdict": "covered", "judge": "gpt", "evidence_note": ""},
            {"run_id": "run-0", "question_id": "q0", "metric": "M3", "item_id": "plant.m3",
             "verdict": "covered", "judge": "gpt", "evidence_note": ""},
        ]
        result = self.run_score(self.write_rows(rows))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid for claim kind 'trap'", result.stderr)

    def test_refuses_empty_verdict_set(self):
        # Zero rows must never score as "zero everywhere, exit 0".
        result = self.run_score(self.write_rows([]))
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED: no verdict rows", result.stderr)

if __name__ == "__main__": unittest.main()
