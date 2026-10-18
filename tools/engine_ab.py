#!/usr/bin/env python3
"""engine_ab.py — A/B benchmark + numerics check for two windhover-engine builds.

For every (pack, prompt) pair this runs each binary REPS times and records
decode tok/s, prefill tok/s, RSS, and the greedy continuation. It also dumps
the last-position prefill logits (WH_LOGITS) from both binaries and reports
top-1 agreement, top-10 overlap, max |dlogit| and KL(A||B), so a speedup is
never reported without the numerics that go with it.

  python3 tools/engine_ab.py --a /path/old-engine --b engine/windhover-engine \
      --pack ~/.windhover/models/Qwen__Qwen3-1.7B/kpk --reps 3 --json out.json

Modes (each binary, same env):
  greedy   TEMP=0                    (decode tok/s, text parity)
  chat     TEMP=0.7 TOPK=40 TOPP=0.9 (sampling cost included)
  sparse   TEMP=0 WH_SPARSE=25        (CATS sparse FFN path, app default)
  long     ~600-token prompt, NGEN=16 (prefill tok/s)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

STATS_RE = re.compile(r"@@WH_STATS@@(\{.*\})")

SHORT_PROMPTS = [
    "Explain how a CPU cache works in three short paragraphs.",
    "Write a Python function that returns the n-th Fibonacci number iteratively.",
    "List five practical tips for writing clear technical documentation.",
]

LONG_SEED = (
    "The history of computing spans mechanical calculators, vacuum tubes, "
    "transistors, integrated circuits and modern multi-core processors. "
    "Each generation traded power, cost and reliability in different ways, "
    "and software evolved alongside: from hand-wired programs to assemblers, "
    "compilers, operating systems, networks and the web. "
)


def chat_wrap(pack: Path, user: str) -> str:
    """Minimal chat template by family so the bench exercises real chat decode."""
    cfg = {}
    for p in (pack / "config.json", pack.parent / "config.json"):
        if p.is_file():
            cfg = json.loads(p.read_text())
            break
    tc = cfg.get("text_config", cfg)
    mt = str(tc.get("model_type") or cfg.get("model_type") or "").lower()
    if mt.startswith("qwen3"):
        return (f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
                "<think>\n\n</think>\n\n")
    if mt.startswith("qwen2"):
        return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
    if mt.startswith("gemma"):
        return f"<start_of_turn>user\n{user}<end_of_turn>\n<start_of_turn>model\n"
    if mt == "granite":
        return (f"<|start_of_role|>user<|end_of_role|>{user}<|end_of_text|>\n"
                "<|start_of_role|>assistant<|end_of_role|>")
    if mt == "phi3":
        return f"<|user|>\n{user}<|end|>\n<|assistant|>\n"
    return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"


def run_once(binary: str, pack: Path, prompt: str, ngen: int, extra: dict,
             logits_path: str | None = None, timeout: int = 600) -> dict:
    env = dict(os.environ)
    env.update({
        "SNAP": str(pack), "PROMPT": prompt, "NGEN": str(ngen),
        "QUIET": "1", "WH_STATS": "1", "WH_JSON_STATS": "1", "SEED": "1234",
    })
    env.update({k: str(v) for k, v in extra.items()})
    if logits_path:
        env["WH_LOGITS"] = logits_path
    p = subprocess.run([binary], env=env, capture_output=True, text=True,
                       timeout=timeout, errors="replace")
    m = STATS_RE.search(p.stdout)
    stats = json.loads(m.group(1)) if m else {}
    text = p.stdout[: m.start()].strip() if m else p.stdout.strip()
    return {"rc": p.returncode, "stats": stats, "text": text,
            "stderr": p.stderr[-2000:] if p.returncode else ""}


def read_logits(path: str) -> list[float]:
    data = Path(path).read_bytes()
    return list(struct.unpack(f"{len(data) // 4}f", data))


def logit_compare(a: list[float], b: list[float]) -> dict:
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    def softmax(v):
        mx = max(v)
        e = [math.exp(x - mx) for x in v]
        s = sum(e)
        return [x / s for x in e]

    pa, pb = softmax(a), softmax(b)
    kl = sum(x * (math.log(x + 1e-30) - math.log(y + 1e-30)) for x, y in zip(pa, pb) if x > 1e-12)
    ta = sorted(range(n), key=lambda i: -a[i])[:10]
    tb = sorted(range(n), key=lambda i: -b[i])[:10]
    return {
        "top1_match": ta[0] == tb[0],
        "top10_overlap": len(set(ta) & set(tb)) / 10.0,
        "max_abs_dlogit": max(abs(x - y) for x, y in zip(a, b)),
        "kl": kl,
    }


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def bench_pack(a_bin: str, b_bin: str, pack: Path, reps: int, ngen: int,
               modes: list[str]) -> dict:
    out: dict = {"pack": str(pack), "modes": {}}
    mode_env = {
        "greedy": {"TEMP": "0"},
        "chat": {"TEMP": "0.7", "TOPK": "40", "TOPP": "0.9"},
        "sparse": {"TEMP": "0", "WH_SPARSE": "25"},
        "long": {"TEMP": "0"},
    }
    long_prompt = chat_wrap(pack, "Summarize the following text in two sentences.\n\n" + LONG_SEED * 9)
    tmp = tempfile.mkdtemp(prefix="wh_ab_")
    for mode in modes:
        prompts = [long_prompt] if mode == "long" else [chat_wrap(pack, p) for p in SHORT_PROMPTS]
        ng = 16 if mode == "long" else ngen
        res = {"a": {"decode": [], "prefill": [], "rss": []},
               "b": {"decode": [], "prefill": [], "rss": []},
               "text_match": [], "logits": []}
        for pi, prompt in enumerate(prompts):
            texts = {}
            for rep in range(reps):
                # alternate order so thermal drift does not favour one binary
                order = (("a", a_bin), ("b", b_bin)) if rep % 2 == 0 else (("b", b_bin), ("a", a_bin))
                for tag, binary in order:
                    lp = os.path.join(tmp, f"{tag}_{mode}_{pi}.f32") if rep == 0 else None
                    r = run_once(binary, pack, prompt, ng, mode_env[mode], lp)
                    if r["rc"] != 0:
                        print(f"  !! {tag} {mode} rc={r['rc']}\n{r['stderr']}", file=sys.stderr)
                        continue
                    s = r["stats"]
                    res[tag]["decode"].append(s.get("decode_tok_s"))
                    res[tag]["prefill"].append(s.get("prefill_tok_s"))
                    res[tag]["rss"].append(s.get("rss_gb"))
                    if rep == 0:
                        texts[tag] = r["text"]
            if mode != "chat" and "a" in texts and "b" in texts:
                res["text_match"].append(texts["a"] == texts["b"])
            la = os.path.join(tmp, f"a_{mode}_{pi}.f32")
            lb = os.path.join(tmp, f"b_{mode}_{pi}.f32")
            if mode in ("greedy", "long") and os.path.isfile(la) and os.path.isfile(lb):
                res["logits"].append(logit_compare(read_logits(la), read_logits(lb)))
        summary = {
            "a_decode": med(res["a"]["decode"]), "b_decode": med(res["b"]["decode"]),
            "a_prefill": med(res["a"]["prefill"]), "b_prefill": med(res["b"]["prefill"]),
            "a_rss": med(res["a"]["rss"]), "b_rss": med(res["b"]["rss"]),
            "text_match": f"{sum(res['text_match'])}/{len(res['text_match'])}" if res["text_match"] else None,
        }
        if res["logits"]:
            summary["top1_match"] = f"{sum(l['top1_match'] for l in res['logits'])}/{len(res['logits'])}"
            summary["top10_overlap"] = statistics.mean(l["top10_overlap"] for l in res["logits"])
            summary["max_kl"] = max(l["kl"] for l in res["logits"])
            summary["max_abs_dlogit"] = max(l["max_abs_dlogit"] for l in res["logits"])
        for k in ("decode", "prefill"):
            a, b = summary[f"a_{k}"], summary[f"b_{k}"]
            summary[f"{k}_speedup"] = (b / a) if a and b else None
        out["modes"][mode] = {"summary": summary, "raw": res}
        sp = summary
        print(f"  [{mode:6}] decode {sp['a_decode']} -> {sp['b_decode']} "
              f"(x{sp['decode_speedup'] or 0:.2f}) | prefill {sp['a_prefill']} -> "
              f"{sp['b_prefill']} (x{sp['prefill_speedup'] or 0:.2f}) | text {sp['text_match']}"
              + (f" | top1 {sp['top1_match']} KL {sp['max_kl']:.2e}" if 'max_kl' in sp else ""),
              flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="baseline engine binary")
    ap.add_argument("--b", required=True, help="candidate engine binary")
    ap.add_argument("--pack", action="append", required=True, help="KPK dir (repeatable)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--ngen", type=int, default=128)
    ap.add_argument("--modes", default="greedy,chat,sparse,long")
    ap.add_argument("--json", help="write full results here")
    ns = ap.parse_args()
    results = []
    for pk in ns.pack:
        pack = Path(os.path.expanduser(pk))
        if (pack / "kpk").is_dir():
            pack = pack / "kpk"
        print(f"== {pack}", flush=True)
        results.append(bench_pack(ns.a, ns.b, pack, ns.reps, ns.ngen, ns.modes.split(",")))
    if ns.json:
        Path(ns.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
