#!/usr/bin/env python3
"""A/B bench: Phi-4 Mini Instruct — windhover-engine vs stock transformers.

Measures wall time, decode tok/s, RSS, and reply quality on the same prompts.
Writes docs/phi4_ab_bench.json.

  python3 tools/phi4_ab_bench.py
  NGEN=64 TRIALS=2 python3 tools/phi4_ab_bench.py
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
OUT = Path(os.environ.get("PHI4_BENCH_OUT", str(ROOT / "docs" / "phi4_ab_bench.json")))
NGEN = int(os.environ.get("BENCH_NGEN", "96"))
TRIALS = int(os.environ.get("BENCH_TRIALS", "2"))
# (prompt, expect_regex or None) — expect is checked case-insensitively on the reply.
PROMPTS: list[tuple[str, str | None]] = [
    ("Hi — reply in one short sentence.", None),
    (
        "What is 17 times 19? Reply with the number only.",
        r"\b323\b",
    ),
    (
        "Solve for x: x^2 + 3x + 6x = 0. Give both roots briefly.",
        r"(?:\b0\b.*(?:-9|-9\.0)\b)|(?:(?:-9|-9\.0)\b.*\b0\b)|x\s*=\s*0.*x\s*=\s*-9|x\s*=\s*-9.*x\s*=\s*0|x\(x\s*\+\s*9\)",
    ),
    (
        "A train travels 60 mph for 2.5 hours. How many miles does it travel? Number only.",
        r"\b150\b",
    ),
    (
        "What is the capital of France? One word.",
        r"\bparis\b",
    ),
    (
        "Write a one-line Python function `add(xs)` that returns the sum of a list.",
        r"def\s+add\s*\(|sum\s*\(",
    ),
    (
        "List three bullet points on why local LLMs matter.",
        r"(?:^|\n)\s*[-*•]|\b1[\).]",
    ),
]


def _models_dir() -> Path:
    wh = Path.home() / ".windhover" / "models"
    ke = Path.home() / ".kestrel" / "models"
    return wh if wh.is_dir() or not ke.is_dir() else ke


def _find_phi() -> tuple[Path, Path]:
    root = _models_dir() / "microsoft__Phi-4-mini-instruct"
    if not root.is_dir():
        raise SystemExit(f"Phi-4 Mini not installed at {root}")
    kpk = root / "kpk"
    if not kpk.is_dir():
        raise SystemExit(f"Missing KPK pack at {kpk} — install/convert first")
    return root, kpk


def _chat_prompt(hf_root: Path, user: str) -> str:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(hf_root), trust_remote_code=True)
    return tok.apply_chat_template(
        [{"role": "user", "content": user}],
        tokenize=False,
        add_generation_prompt=True,
    )


def _rss_mb() -> float:
    try:
        import resource

        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return rss / (1024.0 * 1024.0)
        return rss / 1024.0
    except Exception:
        return 0.0


def _parse_wh(stderr: str, stdout: str) -> dict:
    r: dict = {}
    m = re.search(
        r"\[wh\] decode ([\d.]+) tok/s \((\d+) tok, (\d+) fwd\) \| "
        r"prefill ([\d.]+) tok/s \| RSS ([\d.]+) GB \| footprint ([\d.]+) GB",
        stderr,
    )
    if m:
        r.update(
            decode_tok_s=float(m.group(1)),
            tokens=int(m.group(2)),
            forwards=int(m.group(3)),
            prefill_tok_s=float(m.group(4)),
            rss_gb=float(m.group(5)),
            footprint_gb=float(m.group(6)),
        )
    if "@@WH_STATS@@" in stdout:
        _, _, tail = stdout.partition("@@WH_STATS@@")
        try:
            js = json.loads(tail.strip().splitlines()[0])
            r.update({k: v for k, v in js.items() if v is not None})
        except Exception:
            pass
    return r


def _quality(text: str, expect: str | None = None) -> dict:
    t = (text or "").strip()
    weird = 0
    if not t:
        weird += 1
    if re.search(r"\|{5,}", t) or "\x00" in t or t.count("\ufffd") >= 2:
        weird += 1
    if re.search(r"\b(I I I|can I can I|My I Can)\b", t):
        weird += 1
    if re.search(r"(.{8,60}?)\1{2,}", t, flags=re.DOTALL):
        weird += 1
    # short-token soup: "return: xs: return: xs:" etc.
    if re.search(r"((?:\b\w{1,8}\b[:\s]*){3,})\1{2,}", t):
        weird += 1
    if re.search(r"(?:\b\d{2,4}\b[:\s]*){8,}", t):
        weird += 1
    if len(t) > 80 and len(set(t.split())) < max(5, len(t.split()) // 8):
        weird += 1
    looks_ok = weird == 0 and 0 < len(t) < 2500
    correct = None
    if expect:
        correct = bool(re.search(expect, t, flags=re.IGNORECASE | re.DOTALL)) and looks_ok
    return {
        "chars": len(t),
        "words": len(t.split()),
        "looks_ok": looks_ok,
        "correct": correct,
        "expect": expect,
        "preview": t[:220].replace("\n", " "),
    }


def run_engine(kpk: Path, hf_root: Path, user: str, expect: str | None) -> dict:
    prompt = _chat_prompt(hf_root, user)
    env = os.environ.copy()
    env.update(
        {
            "SNAP": str(kpk),
            "PROMPT": prompt,
            "COLI_PROMPT": prompt,
            "NGEN": str(NGEN),
            "TEMP": "0.0",
            "QUIET": "0",
            "WH_JSON_STATS": "1",
            "DRAFT": "0",
        }
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
    out = p.stdout or ""
    err = p.stderr or ""
    if "@@WH_STATS@@" in out:
        text, _, _ = out.partition("@@WH_STATS@@")
    else:
        text = out
    text = text.strip()
    stats = _parse_wh(err, out)
    q = _quality(text, expect)
    ok = p.returncode == 0 and q["looks_ok"]
    if q.get("correct") is False:
        ok = False
    return {
        "backend": "windhover-engine",
        "ok": ok,
        "wall_s": round(wall, 3),
        "reply": text,
        "quality": q,
        **stats,
    }


def run_transformers(model, tok, device, user: str, eos, expect: str | None) -> dict:
    import torch

    prompt = tok.apply_chat_template(
        [{"role": "user", "content": user}],
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tok(prompt, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    # warmup once per call site (caller may warm once)
    t0 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=NGEN,
            do_sample=False,
            eos_token_id=eos,
            pad_token_id=tok.eos_token_id,
        )
    wall = time.perf_counter() - t0
    new_tokens = out[0][inputs["input_ids"].shape[-1] :]
    text = tok.decode(new_tokens, skip_special_tokens=True).strip()
    ntok = int(new_tokens.shape[0])
    q = _quality(text, expect)
    ok = q["looks_ok"]
    if q.get("correct") is False:
        ok = False
    return {
        "backend": "transformers",
        "ok": ok,
        "wall_s": round(wall, 3),
        "tokens": ntok,
        "decode_tok_s": round(ntok / wall, 2) if wall > 0 else 0.0,
        "rss_mb": round(_rss_mb(), 1),
        "reply": text,
        "quality": q,
        "device": str(device),
    }


def _summarize(rows: list[dict]) -> dict:
    walls = [r["wall_s"] for r in rows]
    tps = [r["decode_tok_s"] for r in rows if r.get("decode_tok_s")]
    ok = all(r.get("ok") for r in rows)
    corrects = [r.get("quality", {}).get("correct") for r in rows]
    corrects = [c for c in corrects if c is not None]
    out = {
        "ok": ok,
        "trials": len(rows),
        "correct_rate": round(sum(1 for c in corrects if c) / len(corrects), 2) if corrects else None,
        "wall_s_mean": round(statistics.mean(walls), 3) if walls else None,
        "wall_s_std": round(statistics.pstdev(walls), 3) if len(walls) > 1 else 0.0,
        "decode_tok_s_mean": round(statistics.mean(tps), 2) if tps else None,
        "decode_tok_s_std": round(statistics.pstdev(tps), 2) if len(tps) > 1 else 0.0,
        "replies": [r.get("quality", {}).get("preview") for r in rows],
    }
    rss = [r["rss_gb"] for r in rows if r.get("rss_gb") is not None]
    if rss:
        out["rss_gb_mean"] = round(statistics.mean(rss), 3)
    rss_mb = [r["rss_mb"] for r in rows if r.get("rss_mb") is not None]
    if rss_mb:
        out["rss_mb_mean"] = round(statistics.mean(rss_mb), 1)
    return out


def main() -> int:
    if not ENGINE.is_file():
        print(f"missing engine: {ENGINE} — run ./windhover build", file=sys.stderr)
        return 1
    hf_root, kpk = _find_phi()
    print(f"HF  = {hf_root}")
    print(f"KPK = {kpk}")
    print(f"NGEN={NGEN} TRIALS={TRIALS}")

    results: dict = {
        "model": "microsoft/Phi-4-mini-instruct",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ngen": NGEN,
        "trials": TRIALS,
        "prompts": {},
    }

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print("Loading transformers Phi-4 Mini once…")
    tok = AutoTokenizer.from_pretrained(str(hf_root), trust_remote_code=True)
    dtype = torch.float16 if torch.backends.mps.is_available() else torch.float32
    # Prefer native Phi3 (HF 5.x); remote modeling_phi3.py breaks on newer transformers.
    model = AutoModelForCausalLM.from_pretrained(
        str(hf_root),
        dtype=dtype,
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    )
    if torch.backends.mps.is_available():
        model = model.to("mps")
    model.eval()
    device = next(model.parameters()).device
    eos = None
    gcfg = hf_root / "generation_config.json"
    if gcfg.is_file():
        eos = json.loads(gcfg.read_text()).get("eos_token_id")
    # warmup
    warm = tok("Hi", return_tensors="pt")
    warm = {k: v.to(device) for k, v in warm.items()}
    with torch.inference_mode():
        _ = model.generate(**warm, max_new_tokens=4, do_sample=False, eos_token_id=eos)
    results["transformers_device"] = str(device)
    results["transformers_dtype"] = str(dtype).replace("torch.", "")

    for user, expect in PROMPTS:
        print(f"\n=== prompt: {user!r} ===")
        eng_rows = []
        for i in range(TRIALS):
            r = run_engine(kpk, hf_root, user, expect)
            eng_rows.append(r)
            print(
                f"  engine[{i}] wall={r['wall_s']}s "
                f"tok/s={r.get('decode_tok_s')} ok={r['ok']} "
                f"correct={r['quality'].get('correct')} "
                f"→ {r['quality']['preview']!r}"
            )
        tf_rows = []
        for i in range(TRIALS):
            r = run_transformers(model, tok, device, user, eos, expect)
            tf_rows.append(r)
            print(
                f"  transformers[{i}] wall={r['wall_s']}s "
                f"tok/s={r.get('decode_tok_s')} ok={r['ok']} "
                f"correct={r['quality'].get('correct')} "
                f"→ {r['quality']['preview']!r}"
            )
        eng_s = _summarize(eng_rows)
        tf_s = _summarize(tf_rows)
        speedup = None
        if eng_s.get("decode_tok_s_mean") and tf_s.get("decode_tok_s_mean"):
            speedup = round(eng_s["decode_tok_s_mean"] / tf_s["decode_tok_s_mean"], 2)
        results["prompts"][user] = {
            "expect": expect,
            "windhover_engine": eng_s,
            "transformers": tf_s,
            "speedup_decode_tok_s": speedup,
            "engine_trials": [
                {k: v for k, v in r.items() if k != "reply"}
                | {"reply_preview": r["quality"]["preview"]}
                for r in eng_rows
            ],
            "transformers_trials": [
                {k: v for k, v in r.items() if k != "reply"}
                | {"reply_preview": r["quality"]["preview"]}
                for r in tf_rows
            ],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nWrote {OUT}")

    # Console summary table
    print("\nSummary (decode tok/s | correct rate):")
    print(
        f"{'prompt':<42} {'eng tok/s':>10} {'tf tok/s':>10} {'speedup':>8} "
        f"{'eng corr':>8} {'tf corr':>8}"
    )
    for user, block in results["prompts"].items():
        e = block["windhover_engine"].get("decode_tok_s_mean")
        t = block["transformers"].get("decode_tok_s_mean")
        s = block.get("speedup_decode_tok_s")
        ec = block["windhover_engine"].get("correct_rate")
        tc = block["transformers"].get("correct_rate")
        print(
            f"{user[:42]:<42} {e or 0:>10.2f} {t or 0:>10.2f} {s or 0:>7.2f}x "
            f"{('-' if ec is None else f'{ec:.0%}'):>8} "
            f"{('-' if tc is None else f'{tc:.0%}'):>8}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
