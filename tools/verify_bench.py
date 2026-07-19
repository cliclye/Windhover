#!/usr/bin/env python3
"""Verify docs/full_bench.json is complete, consistent, and meets goal gates.

Exit 0 only when the recorded fair bench is trustworthy.
Optional: VERIFY_BENCH_RERUN=1 runs one interleaved smoke batch (32/32 each).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "docs" / "full_bench.json"


def fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    if not BENCH.is_file():
        fail(f"missing {BENCH}")
    data = json.loads(BENCH.read_text())
    meta = data.get("meta") or {}
    stock = data.get("stock") or {}
    kestrel = data.get("kestrel") or {}
    cmp_ = data.get("comparison") or {}

    if not meta.get("sha_match"):
        fail(
            f"stock upstream SHA mismatch: got {meta.get('stock_upstream_sha')} "
            f"expected {meta.get('expected_upstream_sha')}"
        )
    if not stock.get("all_correct") or stock.get("oracle") != "32/32":
        fail(f"stock correctness: {stock.get('all_correct')} oracle={stock.get('oracle')}")
    if not kestrel.get("all_correct") or kestrel.get("oracle") != "32/32":
        fail(f"kestrel correctness: {kestrel.get('all_correct')} oracle={kestrel.get('oracle')}")

    thr = cmp_.get("throughput_pos_per_s") or {}
    wall = cmp_.get("batch_wall_s") or {}
    sp, kp = thr.get("stock_mean"), thr.get("kestrel_mean")
    sw, kw = wall.get("stock_mean"), wall.get("kestrel_mean")
    if not isinstance(sp, (int, float)) or not isinstance(kp, (int, float)):
        fail("missing throughput means")
    if not isinstance(sw, (int, float)) or not isinstance(kw, (int, float)):
        fail("missing wall means")
    if kp <= sp:
        fail(f"kestrel pos/s ({kp}) not greater than stock ({sp})")
    if kw >= sw:
        fail(f"kestrel wall ({kw}) not lower than stock ({sw})")
    if not cmp_.get("goal_10pct_throughput"):
        fail("goal ≥10% throughput not met")

    # CI present and ordered
    for side, label in ((stock, "stock"), (kestrel, "kestrel")):
        s = side.get("pos_per_s_batch_means") or {}
        if s.get("n", 0) < 4:
            fail(f"{label} too few batches: n={s.get('n')}")
        if not (s.get("ci95_low", 0) <= s.get("mean", -1) <= s.get("ci95_high", 0)):
            fail(f"{label} CI does not contain mean")

    delta = thr.get("delta_pct")
    print("VERIFY OK")
    print(
        f"  batches={meta.get('batches')}×{meta.get('batch_size')}  "
        f"oracle without={stock.get('oracle')} with={kestrel.get('oracle')}"
    )
    print(
        f"  pos/s without={sp:.1f} with={kp:.1f}  Δ={delta:+.2f}%  "
        f"wall Δ={wall.get('delta_pct'):+.2f}%"
    )
    print(f"  timestamp={meta.get('timestamp_utc')}")
    print(f"  source={BENCH}")

    if os.environ.get("VERIFY_BENCH_RERUN") == "1":
        # Import runner pieces for a live smoke re-check
        sys.path.insert(0, str(ROOT / "tools"))
        import full_bench as fb  # type: ignore

        print("  live smoke: 1 interleaved batch each…")
        for label, glm, cwd, snap in (
            ("stock", fb.STOCK_GLM, fb.STOCK_C, "./glm_tiny"),
            ("kestrel", fb.KESTREL_GLM, fb.KESTREL_C, fb.FIXTURE_SNAP),
        ):
            if not Path(glm).is_file():
                fail(f"missing binary for smoke: {glm}")
            b = fb.run_batch(Path(glm), Path(cwd), 40, with_time_every=0, snap=snap)
            print(f"    {label}: ok={b.all_ok} pos_mean={b.pos_mean:.1f} wall={b.wall_s:.4f}s")
            if not b.all_ok:
                fail(f"live smoke correctness failed for {label}")
        print("  live smoke OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
