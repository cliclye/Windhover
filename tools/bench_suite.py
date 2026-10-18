#!/usr/bin/env python3
"""bench_suite.py — one-command benchmark: baseline engine vs optimized engine.

For every model directory given it runs
  1. tools/engine_ab.py   — decode / chat-sampling / long-prefill speed + logit drift
  2. tools/serve_bench.py — multi-turn chat over SERVE=1 (prefix cache on/off + baseline)
  3. tools/hf_parity.py   — accuracy vs Hugging Face transformers (optional, needs torch)
and writes <out>/suite.json plus <out>/SUMMARY.md.

  python3 tools/bench_suite.py --baseline /path/old-engine --engine engine/windhover-engine \
      --model ~/.windhover/models/Qwen__Qwen3-1.7B --model ~/.windhover/models/Qwen__Qwen3.5-2B \
      --out docs/bench/2026-10 [--parity] [--reps 3]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def sh(cmd: list[str], timeout: int = 7200) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, timeout=timeout)


def host_info() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version()}
    if sys.platform == "darwin":
        for key in ("machdep.cpu.brand_string", "hw.memsize", "hw.perflevel0.physicalcpu",
                    "hw.perflevel1.physicalcpu"):
            try:
                info[key] = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
            except Exception:
                pass
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--engine", required=True)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--parity", action="store_true", help="run HF reference parity (needs torch)")
    ap.add_argument("--parity-python", default=str(ROOT / "c" / ".venv" / "bin" / "python3"))
    ns = ap.parse_args()
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    suite = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "host": host_info(),
             "baseline": ns.baseline, "engine": ns.engine, "models": {}}
    for m in ns.model:
        snap = Path(os.path.expanduser(m))
        tag = snap.name
        res: dict = {}
        ab = out / f"ab_{tag}.json"
        sh([sys.executable, str(TOOLS / "engine_ab.py"), "--a", ns.baseline, "--b", ns.engine,
            "--pack", str(snap), "--reps", str(ns.reps), "--modes", "greedy,chat,long", "--json", str(ab)])
        if ab.is_file():
            res["ab"] = json.loads(ab.read_text())[0]
        sv = out / f"serve_{tag}.json"
        sh([sys.executable, str(TOOLS / "serve_bench.py"), "--engine", ns.engine, "--pack", str(snap),
            "--turns", str(ns.turns), "--ngen", "96", "--compare", "--baseline", ns.baseline,
            "--json", str(sv)])
        if sv.is_file():
            res["serve"] = json.loads(sv.read_text())
        if ns.parity:
            pj = out / f"parity_{tag}.json"
            dtype = "float32"
            # f32 reference needs ~4 bytes/param; above ~2.1B params use bf16 so a
            # 16 GB machine does not swap (bf16 safetensors = 2 bytes/param).
            wbytes = sum(f.stat().st_size for f in snap.glob("*.safetensors"))
            if wbytes / 2 > 2.1e9:
                dtype = "bfloat16"
            sh([ns.parity_python, str(TOOLS / "hf_parity.py"), "--snap", str(snap), "--dtype", dtype,
                "--engine", ns.engine, "--engine", ns.baseline, "--json", str(pj)])
            if pj.is_file():
                res["parity"] = json.loads(pj.read_text())
        suite["models"][tag] = res
        (out / "suite.json").write_text(json.dumps(suite, indent=2))
    suite["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out / "suite.json").write_text(json.dumps(suite, indent=2))
    (out / "SUMMARY.md").write_text(render_summary(suite))
    print((out / "SUMMARY.md").read_text())
    return 0


def _f(v, d=1, suffix=""):
    return "—" if v is None else f"{v:.{d}f}{suffix}"


def render_summary(suite: dict) -> str:
    lines = ["# Windhover engine benchmark", "",
             f"Host: {suite['host'].get('machdep.cpu.brand_string', suite['host']['platform'])} · "
             f"{int(suite['host'].get('hw.memsize', 0)) / 2**30:.0f} GB · run {suite['started']}", "",
             "| Model | Decode tok/s (base → new) | Chat-sampling tok/s | Long-prompt prefill tok/s | Prefill speed-up |",
             "|---|---|---|---|---|"]
    for tag, r in suite["models"].items():
        modes = (r.get("ab") or {}).get("modes", {})
        g, c, lp = (modes.get(k, {}).get("summary", {}) for k in ("greedy", "chat", "long"))
        lines.append(
            f"| {tag} | {_f(g.get('a_decode'))} → **{_f(g.get('b_decode'))}** | "
            f"{_f(c.get('a_decode'))} → **{_f(c.get('b_decode'))}** | "
            f"{_f(lp.get('a_prefill'), 0)} → **{_f(lp.get('b_prefill'), 0)}** | "
            f"{_f(lp.get('prefill_speedup'), 2, '×')} |")
    lines += ["", "## Multi-turn chat (time to first token per turn)", ""]
    for tag, r in suite["models"].items():
        sv = r.get("serve") or {}
        on = sv.get("cache_on") or []
        if not on:
            continue
        off = sv.get("cache_off") or [{}] * len(on)
        base = sv.get("baseline") or [{}] * len(on)
        lines += [f"**{tag}**", "", "| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |",
                  "|---|---|---|---|---|---|"]
        for i, row in enumerate(on):
            lines.append(
                f"| {row['turn']} | {row.get('prompt_tokens') or '—'} | {row.get('cached_tokens') or 0} | "
                f"{_f(row.get('prefill_s'), 3, ' s')} | {_f((off[i] or {}).get('prefill_s'), 3, ' s')} | "
                f"{_f((base[i] or {}).get('prefill_s'), 3, ' s') if i < len(base) else '—'} |")
        if sv.get("baseline_error"):
            lines.append(f"\nBaseline engine could not run this model: `{sv['baseline_error'].strip()[:160]}`")
        lines.append("")
    if any(r.get("parity") for r in suite["models"].values()):
        lines += ["## Accuracy vs Hugging Face transformers (last-token logits, 5 prompts)", "",
                  "| Model | Reference | Engine | Top-1 match | Top-10 overlap | KL mean |", "|---|---|---|---|---|---|"]
        for tag, r in suite["models"].items():
            p = r.get("parity")
            if not p:
                continue
            for eb, e in p["engines"].items():
                s = e["summary"]
                name = "new" if eb == suite["engine"] else "baseline"
                lines.append(f"| {tag} | {p.get('reference_dtype', 'float32')} | {name} | {s['top1']} | "
                             f"{_f(s.get('top10_mean'), 2)} | {_f(s.get('kl_mean'), 4)} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
