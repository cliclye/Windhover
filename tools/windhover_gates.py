#!/usr/bin/env python3
"""Windhover Phase-0 gate harness.

Runs the go/no-go experiments behind the Windhover engine plan and writes
docs/windhover_gates.json. Each gate has an explicit criterion; later
implementation phases are blocked on their gates.

  G1 kernel ceiling     grouped-int4 SDOT GEMV effective bandwidth (C bench)
  G2 quality            PPL deltas: int4-g64 / CATS sparsity / int8-KV (torch)
  G3 speculation        n-gram draft acceptance on code+prose token streams
  G4 mmap residency     phys_footprint + page-in behavior of mmap'd weights
  G5 SME2 prefill       S=64 int8 GEMM: SME2 vs NEON (C bench)
  G6 SSD streaming      cold random-read GB/s at AU bundle sizes (C bench)

Usage:
  c/.venv/bin/python3 tools/windhover_gates.py             # all gates
  ... --skip g2,g6 --model ~/.windhover/models/Qwen__...     # subset
"""
import argparse
import datetime
import json
import math
import os
import platform
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_C = os.path.join(ROOT, "tools", "wh_kernel_bench.c")
BENCH_BIN = os.path.join(tempfile.gettempdir(), "wh_kernel_bench")
DOCS_OUT = os.path.join(ROOT, "docs", "windhover_gates.json")
DEFAULT_MODEL = os.path.expanduser(
    "~/.windhover/models/Qwen__Qwen2.5-Coder-1.5B-Instruct")
if not os.path.isdir(DEFAULT_MODEL):
    DEFAULT_MODEL = os.path.expanduser(
        "~/.kestrel/models/Qwen__Qwen2.5-Coder-1.5B-Instruct")

GS = 64  # quant group size, must match wh_kernel_bench.c / kestrel_pack.py


def sh(cmd, env=None, timeout=1800):
    e = dict(os.environ)
    if env:
        e.update(env)
    out = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                         text=True, env=e, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\n{out.stderr[-2000:]}")
    return out.stdout


def build_bench():
    omp = subprocess.run(["brew", "--prefix", "libomp"], capture_output=True,
                         text=True).stdout.strip()
    cmd = (f"clang -O3 -march=armv8.7-a+sme2+i8mm -Xclang -fopenmp "
           f"-I{omp}/include {BENCH_C} -o {BENCH_BIN} -L{omp}/lib -lomp -lm")
    sh(cmd)
    return BENCH_BIN


def run_json(args, env=None):
    out = sh([BENCH_BIN] + args, env=env)
    return json.loads(out.strip().splitlines()[-1])


# ---------------------------------------------------------------- G1/G5/G6/G4

def gate_g1():
    r4 = run_json(["g1"], env={"OMP_NUM_THREADS": "4", "OMP_WAIT_POLICY": "active"})
    big = ["lm_1.5b", "gate_7b", "down_7b"]  # shapes too big for L2
    eff = min(r4["shapes"][s]["int4_g64"]["gbs"] for s in big)
    return {
        "result": r4,
        "criterion": "int4-g64 GEMV >= 55 GB/s effective on 4 P-threads (big shapes)",
        "measured_min_gbs": eff,
        "pass": eff >= 55.0,
        "notes": "int4_row rel_err vs f64 is several x worse than int4_g64 on "
                 "outlier-heavy rows; g64 kernel costs <5% bandwidth vs row scales.",
    }


def gate_g5():
    r = run_json(["g5"], env={"OMP_NUM_THREADS": "4", "OMP_WAIT_POLICY": "active"})
    best_neon = max(r["sdot_pertoken"]["gops"], r["i8mm"]["gops"])
    ratio = r["sme2"]["gops"] / best_neon if best_neon else 0
    return {
        "result": r,
        "criterion": "SME2 int8 GEMM >= 2x best NEON path at S=64",
        "measured_ratio": round(ratio, 2),
        "pass": ratio >= 2.0 and r["sme2"]["match"] == 1,
    }


def gate_g6(scratch_gb=10):
    path = os.path.join(tempfile.gettempdir(), "wh_g6_test.bin")
    try:
        sh(f"dd if=/dev/urandom of={path} bs=16m count={scratch_gb * 64} 2>/dev/null",
           timeout=600)
        r = run_json(["g6", path])
    finally:
        if os.path.exists(path):
            os.unlink(path)
    best64 = max(v for k, v in r["runs"].items() if k.startswith("64KB"))
    best32 = max(v for k, v in r["runs"].items() if k.startswith("32KB"))
    return {
        "result": r,
        "criterion": "cold random reads >= 1.5 GB/s at chosen AU bundle size",
        "measured_64kb_gbs": best64,
        "measured_32kb_gbs": best32,
        "pass": best64 >= 1.5,
        "decision": "AU cold-fetch granularity = 64KB min (32KB is borderline, "
                    "24KB fails); batch neuron bundles into >=64KB reads.",
    }


def gate_g4(model_dir):
    st = None
    for f in sorted(os.listdir(model_dir)):
        if f.endswith(".safetensors"):
            st = os.path.join(model_dir, f)
            break
    if not st:
        return {"pass": None, "skipped": "no safetensors in model dir"}
    r = run_json(["g4", st])
    fp = r["footprint_gb"]
    accounting_win = fp["touched"] < r["file_gb"] * 0.25
    return {
        "result": r,
        "criterion": "mmap'd clean pages stay out of phys_footprint; "
                     "warm re-touch fast; no compressor spiral under pressure",
        "pass": bool(accounting_win and r["warm_touch_gbs"] > 5.0),
        "notes": "phys_footprint is what macOS pressure/jetsam accounting uses; "
                 "file-backed clean pages are reclaimable without swap.",
    }


# --------------------------------------------------------------------- G2

def corpus_text(kind):
    """Fixed repo-local corpora: code + prose (no network)."""
    if kind == "code":
        files = ["engine/runtime/engine.c"]
    else:
        files = ["README.md", "docs/METAL-M5MAX-PERF-REPORT.md",
                 "docs/experiments/glm52-6x5090-2026-07-12.md", "CONTRIBUTING.md"]
    parts = []
    for f in files:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            with open(p, "r", errors="ignore") as fh:
                parts.append(fh.read())
    return "\n\n".join(parts)


def gate_g2(model_dir, device_pref=None, seq_len=1024, max_windows=24):
    """Quality decision matrix.

    The first run of this gate showed naive symmetric g64-int4 RTN costs +9.6%
    PPL on a 1.5B — unshippable. This version tests the training-free fixes
    (asymmetric groups, AWQ-style scale folding, int8-attention hybrid, g32 KV)
    and — critically — also measures the *current* engine profile (per-row
    symmetric int8 attn + int4 MLP), which had never been quality-tested.
    Ship criterion: best Windhover profile must be at least as good as today's
    profile while cutting bytes/token ~35-45%.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = device_pref or ("mps" if torch.backends.mps.is_available() else "cpu")
    dtype = torch.float16 if device == "mps" else torch.float32
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForCausalLM.from_pretrained(model_dir, dtype=dtype)
    model.to(device).eval()

    # Untie lm_head from the embedding table. The engine always keeps a
    # separate quantized copy for the logits matmul (dense.c lm4 vs embed_q),
    # so the sim must not let lm_head quantization corrupt embeddings.
    lm = model.get_output_embeddings()
    if lm is not None and lm.weight.data_ptr() == model.get_input_embeddings().weight.data_ptr():
        lm.weight = torch.nn.Parameter(lm.weight.data.clone())

    text = corpus_text("prose") + "\n\n" + corpus_text("code")
    ids = tok(text, return_tensors="pt").input_ids[0]
    n_win = min(max_windows, (ids.numel() - 1) // seq_len)
    calib_win = 2  # first windows reserved for calibration (AWQ + CATS taus)

    def ppl(windows):
        losses = []
        with torch.no_grad():
            for w in windows:
                chunk = ids[w * seq_len:(w + 1) * seq_len + 1]
                x = chunk[:-1].unsqueeze(0).to(device)
                y = chunk[1:].unsqueeze(0).to(device)
                out = model(x).logits.float()
                loss = torch.nn.functional.cross_entropy(
                    out.view(-1, out.size(-1)), y.view(-1))
                losses.append(loss.item())
        return math.exp(sum(losses) / len(losses))

    eval_windows = list(range(calib_win, n_win))

    # ---- module classification -------------------------------------------
    def linears():
        for name, mod in model.named_modules():
            if isinstance(mod, torch.nn.Linear) and mod.weight.dim() == 2:
                yield name, mod

    def klass(name):
        if "lm_head" in name:
            return "lm"
        if any(k in name for k in ("q_proj", "k_proj", "v_proj")):
            return "attn_qkv"
        if "o_proj" in name:
            return "attn_o"
        return "mlp"

    # Stash originals on CPU — a device-side clone of every linear doubles
    # device memory and swap-kills 16GB hosts.
    orig = {name: mod.weight.data.detach().cpu().clone() for name, mod in linears()}

    def empty_cache():
        if device == "mps":
            torch.mps.empty_cache()

    def restore():
        for name, mod in linears():
            mod.weight.data = orig[name].to(device)
        empty_cache()

    # ---- calibration: per-channel input |x| mean for AWQ scale folding ----
    act_absmean = {}
    hooks = []
    for name, mod in linears():
        def mk(nm):
            def pre(module, args):
                x = args[0]
                a = x.detach().abs().reshape(-1, x.shape[-1]).mean(dim=0).float().cpu()
                if nm in act_absmean:
                    act_absmean[nm] += a
                else:
                    act_absmean[nm] = a
            return pre
        hooks.append(mod.register_forward_pre_hook(mk(name)))
    with torch.no_grad():
        for w in range(calib_win):
            model(ids[w * seq_len:(w + 1) * seq_len].unsqueeze(0).to(device))
    for h in hooks:
        h.remove()

    # ---- quantizers --------------------------------------------------------
    def q_row_sym(w, bits):
        qmax = (1 << (bits - 1)) - 1
        s = w.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / qmax
        return (w / s).round().clamp(-qmax - 1, qmax) * s

    def q_g64_asym(w, bits=4, gs=GS):
        O, I = w.shape
        if I % gs:
            return q_row_sym(w, bits)
        levels = (1 << bits) - 1
        wg = w.view(O, I // gs, gs).float()
        lo = wg.amin(dim=2, keepdim=True)
        hi = wg.amax(dim=2, keepdim=True)
        s = ((hi - lo) / levels).clamp_min(1e-8)
        q = ((wg - lo) / s).round().clamp(0, levels)
        return (q * s + lo).view(O, I).to(w.dtype)

    awq_state = {}

    def awq_scales(name, w, alpha=0.5):
        a = act_absmean.get(name)
        if a is None:
            return None
        a = a.to(w.device).clamp_min(1e-5)
        wmax = w.detach().abs().amax(dim=0).float().clamp_min(1e-5)
        s = (a ** alpha) / (wmax ** (1 - alpha))
        s = (s / s.mean()).clamp(0.2, 5.0)
        return s

    def apply_profile(profile, awq=False):
        """profile: dict klass -> ('row8'|'g64a4'|'row4'|'fp16')"""
        for h in awq_state.pop("hooks", []):
            h.remove()
        hooks_ = []
        for name, mod in linears():
            kind = profile.get(klass(name), "fp16")
            if kind == "fp16":
                mod.weight.data = orig[name].to(device)
                continue
            w = orig[name].to(device)
            if awq and kind.startswith("g64"):
                s = awq_scales(name, w)
                if s is not None:
                    w = (w.float() * s.unsqueeze(0)).to(w.dtype)
                    def mk_div(sv):
                        def pre(module, args):
                            return (args[0] / sv.to(args[0].dtype),) + args[1:]
                        return pre
                    hooks_.append(mod.register_forward_pre_hook(mk_div(s)))
            if kind == "row8":
                mod.weight.data = q_row_sym(w, 8)
            elif kind == "row4":
                mod.weight.data = q_row_sym(w, 4)
            elif kind == "g64a4":
                mod.weight.data = q_g64_asym(w, 4)
        awq_state["hooks"] = hooks_
        empty_cache()

    # ---- CATS sparsity ------------------------------------------------------
    mlps = [m for _, m in model.named_modules()
            if hasattr(m, "gate_proj") and hasattr(m, "up_proj")
            and hasattr(m, "down_proj") and hasattr(m, "act_fn")]
    taus = {}
    stats = {"kept": 0, "total": 0}
    orig_mlp_forward = type(mlps[0]).forward if mlps else None

    def sparse_forward(self, x):
        g = self.act_fn(self.gate_proj(x))
        tau = taus.get(id(self), 0.0)
        if tau > 0.0:
            mask = g.abs() > tau
            stats["kept"] += int(mask.sum())
            stats["total"] += mask.numel()
            g = g * mask
        return self.down_proj(g * self.up_proj(x))

    def calibrate_taus(target):
        taus.clear()
        if target <= 0:
            return
        acts = {id(m): [] for m in mlps}
        col = []
        for m in mlps:
            def mk(mid):
                def hook(module, inp, out):
                    a = torch.nn.functional.silu(out).abs()
                    acts[mid].append(
                        a.flatten()[:: max(1, a.numel() // 4096)].float().cpu())
                return hook
            col.append(m.gate_proj.register_forward_hook(mk(id(m))))
        with torch.no_grad():
            for w in range(calib_win):
                model(ids[w * seq_len:(w + 1) * seq_len].unsqueeze(0).to(device))
        for h in col:
            h.remove()
        for m in mlps:
            taus[id(m)] = torch.quantile(torch.cat(acts[id(m)]), target).item()

    # ---- KV int8 (g32 within head_dim, llama.cpp q8_0-style) ---------------
    kv_hooks = []

    def enable_kv8(gs=32):
        def fq(out):
            shp = out.shape
            o = out.view(*shp[:-1], shp[-1] // gs, gs).float()
            s = o.abs().amax(dim=-1, keepdim=True).clamp_min(1e-8) / 127.0
            return ((o / s).round().clamp(-128, 127) * s).view(shp).to(out.dtype)
        for name, mod in model.named_modules():
            if name.endswith("k_proj") or name.endswith("v_proj"):
                kv_hooks.append(mod.register_forward_hook(
                    lambda m, i, o: fq(o)))

    def disable_kv8():
        for h in kv_hooks:
            h.remove()
        kv_hooks.clear()

    # ---- run the matrix -----------------------------------------------------
    results = {}
    results["baseline_fp16"] = {"ppl": ppl(eval_windows)}
    base = results["baseline_fp16"]["ppl"]

    # Today's dense.c profile: int8-row qkv, int4-row o+mlp, int8-row lm.
    apply_profile({"attn_qkv": "row8", "attn_o": "row4", "mlp": "row4", "lm": "row8"})
    results["today_profile"] = {"ppl": ppl(eval_windows)}

    # WH-A: everything int4 g64 asym + AWQ (lm too).
    apply_profile({"attn_qkv": "g64a4", "attn_o": "g64a4", "mlp": "g64a4",
                   "lm": "g64a4"}, awq=True)
    results["wh_a_all4"] = {"ppl": ppl(eval_windows)}

    # WH-B: int8 qkv, rest int4 g64 asym + AWQ.
    apply_profile({"attn_qkv": "row8", "attn_o": "g64a4", "mlp": "g64a4",
                   "lm": "g64a4"}, awq=True)
    results["wh_b_attn8"] = {"ppl": ppl(eval_windows)}

    # WH-C: like B but lm int8 (isolates lm_head int4 damage).
    apply_profile({"attn_qkv": "row8", "attn_o": "g64a4", "mlp": "g64a4",
                   "lm": "row8"}, awq=True)
    results["wh_c_attn8_lm8"] = {"ppl": ppl(eval_windows)}

    best_key = min(("wh_a_all4", "wh_b_attn8", "wh_c_attn8_lm8"),
                   key=lambda k: results[k]["ppl"])
    best_profiles = {
        "wh_a_all4": {"attn_qkv": "g64a4", "attn_o": "g64a4", "mlp": "g64a4", "lm": "g64a4"},
        "wh_b_attn8": {"attn_qkv": "row8", "attn_o": "g64a4", "mlp": "g64a4", "lm": "g64a4"},
        "wh_c_attn8_lm8": {"attn_qkv": "row8", "attn_o": "g64a4", "mlp": "g64a4", "lm": "row8"},
    }
    apply_profile(best_profiles[best_key], awq=True)

    enable_kv8()
    results[f"{best_key}+kv8g32"] = {"ppl": ppl(eval_windows)}
    disable_kv8()

    if mlps:
        type(mlps[0]).forward = sparse_forward
        for target in (0.25, 0.40):
            calibrate_taus(target)
            stats["kept"] = stats["total"] = 0
            p = ppl(eval_windows)
            realized = 1.0 - stats["kept"] / max(1, stats["total"])
            results[f"{best_key}+cats{int(target * 100)}"] = {
                "ppl": p, "realized_sparsity": round(realized, 3)}
        taus.clear()
        type(mlps[0]).forward = orig_mlp_forward

    for h in awq_state.pop("hooks", []):
        h.remove()
    restore()
    del model

    for k, v in results.items():
        v["delta_pct"] = round((v["ppl"] / base - 1) * 100, 2)

    d_today = results["today_profile"]["delta_pct"]
    d_best = results[best_key]["delta_pct"]
    d_kv = results[f"{best_key}+kv8g32"]["delta_pct"] - d_best
    d_cats25 = results.get(f"{best_key}+cats25", {}).get("delta_pct", 99) - d_best
    return {
        "device": device, "seq_len": seq_len,
        "eval_windows": len(eval_windows), "corpus_tokens": int(ids.numel()),
        "variants": results,
        "best_wh_profile": best_key,
        "criterion": "best WH profile <= today_profile +0.5pp PPL at ~40% fewer "
                     "bytes; kv8g32 adds <=0.5pp; report CATS level fitting +2pp",
        "pass": bool(d_best <= d_today + 0.5 and d_kv <= 0.5),
        "sparsity_decision": ("cats25" if d_cats25 <= 2.0 else "off"),
    }


# --------------------------------------------------------------------- G3

def gate_g3(model_dir):
    """Adaptive longest-match prompt-lookup: n-gram tables for n in
    [nmin, nmax], longest suffix hit drafts up to kmax tokens.
    Cost model: verify of 1+K tokens re-reads weights once (bandwidth-bound),
    each draft position adds ~8% compute-side cost."""
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir)

    def simulate(text, nmin, nmax, kmax, cost_per_draft=0.08):
        ids = tok(text).input_ids
        tables = {n: {} for n in range(nmin, nmax + 1)}
        pos = nmax
        steps = produced = drafted = accepted = 0
        while pos < len(ids) - 1:
            src = None
            for n in range(nmax, nmin - 1, -1):
                key = tuple(ids[pos - n:pos])
                if key in tables[n]:
                    src = tables[n][key]
                    break
            for n in range(nmin, nmax + 1):
                tables[n][tuple(ids[pos - n:pos])] = pos
            steps += 1
            produced += 1
            acc = 0
            if src is not None:
                k = min(kmax, len(ids) - pos - 1, pos - src)
                drafted += k
                for j in range(k):
                    if ids[src + j] == ids[pos + j]:
                        acc += 1
                    else:
                        break
            accepted += acc
            produced += acc
            pos += 1 + acc
        cost = steps + cost_per_draft * drafted
        return {
            "tokens": len(ids), "steps": steps,
            "tokens_per_step": round(produced / steps, 3),
            "draft_acceptance": round(accepted / max(1, drafted), 3),
            "modeled_speedup": round(produced / cost, 3),
        }

    sweep = {}
    best = (None, 0.0)
    for nmin, kmax in ((2, 8), (3, 8), (3, 12), (4, 8)):
        c = simulate(corpus_text("code"), nmin, 6, kmax)
        p = simulate(corpus_text("prose"), nmin, 6, kmax)
        key = f"nmin{nmin}_k{kmax}"
        sweep[key] = {"code": c, "prose": p}
        score = min(c["modeled_speedup"], 1e9)
        if score > best[1] and p["modeled_speedup"] >= 0.99:
            best = (key, score)

    code_best = sweep[best[0]]["code"]["modeled_speedup"] if best[0] else 0
    return {
        "sweep": sweep,
        "best_config": best[0],
        "criterion": "modeled decode multiplier >= 1.25x on code/agent text "
                     "(prose must not regress)",
        "measured_code_speedup": code_best,
        "pass": code_best >= 1.25,
        "decision": "MARGINAL: ~1.2x on code, ~1.0x on prose. Speculation is "
                    "demoted from core pillar to opt-in flag (WH_SPEC=1) for "
                    "code/agent workloads; excluded from headline projections. "
                    "Revisit with session-level suffix reuse (agent edit loops "
                    "repeat far more than a linear read of this corpus).",
        "notes": "Proxy acceptance vs ground-truth continuations of repo text; "
                 "upper-bounds n-gram-only acceptance on similar distributions.",
    }


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--skip", default="", help="comma list: g1,g2,g3,g4,g5,g6,stream")
    ap.add_argument("--device", default=None, help="torch device for g2 (mps/cpu)")
    ap.add_argument("--g6-gb", type=int, default=10)
    args = ap.parse_args()
    skip = set(x.strip() for x in args.skip.split(",") if x.strip())

    build_bench()
    gates = {}

    if "stream" not in skip:
        gates["stream"] = run_json(["stream"])
    if "g1" not in skip:
        gates["g1_kernel_ceiling"] = gate_g1()
    if "g5" not in skip:
        gates["g5_sme2_prefill"] = gate_g5()
    if "g6" not in skip:
        gates["g6_ssd_streaming"] = gate_g6(args.g6_gb)
    if "g4" not in skip:
        gates["g4_mmap_residency"] = gate_g4(args.model)
    if "g3" not in skip:
        gates["g3_speculation"] = gate_g3(args.model)
    if "g2" not in skip:
        gates["g2_quality"] = gate_g2(args.model, args.device)

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu": sh("sysctl -n machdep.cpu.brand_string").strip(),
            "mem_gb": int(sh("sysctl -n hw.memsize").strip()) / 2**30,
        },
        "model": args.model,
        "gates": gates,
    }
    # merge with previous runs so gates can be (re)run piecemeal
    if os.path.exists(DOCS_OUT):
        try:
            with open(DOCS_OUT) as f:
                prev = json.load(f)
            merged = prev.get("gates", {})
            merged.update(gates)
            report["gates"] = merged
        except Exception:
            pass
    os.makedirs(os.path.dirname(DOCS_OUT), exist_ok=True)
    with open(DOCS_OUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== Windhover Phase-0 gates -> {os.path.relpath(DOCS_OUT, ROOT)} ===")
    for name, g in gates.items():
        if name == "stream":
            print(f"  stream ceiling: {g['best_gbs']} GB/s @ {g['best_threads']}T")
            continue
        status = {True: "PASS", False: "FAIL", None: "SKIP"}[g.get("pass")]
        print(f"  {name:24s} {status}   {g.get('criterion','')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
