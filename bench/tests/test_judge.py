import sys
import json
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge import extract_text, main as judge_main


class ExtractTextTests(unittest.TestCase):
    # Shapes copied from a real `pi --mode json` stream (2026-09-14): the
    # answer lives in the assistant message_end's text content blocks; deltas
    # arrive as message_update.assistantMessageEvent.text_delta.delta.
    ASSISTANT_END = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "final answer"}]}})
    USER_END = json.dumps({"type": "message_end", "message": {"role": "user", "content": [
        {"type": "text", "text": "the prompt"}]}})
    @staticmethod
    def DELTA(s):
        return json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": s}})

    def test_assistant_message_end_text_blocks_win(self):
        stream = "\n".join([self.USER_END, self.DELTA("fin"), self.DELTA("al"), self.ASSISTANT_END])
        self.assertEqual(extract_text(stream), "final answer")

    def test_deltas_are_fallback_when_no_assistant_message_end(self):
        stream = "\n".join([self.USER_END, self.DELTA("hello "), self.DELTA("world"), "not json"])
        self.assertEqual(extract_text(stream), "hello world")

    def test_user_message_text_is_never_the_answer(self):
        self.assertEqual(extract_text(self.USER_END), "")

    def test_legacy_top_level_text_events(self):
        stream = "\n".join([json.dumps({"type": "text", "text": "a"}), json.dumps({"type": "text", "text": "b"})])
        self.assertEqual(extract_text(stream), "b")

    def test_from_events_recovers_text_without_pi(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            events = os.path.join(tmp, "e.jsonl"); out = os.path.join(tmp, "o.txt")
            open(events, "w").write(self.ASSISTANT_END + "\n")
            self.assertEqual(judge_main(["--prompt", "x", "--out-text", out, "--out-json", "y", "--from-events", events]), 0)
            self.assertEqual(open(out).read(), "final answer")


if __name__ == "__main__":
    unittest.main()
