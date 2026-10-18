#!/usr/bin/env python3
"""serve_bench.py — multi-turn chat benchmark over the SERVE=1 engine protocol.

Drives one warm windhover-engine through a scripted conversation (each turn
re-sends the full history, like the app does) and records per-turn prompt
tokens, tokens served from the prefix KV cache, prefill seconds and decode
tok/s. Run with --compare to replay the same conversation with the prefix
cache disabled (WH_PREFIX_CACHE=0) and check the greedy replies match.

  python3 tools/serve_bench.py --engine engine/windhover-engine \
      --pack ~/.windhover/models/Qwen__Qwen3-1.7B --turns 6 --compare
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_text import fallback_chat_prompt, snap_model_type  # noqa: E402
from engine_session import END, READY, encode_whgen, parse_stats_blob  # noqa: E402

USER_TURNS = [
    "I'm planning a 3-day trip to Kyoto in autumn. What should I prioritise?",
    "Which of those are best early in the morning to avoid crowds?",
    "Suggest a simple day-1 itinerary with times.",
    "What local foods should I try near those places?",
    "How do I get from Kyoto Station to Arashiyama cheaply?",
    "Summarise the whole plan in five bullet points.",
    "Any etiquette tips for temples I should know?",
    "What should I pack for the weather?",
]


def read_until(proc, marker: bytes, timeout: float = 600) -> bytes:
    buf = b""
    t0 = time.time()
    while marker not in buf:
        ch = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
        if not ch:
            raise RuntimeError("engine exited: " + proc.stderr.read().decode(errors="replace")[-800:])
        buf += ch
        if time.time() - t0 > timeout:
            raise TimeoutError(marker)
    return buf


def run_conversation(engine: str, pack: Path, turns: int, ngen: int, cache: bool) -> list[dict]:
    env = dict(os.environ, SNAP=str(pack), SERVE="1", QUIET="1",
               WH_PREFIX_CACHE="1" if cache else "0", CTX="8192")
    proc = subprocess.Popen([engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    read_until(proc, READY)
    snap = pack.parent if pack.name == "kpk" else pack
    mt = snap_model_type(snap)
    history: list[dict] = []
    rows = []
    for t in range(turns):
        history.append({"role": "user", "content": USER_TURNS[t % len(USER_TURNS)]})
        prompt = fallback_chat_prompt(history, mt, snap)
        t0 = time.time()
        proc.stdin.write(encode_whgen(prompt, ngen=ngen, temp=0.0, topk=0, topp=0.0, spec=0))
        proc.stdin.flush()
        raw = read_until(proc, END)
        wall = time.time() - t0
        body, stats = parse_stats_blob(raw)
        reply = body.decode("utf-8", errors="replace").strip()
        for stop in ("<|im_end|>", "<end_of_turn>", "<|eot_id|>"):
            reply = reply.split(stop)[0]
        history.append({"role": "assistant", "content": reply})
        prefill_s = stats.get("prefill_s")
        if prefill_s is None and stats.get("decode_tok_s"):
            # Older engines don't report prefill time: wall minus decode time.
            prefill_s = max(0.0, wall - float(stats.get("tokens") or 0) / float(stats["decode_tok_s"]))
        rows.append({
            "turn": t + 1,
            "prompt_tokens": stats.get("prompt_tokens"),
            "cached_tokens": stats.get("cached_tokens"),
            "prefill_s": prefill_s,
            "decode_tok_s": stats.get("decode_tok_s"),
            "generated": stats.get("tokens"),
            "wall_s": round(wall, 3),
            "reply": reply,
        })
    try:
        proc.stdin.write(b"WHQUIT\n")
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    proc.wait(timeout=30)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--ngen", type=int, default=96)
    ap.add_argument("--compare", action="store_true", help="also run with the prefix cache off")
    ap.add_argument("--baseline", help="also replay the conversation on this (older) engine binary")
    ap.add_argument("--json")
    ns = ap.parse_args()
    pack = Path(os.path.expanduser(ns.pack))
    if (pack / "kpk").is_dir():
        pack = pack / "kpk"
    out = {"pack": str(pack)}
    out["cache_on"] = run_conversation(ns.engine, pack, ns.turns, ns.ngen, True)
    if ns.compare:
        out["cache_off"] = run_conversation(ns.engine, pack, ns.turns, ns.ngen, False)
    if ns.baseline:
        try:
            out["baseline"] = run_conversation(ns.baseline, pack, ns.turns, ns.ngen, False)
        except Exception as e:  # older engines may not run newer architectures
            out["baseline_error"] = str(e)[-400:]
    print(f"{'turn':>4} {'prompt':>7} {'cached':>7} {'prefill_s(on)':>14} {'prefill_s(off)':>15} "
          f"{'baseline_s':>11} {'same reply':>10}")
    n = len(out["cache_on"])
    for i, r in enumerate(out["cache_on"]):
        off = (out.get("cache_off") or [None] * n)[i]
        base = (out.get("baseline") or [None] * n)[i]
        print(f"{r['turn']:>4} {r['prompt_tokens'] or 0:>7} {r['cached_tokens'] or 0:>7} "
              f"{r['prefill_s'] or 0:>14.3f} {(off or {}).get('prefill_s') or 0:>15.3f} "
              f"{(base or {}).get('prefill_s') or 0:>11.3f} "
              f"{str(off['reply'] == r['reply']) if off else '-':>10}")
    if ns.json:
        Path(ns.json).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
