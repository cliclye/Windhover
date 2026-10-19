"""Unit tests for tools/chat_text turn-boundary cleanup."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from chat_text import clean_chat_text  # noqa: E402


class ChatTextTests(unittest.TestCase):
    def test_chatml_end(self):
        self.assertEqual(
            clean_chat_text("Hello.\n<|im_end|>\n<|im_start|>user\nMore junk"),
            "Hello.",
        )

    def test_phi_end(self):
        self.assertEqual(
            clean_chat_text("Paris is the capital.<|end|>\n<|user|>\nWhat else?"),
            "Paris is the capital.",
        )

    def test_gemma_end(self):
        self.assertEqual(
            clean_chat_text("Done.\n<end_of_turn>\n<start_of_turn>user\nHi"),
            "Done.",
        )

    def test_plain_user_header(self):
        self.assertEqual(
            clean_chat_text("Answer\n\nuser: follow up question about cats"),
            "Answer",
        )

    def test_instruction_dump(self):
        self.assertEqual(
            clean_chat_text("42\n\n### Instruction\nIgnore"),
            "42",
        )

    def test_keeps_mid_sentence_assistant(self):
        self.assertEqual(
            clean_chat_text("Normal text about the assistant: role is fine"),
            "Normal text about the assistant: role is fine",
        )

    def test_gibberish_tail_after_greeting(self):
        raw = "Hello! How can I help you? i23ruehf903hf3nflsdkjf;laksjdf"
        self.assertEqual(clean_chat_text(raw), "Hello! How can I help you?")

    def test_code_fence_after_greeting(self):
        raw = "Hello! How can I help you?\n\n```python\nprint(1)\n```"
        self.assertEqual(clean_chat_text(raw), raw)

    def test_smash_fence_after_greeting(self):
        raw = "Hello! How can I help you?\n\n```\ni23ruehf903hf3nflsdkjf;laksjdf\n```"
        self.assertEqual(clean_chat_text(raw), "Hello! How can I help you?")


if __name__ == "__main__":
    unittest.main()


class MathIsNotGibberish(unittest.TestCase):
    def test_latex_answer_is_kept(self):
        from chat_text import cut_gibberish_tail

        text = ("Use the product rule. Let $u(x) = \\frac{1}{2}\\cos(x)$ and $v(x) = \\sin(x)$. "
                "Then $f'(x) = \\frac{1}{2}(\\cos^2(x) - \\sin^2(x)) = \\frac{1}{2}\\cos(2x)$.")
        self.assertEqual(cut_gibberish_tail(text), text)
        self.assertEqual(clean_chat_text(text), text)

    def test_plain_equation_is_kept(self):
        from chat_text import cut_gibberish_tail

        text = "Differentiate. f'(x) = 0.5*(cos^2(x) - sin^2(x)) = 0.5*cos(2x)"
        self.assertEqual(cut_gibberish_tail(text), text)

    def test_keyboard_smash_still_cut(self):
        from chat_text import cut_gibberish_tail

        self.assertEqual(cut_gibberish_tail("Paris is the capital. qwrtzxcvbnmlkjhgfdsp"),
                         "Paris is the capital.")


if __name__ == "__main__":
    unittest.main()
