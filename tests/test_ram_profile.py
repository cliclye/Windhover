"""RAM profile math: Fast / Balanced / Low-RAM → RAM_GB + MLOCK + WH_SPARSE."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import ram_profile  # noqa: E402


class RamProfileTests(unittest.TestCase):
    def test_default_balanced_on_16gb(self):
        self.assertEqual(ram_profile.default_name(16.0), "balanced")
        self.assertEqual(ram_profile.default_name(8.0), "balanced")
        self.assertEqual(ram_profile.default_name(0.0), "balanced")

    def test_default_fast_on_large_machines(self):
        self.assertEqual(ram_profile.default_name(32.0), "fast")
        self.assertEqual(ram_profile.default_name(24.0), "fast")

    def test_cap_fractions(self):
        self.assertIsNone(ram_profile.cap_gb("fast", 16.0))
        self.assertEqual(ram_profile.cap_gb("balanced", 16.0), 8.8)
        self.assertEqual(ram_profile.cap_gb("low", 16.0), 6.4)

    def test_cap_leaves_os_headroom(self):
        # 3 GB machine: 55% would be 1.65, floor is 2.0; also phys-1.5 = 1.5 → max(2.0).
        self.assertGreaterEqual(ram_profile.cap_gb("balanced", 4.0), 2.0)

    def test_normalize(self):
        self.assertEqual(ram_profile.normalize_name("Low-RAM"), "low")
        self.assertEqual(ram_profile.normalize_name("FAST"), "fast")
        self.assertIsNone(ram_profile.normalize_name("turbo"))

    def test_resolve_balanced_sets_au_and_mlock(self):
        p = ram_profile.resolve("balanced", physical_gb=16.0)
        self.assertEqual(p["ram_gb"], 8.8)
        self.assertEqual(p["mlock"], 1)
        self.assertEqual(p["sparse"], 25)
        self.assertTrue(p["au"])

    def test_resolve_fast_unsets_budget(self):
        p = ram_profile.resolve("fast", physical_gb=16.0)
        self.assertIsNone(p["ram_gb"])
        self.assertEqual(p["mlock"], 1)
        self.assertFalse(p["au"])

    def test_resolve_low_disables_mlock(self):
        p = ram_profile.resolve("low", physical_gb=16.0)
        self.assertEqual(p["ram_gb"], 6.4)
        self.assertEqual(p["mlock"], 0)
        self.assertTrue(p["au"])

    def test_apply_to_env(self):
        env = {"PATH": "/bin"}
        ram_profile.apply_to_env(env, ram_profile.resolve("balanced", physical_gb=16.0))
        self.assertEqual(env["RAM_GB"], "8.8")
        self.assertEqual(env["COLI_HARD_CAP"], "1")
        self.assertEqual(env["MLOCK"], "1")
        self.assertEqual(env["WH_SPARSE"], "25")
        env2 = {"PATH": "/bin", "RAM_GB": "99"}
        with mock.patch.dict(os.environ, {"RAM_GB": "99"}, clear=False):
            ram_profile.apply_to_env(env2, ram_profile.resolve("low", physical_gb=16.0))
            self.assertEqual(env2["RAM_GB"], "99")

    def test_apply_fast_clears_ram_gb(self):
        env = {"PATH": "/bin", "RAM_GB": "12"}
        ram_profile.apply_to_env(env, ram_profile.resolve("fast", physical_gb=16.0))
        self.assertNotIn("RAM_GB", env)

    def test_persist_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            with mock.patch.object(ram_profile, "settings_path", return_value=path):
                ram_profile._CURRENT = None
                with mock.patch.dict(os.environ):
                    os.environ.pop("WINDHOVER_RAM_PROFILE", None)
                    ram_profile.set_active_name("low")
                    ram_profile._CURRENT = None
                    self.assertEqual(ram_profile.active_name(), "low")
                ram_profile._CURRENT = None


if __name__ == "__main__":
    unittest.main()
