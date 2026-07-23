"""Regression: Windows cp1252/charmap must not crash model download progress."""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
WINDHOVER = ROOT / "windhover"


def _load_windhover():
    loader = importlib.machinery.SourceFileLoader("windhover_cli_test", str(WINDHOVER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WindowsStdioUtf8Test(unittest.TestCase):
    def test_pull_banner_encodes_on_cp1252(self):
        """The old 'pulling id → dest' arrow (U+2192) raised UnicodeEncodeError on Windows."""
        mid = "microsoft/Phi-4-mini-instruct"
        dest = Path("C:/Users/test/.windhover/models/microsoft__Phi-4-mini-instruct")
        msg = f"pulling {mid} -> {dest}"
        encoded = msg.encode("cp1252")
        self.assertEqual(encoded.decode("cp1252"), msg)
        with self.assertRaises(UnicodeEncodeError):
            f"pulling {mid} \u2192 {dest}".encode("cp1252")

    def test_catalog_loads_as_utf8_with_arrow(self):
        """catalog.json contains U+2192; locale cp1252 read_text() must not be used."""
        wh = _load_windhover()
        path = ROOT / "app" / "public" / "catalog.json"
        self.assertTrue(path.is_file())
        with self.assertRaises(UnicodeDecodeError):
            path.read_bytes().decode("cp1252")
        models = json.loads(path.read_text(encoding="utf-8")).get("models", [])
        self.assertTrue(models)
        with mock.patch.object(wh, "CATALOG_PATH", path):
            loaded = wh.load_catalog()
        self.assertTrue(isinstance(loaded, list))
        self.assertGreater(len(loaded), 0)

    def test_configure_stdio_utf8_allows_arrow(self):
        wh = _load_windhover()
        buf = io.BytesIO()
        wrapper = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        with mock.patch.object(sys, "stdout", wrapper), mock.patch.object(sys, "stderr", wrapper):
            wh._configure_stdio_utf8()
            try:
                sys.stdout.write("pulling x \u2192 y\n")
                sys.stdout.flush()
            except UnicodeEncodeError as e:
                self.fail(f"stdout still rejects Unicode after configure: {e}")

    def test_cmd_pull_unknown_model_print_is_ascii(self):
        wh = _load_windhover()
        buf = io.BytesIO()
        err = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        with mock.patch.object(sys, "stderr", err):
            wh._configure_stdio_utf8()
            rc = wh.cmd_pull(argparse.Namespace(model_id="no/such-model", weights=True))
        self.assertEqual(rc, 1)
        err.flush()
        text = buf.getvalue().decode("cp1252", errors="replace")
        self.assertIn("unknown model id", text)


if __name__ == "__main__":
    unittest.main()
