"""Windhover Code agent loop with a scripted model (no engine needed)."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from code_agent import CodeSession, _loose_replace  # noqa: E402


def scripted(replies):
    """generate() that returns the given replies in order and records prompts."""
    seen = []

    def gen(messages, max_tokens, temperature, on_delta):
        seen.append(messages)
        text = replies[min(len(seen) - 1, len(replies) - 1)]
        if on_delta:
            for i in range(0, len(text), 7):
                on_delta(text[i:i + 7])
        return text, {"backend": "fake"}

    gen.seen = seen
    return gen


class CodeAgentLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_edit_answer(self):
        gen = scripted([
            '```tool\n{"name": "read_file", "path": "calc.py"}\n```',
            "TOOL edit_file\npath: calc.py\nold:\n    return a + b\nnew:\n    return a + b\n\n\n"
            "def mul(a, b):\n    return a * b\nEND",
            "Added a mul(a, b) function to calc.py.",
        ])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("add a multiply function")
        self.assertIn("def mul(a, b):", (self.root / "calc.py").read_text())
        tools = [e for e in s.events if e["type"] == "tool"]
        self.assertEqual([t["status"] for t in tools], ["ok", "ok"])
        self.assertTrue(tools[1]["result"]["diff"].startswith("--- a/calc.py"))
        final = [e for e in s.events if e["type"] == "assistant" and e.get("final")]
        self.assertEqual(final[-1]["text"], "Added a mul(a, b) function to calc.py.")
        # the model saw the file content in its second prompt
        self.assertIn("return a + b", gen.seen[1][-1]["content"])
        self.assertFalse(s.busy)

    def test_undo_restores_file(self):
        gen = scripted(['```tool\n{"name": "write_file", "path": "new.txt", "content": "hi"}\n```', "Done."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("create new.txt")
        self.assertEqual((self.root / "new.txt").read_text(), "hi\n")
        cid = next(e["change_id"] for e in s.events if e.get("change_id"))
        self.assertTrue(s.undo(cid)["ok"])
        self.assertFalse((self.root / "new.txt").exists())

    def test_run_requires_approval_and_denial_is_reported(self):
        gen = scripted(['```tool\n{"name": "run", "command": "echo hello"}\n```', "The command was declined."])
        s = CodeSession(self.root, "fake", gen)
        th = threading.Thread(target=s.run_turn, args=("run echo",))
        th.start()
        for _ in range(100):
            if s.snapshot()["pending_approval"]:
                break
            time.sleep(0.02)
        pid = s.snapshot()["pending_approval"]
        self.assertIsNotNone(pid)
        s.answer_approval(pid, False)
        th.join(5)
        tool = next(e for e in s.events if e["type"] == "tool")
        self.assertEqual(tool["status"], "denied")
        self.assertIn("declined", gen.seen[1][-1]["content"])

    def test_run_auto_approved(self):
        gen = scripted(['```tool\n{"name": "run", "command": "echo hello"}\n```', "It printed hello."])
        s = CodeSession(self.root, "fake", gen)
        s.auto_run = True
        s.run_turn("run echo")
        tool = next(e for e in s.events if e["type"] == "tool")
        self.assertEqual(tool["status"], "ok")
        self.assertIn("hello", tool["result"]["output"])

    def test_repeat_read_is_skipped(self):
        call = '```tool\n{"name": "read_file", "path": "calc.py"}\n```'
        s = CodeSession(self.root, "fake", scripted([call, call, "It adds two numbers."]))
        s.run_turn("what does calc.py do")
        statuses = [e["status"] for e in s.events if e["type"] == "tool"]
        self.assertEqual(statuses, ["ok", "skipped"])

    def test_path_escape_blocked(self):
        s = CodeSession(self.root, "fake",
                        scripted(['```tool\n{"name": "read_file", "path": "../../etc/passwd"}\n```', "ok"]))
        s.run_turn("read passwd")
        tool = next(e for e in s.events if e["type"] == "tool")
        self.assertEqual(tool["status"], "error")
        self.assertIn("escapes workspace", tool["summary"])

    def test_failed_edit_returns_current_file(self):
        gen = scripted(["TOOL edit_file\npath: calc.py\nold:\nnot in file\nnew:\nx\nEND", "Gave up."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("edit")
        self.assertIn("def add(a, b):", gen.seen[1][-1]["content"])

    def test_follow_up_keeps_history(self):
        gen = scripted(["calc.py has an add function.", "It returns a + b."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("what is in calc.py")
        s.run_turn("and what does it return?")
        roles = [m["role"] for m in gen.seen[1]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])


    def test_narrated_intent_is_nudged_not_final(self):
        gen = scripted(["Let me look at the files first.",
                        '```tool\n{"name": "list_dir", "path": "."}\n```',
                        "There is one file, calc.py."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("what files are here")
        self.assertIn("Go ahead", gen.seen[1][-1]["content"])
        final = [e for e in s.events if e["type"] == "assistant" and e.get("final")]
        self.assertEqual(final[-1]["text"], "There is one file, calc.py.")


    def test_wrong_dir_guess_is_corrected_and_empty_old_appends(self):
        gen = scripted(['```tool\n{"name": "read_file", "path": "src/calc.py"}\n```',
                        '```tool\n{"name": "edit_file", "path": "src/calc.py", "old": "", "new": "def mul(a, b):\\n    return a * b"}\n```',
                        "Added mul."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("add mul")
        self.assertIn("using calc.py", gen.seen[1][-1]["content"])
        text = (self.root / "calc.py").read_text()
        self.assertTrue(text.startswith("def add(a, b):"))
        self.assertIn("\n\n\ndef mul(a, b):\n    return a * b\n", text)


    def test_destructive_edits_are_refused(self):
        gen = scripted(['```tool\n{"name": "write_file", "path": "calc.py", "content": ""}\n```',
                        "TOOL edit_file\npath: calc.py\nold:\nnew:\nEND", "ok"])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("break it")
        self.assertIn("def add", (self.root / "calc.py").read_text())
        self.assertEqual([e["status"] for e in s.events if e["type"] == "tool"], ["error", "error"])


    def test_system_prompt_is_stable_across_steps(self):
        gen = scripted(['```tool\n{"name": "write_file", "path": "zzz_new.py", "content": "x = 1"}\n```', "Done."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("create a file")
        self.assertEqual(gen.seen[0][0]["content"], gen.seen[1][0]["content"])


    def test_empty_reply_is_retried(self):
        gen = scripted(["", '```tool\n{"name": "list_dir", "path": "."}\n```', "One file: calc.py."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("list files")
        self.assertIn("empty", gen.seen[1][-1]["content"])
        final = [e for e in s.events if e["type"] == "assistant" and e.get("final")]
        self.assertEqual(final[-1]["text"], "One file: calc.py.")


class PermissionsAndEffort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _answer_when_pending(self, s, approve):
        for _ in range(200):
            pid = s.snapshot()["pending_approval"]
            if pid:
                return pid, s.answer_approval(pid, approve)
            time.sleep(0.02)
        self.fail("no approval requested")

    EDIT = "TOOL edit_file\npath: calc.py\nold:\n    return a + b\nnew:\n    return b + a\nEND"

    def test_ask_mode_shows_diff_and_writes_after_approval(self):
        s = CodeSession(self.root, "fake", scripted([self.EDIT, "Swapped."]))
        s.set_mode("ask")
        th = threading.Thread(target=s.run_turn, args=("swap",))
        th.start()
        for _ in range(200):
            snap = s.snapshot()
            if snap["pending_approval"]:
                ev = next(e for e in snap["events"] if e["id"] == snap["pending_approval"])
                self.assertIn("+    return b + a", ev["result"]["diff"])
                self.assertIn("return a + b", (self.root / "calc.py").read_text())  # not written yet
                s.answer_approval(ev["id"], True)
                break
            time.sleep(0.02)
        th.join(5)
        self.assertIn("return b + a", (self.root / "calc.py").read_text())

    def test_ask_mode_rejection_leaves_file(self):
        gen = scripted([self.EDIT, "OK, left it."])
        s = CodeSession(self.root, "fake", gen)
        s.set_mode("ask")
        th = threading.Thread(target=s.run_turn, args=("swap",))
        th.start()
        self._answer_when_pending(s, False)
        th.join(5)
        self.assertIn("return a + b", (self.root / "calc.py").read_text())
        self.assertIn("rejected", gen.seen[1][-1]["content"])
        self.assertEqual(next(e for e in s.events if e["type"] == "tool")["status"], "denied")

    def test_plan_mode_blocks_changes(self):
        gen = scripted([self.EDIT, "1. Swap the operands."])
        s = CodeSession(self.root, "fake", gen)
        s.set_mode("plan")
        s.run_turn("plan a swap")
        self.assertIn("return a + b", (self.root / "calc.py").read_text())
        self.assertIn("Plan mode", gen.seen[0][-1]["content"])
        self.assertIn("Plan mode", next(e for e in s.events if e["type"] == "tool")["summary"])

    def test_high_effort_thinks_and_hides_thoughts(self):
        seen = {}

        def gen(messages, max_tokens, temperature, on_delta, thinking=False):
            seen["thinking"], seen["max_tokens"] = thinking, max_tokens
            return "The user wants a summary.\n</think>\n\ncalc.py adds numbers.", {}

        s = CodeSession(self.root, "fake", gen)
        s.set_effort("high")
        s.run_turn("what is calc.py")
        self.assertTrue(seen["thinking"])
        self.assertEqual(seen["max_tokens"], 4096)
        final = [e for e in s.events if e["type"] == "assistant" and e.get("final")][-1]
        self.assertEqual(final["text"], "calc.py adds numbers.")
        self.assertIn("summary", final["thinking"])
        self.assertNotIn("think", s.history[-1]["content"])

    def test_images_reach_the_model(self):
        gen = scripted(["It shows a red square."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("what is this?", images=["data:image/png;base64,AAAA"], thumbs=["data:image/jpeg;base64,BB"])
        self.assertEqual(gen.seen[0][-1]["images"], ["data:image/png;base64,AAAA"])
        self.assertEqual(s.events[0]["images"], ["data:image/jpeg;base64,BB"])


class DoTheWork(unittest.TestCase):
    """The agent must save files / run commands instead of telling the user to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_pasted_in_chat_is_nudged_into_a_file(self):
        page = "```html\n" + "\n".join(f"<p>{i}</p>" for i in range(20)) + "\n```"
        gen = scripted([page,
                        '```tool\n{"name": "write_file", "path": "index.html", "content": "<p>hi</p>"}\n```',
                        "Created index.html."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("create a quick html page")
        self.assertTrue((self.root / "index.html").is_file())
        self.assertIn("you have tools", gen.seen[1][-1]["content"])
        # the pasted code is not left in the transcript
        self.assertFalse(any("<p>19</p>" in (e.get("text") or "") for e in s.events))

    def test_telling_the_user_to_run_is_nudged(self):
        gen = scripted(["I can't open files in your browser, but you can run `open index.html`.",
                        '```tool\n{"name": "run", "command": "echo opened"}\n```', "Opened it."])
        s = CodeSession(self.root, "fake", gen)
        s.mode = "bypass"
        s.run_turn("open it in my browser")
        tool = next(e for e in s.events if e["type"] == "tool")
        self.assertEqual(tool["status"], "ok")

    def test_cut_off_file_is_not_saved(self):
        half = '```tool\n{"name": "write_file", "path": "index.html", "content": "<html><body>' + "x" * 50
        gen = scripted([half, '```tool\n{"name": "write_file", "path": "index.html", "content": "<p>ok</p>"}\n```',
                        "Created index.html."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("create a page")
        self.assertEqual((self.root / "index.html").read_text(), "<p>ok</p>\n")
        self.assertIn("cut off", gen.seen[1][-1]["content"])

    def test_fence_closed_with_END_is_not_cut_off(self):
        (self.root / "a.js").write_text("x = 1\n")
        gen = scripted(['```tool\n{"name": "edit_file", "path": "a.js", "old": "x = 1", "new": "x = 2"}\nEND', "Done."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("set x to 2")
        self.assertEqual((self.root / "a.js").read_text(), "x = 2\n")

    def test_going_in_circles_gets_the_file_and_a_push(self):
        (self.root / "calc.js").write_text("function mul(a, b) {\n  return a + b;\n}\n")
        search = '```tool\n{"name": "search", "query": "nothing-here"}\n```'
        gen = scripted(['```tool\n{"name": "read_file", "path": "calc.js"}\n```', search,
                        '```tool\n{"name": "search", "query": "also-missing"}\n```',
                        '```tool\n{"name": "read_file", "path": "calc.js"}\n```',
                        "TOOL edit_file\npath: calc.js\nold:\n  return a + b;\nnew:\n  return a * b;\nEND",
                        "Fixed."])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("fix mul in calc.js")
        pushes = [m for m in s.history if "going in circles" in m["content"]]
        self.assertEqual(len(pushes), 1)
        self.assertIn("return a + b", pushes[0]["content"])
        self.assertIn("a * b", (self.root / "calc.js").read_text())

    def test_compacted_read_can_run_again(self):
        (self.root / "a.txt").write_text("hello\n")
        read = '```tool\n{"name": "read_file", "path": "a.txt"}\n```'
        gen = scripted([read, read, "Done."])
        s = CodeSession(self.root, "fake", gen)
        orig = s._messages

        def compacting():
            for m in s.history:
                if m.get("kind") == "result":
                    m["compacted"] = True
            return orig()

        s._messages = compacting
        s.run_turn("read a.txt twice")
        self.assertEqual([e["status"] for e in s.events if e["type"] == "tool"], ["ok", "ok"])

    def test_questions_with_code_examples_are_answers(self):
        gen = scripted(["Use a list comprehension:\n```python\n" + "x = 1\n" * 10 + "```"])
        s = CodeSession(self.root, "fake", gen)
        s.run_turn("what is a list comprehension?")
        self.assertEqual(len(gen.seen), 1)

    def test_server_runs_in_background_off_windhover_port(self):
        gen = scripted(['```tool\n{"name": "run", "command": "python3 -m http.server 8000"}\n```', "Serving."])
        s = CodeSession(self.root, "fake", gen)
        s.mode = "bypass"
        try:
            s.run_turn("serve this folder on localhost")
            tool = next(e for e in s.events if e["type"] == "tool")
            self.assertTrue(tool["result"].get("background"))
            self.assertNotIn("8000", tool["result"].get("output", "") + tool["summary"])
            self.assertIn("used by Windhover", gen.seen[1][-1]["content"])
            self.assertEqual(len(s.procs), 1)
        finally:
            s.stop_background()


class VisibleText(unittest.TestCase):
    def test_unterminated_tool_fence_and_end_lines_hidden(self):
        v = CodeSession._visible
        self.assertEqual(v('Reading it.\n```tool\n{"name": "read_file", "pa'), "Reading it.")
        self.assertEqual(v("Done.\nEND"), "Done.")
        self.assertEqual(v('Saving it.\n{"name": "write_file", "path": "a.html", "content": "<p>'), "Saving it.")
        self.assertEqual(v("Use:\n```python\nx = 1\n```"), "Use:\n```python\nx = 1\n```")


class LooseReplace(unittest.TestCase):
    def test_indentation_drift(self):
        text = "class A:\n    def f(self):\n        return 1\n"
        out = _loose_replace(text, "def f(self):\n    return 1", "def f(self):\n    return 2")
        self.assertEqual(out, "class A:\n    def f(self):\n        return 2\n")

    def test_ambiguous_returns_none(self):
        self.assertIsNone(_loose_replace("x = 1\nx = 1\n", "x = 1", "x = 2"))


if __name__ == "__main__":
    unittest.main()
