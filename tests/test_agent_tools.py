"""Agent tool-call parsing across the formats local models actually emit."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from agent_workspace import parse_tool_calls, run_tool  # noqa: E402


class ParseToolCalls(unittest.TestCase):
    def test_colon_block(self):
        self.assertEqual(parse_tool_calls("TOOL read_file\npath: calc.py\nEND"),
                         [{"name": "read_file", "path": "calc.py"}])

    def test_json_fence(self):
        self.assertEqual(parse_tool_calls('```tool\n{"name":"list_dir","path":"."}\n```'),
                         [{"name": "list_dir", "path": "."}])

    def test_xml_key_without_close(self):
        # Qwen3.5-2B emitted this and every read_file failed with FileNotFoundError: .
        self.assertEqual(parse_tool_calls("TOOL read_file\n<path>calc.py"),
                         [{"name": "read_file", "path": "calc.py"}])

    def test_xml_key_with_close(self):
        self.assertEqual(parse_tool_calls("TOOL read_file\n<path>calc.py</path>\nEND"),
                         [{"name": "read_file", "path": "calc.py"}])

    def test_native_qwen_tool_call(self):
        text = ("<tool_call>\n<function=read_file>\n<parameter=path>\ncalc.py\n</parameter>\n"
                "</function>\n</tool_call>")
        self.assertEqual(parse_tool_calls(text), [{"name": "read_file", "path": "calc.py"}])

    def test_xml_str_replace(self):
        calls = parse_tool_calls("TOOL str_replace\n<path>a.py\n<old>x = 1\n<new>x = 2\nEND")
        self.assertEqual(calls, [{"name": "str_replace", "path": "a.py", "old": "x = 1", "new": "x = 2"}])


class RunTool(unittest.TestCase):
    def test_read_file_without_path_is_clear(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_tool(Path(d), {"name": "read_file"})
            self.assertFalse(r["ok"])
            self.assertIn("needs a path", r["error"])

    def test_read_file_on_directory_points_to_list_dir(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            r = run_tool(Path(d), {"name": "read_file", "path": "src"})
            self.assertFalse(r["ok"])
            self.assertIn("list_dir", r["error"])


if __name__ == "__main__":
    unittest.main()
