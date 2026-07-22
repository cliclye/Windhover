#!/usr/bin/env python3
"""Frozen entrypoint for the Windhover desktop sidecar (PyInstaller).

Runs `windhover app` with ROOT = bundle (MEIPASS) and engine beside the exe
(Tauri externalBin layout).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    frozen = getattr(sys, "frozen", False)
    if frozen:
        bundle = Path(getattr(sys, "_MEIPASS"))
        exe_dir = Path(sys.executable).resolve().parent
    else:
        bundle = Path(__file__).resolve().parents[1]
        exe_dir = bundle / "engine"

    os.environ.setdefault("WINDHOVER_ROOT", str(bundle))

    for name in ("windhover-engine.exe", "windhover-engine"):
        cand = exe_dir / name
        if cand.is_file():
            os.environ["WINDHOVER_ENGINE"] = str(cand)
            break
        # Tauri sometimes nests resources one level up from the sidecar
        alt = exe_dir.parent / name
        if alt.is_file():
            os.environ["WINDHOVER_ENGINE"] = str(alt)
            break

    # Ensure windhover script + tools are importable from the bundle
    sys.path.insert(0, str(bundle))
    wh = bundle / "windhover"
    if not wh.is_file():
        print(f"windhover-server: missing {wh}", file=sys.stderr)
        return 1

    # Avoid interactive first-run pulls in the frozen GUI path unless needed.
    os.environ.setdefault("WINDHOVER_APP_NO_AUTOPULL", "1")

    sys.argv = [
        "windhover",
        "app",
        "--host",
        os.environ.get("WINDHOVER_HOST", "127.0.0.1"),
        "--port",
        os.environ.get("WINDHOVER_PORT", "8000"),
    ]

    import importlib.util

    spec = importlib.util.spec_from_file_location("windhover_cli", wh)
    if spec is None or spec.loader is None:
        print("windhover-server: failed to load windhover", file=sys.stderr)
        return 1
    mod = importlib.util.module_from_spec(spec)
    # Force ROOT to bundle before exec (script assigns ROOT from __file__)
    spec.loader.exec_module(mod)
    # Re-bind ROOT if the script used __file__ under a different layout
    if hasattr(mod, "ROOT"):
        mod.ROOT = bundle
        mod.ENGINE_DIR = bundle / "engine"
        if hasattr(mod, "_engine_bin"):
            mod.ENGINE_BIN = mod._engine_bin()
        mod.CATALOG_PATH = bundle / "app" / "public" / "catalog.json"
        if not mod.CATALOG_PATH.is_file():
            mod.CATALOG_PATH = bundle / "app" / "dist" / "catalog.json"
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
