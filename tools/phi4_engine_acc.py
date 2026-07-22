#!/usr/bin/env python3
"""Engine-only Phi-4 Mini accuracy+speed smoke (no transformers load).

  ./c/.venv/bin/python tools/phi4_engine_acc.py
  BENCH_NGEN=96 ./c/.venv/bin/python tools/phi4_engine_acc.py
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine" / "windhover-engine"
OUT = Path(os.environ.get("PHI4_ACC_OUT", str(ROOT / "docs" / "phi4_engine_acc.json")))
NGEN = int(os.environ.get("BENCH_NGEN", "96"))

CASES: list[tuple[str, str | None]] = [
    ("Hi — reply in one short sentence.", None),
    ("What is 17 times 19? Reply with the number only.", r"\b323\b"),
    ("Compute 12 times 12. Digits only.", r"\b144\b"),
    ("What is 25 times 4? Number only.", r"\b100\b"),
    (
        "Solve for x: x^2 + 3x + 6x = 0. Give both roots briefly.",
        r"x\s*\(\s*x\s*\+\s*9\s*\)|(?:\b0\b.*-9)|(?:-9.*\b0\b)",
    ),
    (
        "A train travels 60 mph for 2.5 hours. How many miles does it travel? Number only.",
        r"\b150\b",
    ),
    ("What is the capital of France? One word.", r"\bparis\b"),
    (
        "Write a one-line Python function `add(xs)` that returns the sum of a list.",
        r"def\s+add\s*\(|sum\s*\(",
    ),
]


def models_dir() -> Path:
    wh = Path.home() / ".windhover" / "models"
    ke = Path.home() / ".kestrel" / "models"
    return wh if wh.is_dir() or not ke.is_dir() else ke


def main() -> int:
    hf = models_dir() / "microsoft__Phi-4-mini-instruct"
    kpk = hf / "kpk"
    if not ENGINE.is_file():
        print(f"missing engine: {ENGINE}", file=sys.stderr)
        return 1
    if not kpk.is_dir():
        print(f"missing KPK: {kpk}", file=sys.stderr)
        return 1

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(hf), trust_remote_code=True)
    rows = []
    print(f"NGEN={NGEN}  engine={ENGINE}")
    for user, expect in CASES:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": user}],
            tokenize=False,
            add_generation_prompt=True,
        )
        env = os.environ.copy()
        env.update(
            SNAP=str(kpk),
            PROMPT=prompt,
            COLI_PROMPT=prompt,
            NGEN=str(NGEN),
            TEMP="0.0",
            QUIET="0",
            WH_JSON_STATS="1",
            DRAFT="0",
        )
        t0 = time.perf_counter()
        p = subprocess.run(
            [str(ENGINE), "64", "4", "4"],
            cwd=str(ENGINE.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        wall = time.perf_counter() - t0
        out = (p.stdout or "").split("@@WH_STATS@@")[0].strip()
        err = p.stderr or ""
        m = re.search(r"decode ([\d.]+) tok/s \((\d+) tok", err)
        rope = re.search(r"\[wh\] RoPE:.*", err)
        looks_bad = bool(
            re.search(r"(.{8,40}?)\1{2,}", out)
            or "\x00" in out
            or (len(out) > 80 and len(set(out.split())) < max(5, len(out.split()) // 8))
        )
        correct = None
        if expect:
            correct = bool(re.search(expect, out, flags=re.I | re.S)) and not looks_bad
        row = {
            "prompt": user,
            "expect": expect,
            "ok": p.returncode == 0 and not looks_bad and (correct is not False),
            "correct": correct,
            "wall_s": round(wall, 3),
            "decode_tok_s": float(m.group(1)) if m else None,
            "tokens": int(m.group(2)) if m else None,
            "rope": rope.group(0) if rope else None,
            "reply": out[:300],
        }
        rows.append(row)
        tag = "OK" if row["ok"] else "FAIL"
        corr = "-" if correct is None else ("Y" if correct else "N")
        print(
            f"{tag} corr={corr}  {row['decode_tok_s'] or 0:6.2f} tok/s  "
            f"{user[:48]!r}\n  → {out[:140].replace(chr(10), ' ')}"
        )

    scored = [r for r in rows if r["correct"] is not None]
    acc = sum(1 for r in scored if r["correct"]) / len(scored) if scored else None
    speeds = [r["decode_tok_s"] for r in rows if r.get("decode_tok_s")]
    result = {
        "model": "microsoft/Phi-4-mini-instruct",
        "backend": "windhover-engine",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ngen": NGEN,
        "accuracy": round(acc, 3) if acc is not None else None,
        "decode_tok_s_mean": round(statistics.mean(speeds), 2) if speeds else None,
        "cases": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"\naccuracy={result['accuracy']}  "
        f"mean_tok/s={result['decode_tok_s_mean']}  wrote {OUT}"
    )
    return 0 if (acc is None or acc >= 0.7) else 2


if __name__ == "__main__":
    raise SystemExit(main())
