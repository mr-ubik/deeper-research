import json
import subprocess
import sys
import unittest
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CostTests(unittest.TestCase):
    def test_transcripts_and_judge_usage(self):
        result = subprocess.run([sys.executable, str(BENCH / "cost.py"), str(FIXTURES / "transcript"),
                                 "--judge-usage", str(FIXTURES / "judge.jsonl")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual["agents"], 2)
        self.assertEqual(actual["by_model"]["model-a"], {"input": 105, "cache_creation": 20, "cache_read": 35, "output": 12, "turns": 2})
        self.assertEqual(actual["by_phase"]["Write"], {"input": 40, "cache_creation": 4, "cache_read": 10, "output": 8, "turns": 1})
        self.assertEqual(actual["totals"], {"input": 145, "cache_creation": 24, "cache_read": 45, "output": 20, "turns": 3})
        self.assertEqual(actual["sonnet_input_equivalent"], 279.5)
        self.assertEqual(actual["judge"], {"input": 18, "output": 5, "total": 23, "calls": 2})


if __name__ == "__main__": unittest.main()
