#!/usr/bin/env python3
"""hf_parity.py — compare windhover-engine prefill logits with Hugging Face
transformers (float32, CPU) on the same prompts.

Reports, per engine binary: top-1 agreement, top-10 overlap and KL(HF || engine)
on the last prompt position. This is the accuracy number that matters for a
quantized runtime — engine-vs-engine A/B only shows self-consistency.

  c/.venv/bin/python3 tools/hf_parity.py --snap ~/.windhover/models/Qwen__Qwen3.5-0.8B \
      --engine engine/windhover-engine [--engine /path/old-engine] --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PROMPTS = [
    "Explain how a CPU cache works in three short paragraphs.",
    "Write a Python function that returns the n-th Fibonacci number iteratively.",
    "What is the capital of Australia, and why is it not Sydney?",
    "List five practical tips for writing clear technical documentation.",
    "Translate to French: The weather is nice today, let's go for a walk.",
]


def engine_logits(binary: str, pack: Path, prompt: str) -> list[float] | None:
    fd, path = tempfile.mkstemp(suffix=".f32")
    os.close(fd)
    env = dict(os.environ, SNAP=str(pack), PROMPT=prompt, NGEN="1", QUIET="1", WH_LOGITS=path)
    p = subprocess.run([binary], env=env, capture_output=True, text=True, errors="replace")
    data = Path(path).read_bytes() if os.path.exists(path) else b""
    os.unlink(path)
    if p.returncode != 0 or not data:
        print(f"  engine failed rc={p.returncode}: {p.stderr[-400:]}", file=sys.stderr)
        return None
    return list(struct.unpack(f"{len(data) // 4}f", data))


def compare(ref, got) -> dict:
    n = min(len(ref), len(got))
    ref, got = ref[:n], got[:n]

    def lsm(v):
        mx = max(v)
        s = math.log(sum(math.exp(x - mx) for x in v)) + mx
        return [x - s for x in v]

    lr, lg = lsm(ref), lsm(got)
    kl = sum(math.exp(a) * (a - b) for a, b in zip(lr, lg) if a > -30)
    tr = sorted(range(n), key=lambda i: -ref[i])[:10]
    tg = sorted(range(n), key=lambda i: -got[i])[:10]
    return {"top1": tr[0] == tg[0], "top10": len(set(tr) & set(tg)) / 10.0, "kl": kl}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", required=True, help="HF snapshot dir (with kpk/ inside)")
    ap.add_argument("--engine", action="append", required=True)
    ap.add_argument("--json")
    ap.add_argument("--dtype", default="float32", choices=["float32", "bfloat16"],
                    help="reference precision (bfloat16 halves RAM for >2B models)")
    ns = ap.parse_args()
    snap = Path(os.path.expanduser(ns.snap))
    pack = snap / "kpk" if (snap / "kpk").is_dir() else snap

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(max(1, os.cpu_count() or 4))
    tok = AutoTokenizer.from_pretrained(str(snap))
    model = AutoModelForCausalLM.from_pretrained(str(snap), dtype=getattr(torch, ns.dtype))
    model.eval()

    results = {"snap": str(snap), "reference_dtype": ns.dtype, "engines": {}}
    refs = []
    for u in PROMPTS:
        msgs = [{"role": "user", "content": u}]
        try:
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
        except Exception:
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = tok(text, return_tensors="pt", add_special_tokens=False).input_ids
        with torch.no_grad():
            lg = model(ids).logits[0, -1].float().tolist()
        refs.append((text, lg))
    for eb in ns.engine:
        rows = []
        for text, ref in refs:
            got = engine_logits(eb, pack, text)
            rows.append(compare(ref, got) if got else None)
        ok = [r for r in rows if r]
        summ = {
            "n": len(rows), "ran": len(ok),
            "top1": f"{sum(r['top1'] for r in ok)}/{len(ok)}" if ok else "0/0",
            "top10_mean": sum(r["top10"] for r in ok) / len(ok) if ok else None,
            "kl_mean": sum(r["kl"] for r in ok) / len(ok) if ok else None,
            "kl_max": max(r["kl"] for r in ok) if ok else None,
        }
        results["engines"][eb] = {"summary": summ, "rows": rows}
        print(f"{os.path.basename(eb):32} top1 {summ['top1']}  top10 {summ['top10_mean'] or 0:.2f}  "
              f"KL mean {summ['kl_mean'] if summ['kl_mean'] is not None else float('nan'):.4f} "
              f"max {summ['kl_max'] if summ['kl_max'] is not None else float('nan'):.4f}", flush=True)
    if ns.json:
        Path(ns.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
