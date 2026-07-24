#!/usr/bin/env python3
"""Regression: packaged Windows must not pass a missing ENGINE_DIR as cwd.

WinError 267 (ERROR_DIRECTORY) happens when CreateProcess gets a non-existent
working directory. Packaged installs ship windhover-engine next to the sidecar,
not under bundle/engine.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_windhover():
    path = ROOT / "windhover"
    loader = importlib.machinery.SourceFileLoader("windhover_cli_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_engine_cwd_fallback():
    mod = load_windhover()
    eng = ROOT / "engine" / ("windhover-engine.exe" if sys.platform == "win32" else "windhover-engine")
    if not eng.is_file():
        print("SKIP: no local engine binary")
        return 0
    missing = Path(tempfile.mkdtemp()) / "bundle" / "engine"
    mod.ENGINE_DIR = missing
    mod.ENGINE_BIN = eng
    cwd = mod._engine_cwd()
    assert cwd.is_dir(), cwd
    assert cwd == eng.resolve().parent
    print(f"PASS _engine_cwd -> {cwd}")

    # Launch must work with that cwd even without SNAP.
    r = subprocess.run(
        [str(eng), "64", "4", "4"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert r.returncode != 0
    blob = (r.stderr or "") + (r.stdout or "")
    assert "SNAP" in blob
    print("PASS engine CreateProcess with fallback cwd")
    return 0


if __name__ == "__main__":
    raise SystemExit(test_engine_cwd_fallback())
