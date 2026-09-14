import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge import extract_text


class JudgeTests(unittest.TestCase):
    def test_last_text_event_wins(self):
        stream = '{"type":"text","text":"first"}\n{"type":"text","text":"final"}\n'
        self.assertEqual(extract_text(stream), "final")

    def test_deltas_are_fallback(self):
        stream = '{"type":"text_delta","text":"hello "}\ninvalid\n{"type":"text_delta","text":"world"}\n'
        self.assertEqual(extract_text(stream), "hello world")


if __name__ == "__main__": unittest.main()
