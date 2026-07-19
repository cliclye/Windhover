#!/usr/bin/env python3
"""Memory ceiling adversarial test (Phase 1).

Confirms:
  1. budget hard-cap unit test passes (probe + arm backend)
  2. engine under RAM_GB prints [BUDGET] hard cap and stays within soft plan
  3. pre-emptive evict path is compiled in (BUDGET_EVICT_FRACTION) — full RSS
     pressure requires a large model; tiny fixture validates the wire-up

Run from repo root or c/:
  python3 tests/memory_ceiling/test_memory_ceiling.py
  # or:  cd c && python3 ../tests/memory_ceiling/test_memory_ceiling.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C_DIR = ROOT / "c"
GLM = C_DIR / ("glm.exe" if sys.platform == "win32" else "glm")
TINY = C_DIR / "glm_tiny"
REF = C_DIR / "ref_glm.json"


class MemoryCeilingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GLM.is_file():
            subprocess.check_call(["make", "glm"], cwd=C_DIR)
        cls.test_budget = C_DIR / ("tests/test_budget.exe" if sys.platform == "win32"
                                   else "tests/test_budget")
        if not cls.test_budget.is_file():
            subprocess.check_call(["make", "tests/test_budget"], cwd=C_DIR)

    def test_budget_unit(self):
        r = subprocess.run([str(self.test_budget)], cwd=C_DIR,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        self.assertIn("test_budget: ok", r.stderr)

    def test_engine_arms_hard_cap(self):
        if not TINY.is_dir() or not REF.is_file():
            self.skipTest("glm_tiny + ref_glm.json required (run tools/make_glm_oracle.py)")
        env = os.environ.copy()
        env["SNAP"] = str(TINY)
        env["TF"] = "1"
        env["REF"] = str(REF)
        env["RAM_GB"] = "4"
        env["COLI_HARD_CAP"] = "1"
        env["COLI_OMP_TUNED"] = "1"  # skip omp re-exec noise
        r = subprocess.run([str(GLM), "8", "16", "16"], cwd=C_DIR, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, msg=r.stderr[-2000:] + r.stdout[-500:])
        self.assertIn("[BUDGET] hard cap", r.stderr)
        self.assertRegex(r.stderr, r"via (cgroup|job_object|rlimit|footprint|soft_evict)")
        self.assertIn("32/32", r.stdout)
        # Soft budget and hard cap are the same target; RSS of tiny model is << 4GB.
        self.assertNotIn("could not arm hard memory cap", r.stderr)

    def test_hard_cap_disable(self):
        if not TINY.is_dir() or not REF.is_file():
            self.skipTest("glm_tiny + ref_glm.json required")
        env = os.environ.copy()
        env["SNAP"] = str(TINY)
        env["TF"] = "1"
        env["REF"] = str(REF)
        env["RAM_GB"] = "4"
        env["COLI_HARD_CAP"] = "0"
        env["COLI_OMP_TUNED"] = "1"
        r = subprocess.run([str(GLM), "8", "16", "16"], cwd=C_DIR, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, msg=r.stderr[-2000:])
        self.assertNotIn("[BUDGET] hard cap", r.stderr)
        self.assertIn("32/32", r.stdout)


if __name__ == "__main__":
    unittest.main()
