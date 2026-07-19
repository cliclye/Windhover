#!/usr/bin/env python3
"""Calibration-aware mixed-precision quantizer — Phase 2 scaffolding (blueprint §3.1).

This is the converter *plan* + tier assignment harness. Full AWQ/VQ codebook fitting
requires a calibration corpus + fp reference forward; until then this tool:

  1. Reads safetensors headers (like coli plan)
  2. Assigns each tensor to Tier A/B/C per the blueprint table
  3. Emits quant_profile.json for the budget controller

Tier assignment (lossless-by-default until measured):
  A — attention q/kv-LoRA, out proj, router logits → int8 (sensitive)
  B — embeddings → int8, resident=false (streamed)
  C — expert FFN → keep current int4 until VQ kernels land (opt-in: --expert-bits 3)

Usage:
  python3 tools/quantize.py --model /path/to/model --out quant_profile.json
  python3 tools/quantize.py --model ./glm_tiny --out /tmp/qp.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXPERT_RE = re.compile(r"model\.layers\.\d+\.mlp\.experts\.")
ROUTER_RE = re.compile(r"model\.layers\.\d+\.mlp\.gate\.")
ATTN_RE = re.compile(
    r"model\.layers\.\d+\.self_attn\.(q_a_proj|q_b_proj|kv_a_proj|kv_b_proj|o_proj)"
)
EMBED_RE = re.compile(r"(embed_tokens|lm_head)")


def tensor_names(model: Path):
    import struct

    for shard in sorted(model.glob("*.safetensors")):
        with shard.open("rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            header = json.loads(f.read(n))
        for name, meta in header.items():
            if name == "__metadata__":
                continue
            start, end = meta["data_offsets"]
            yield name, end - start


def assign_tier(name: str) -> dict:
    if EMBED_RE.search(name):
        return {
            "tier": "B",
            "bits": 8,
            "scheme": "int8_row",
            "resident": False,
            "rationale": "embedding lookup — stream rows (EMBED_STREAM)",
        }
    if ROUTER_RE.search(name) or ATTN_RE.search(name):
        return {
            "tier": "A",
            "bits": 8,
            "scheme": "int8_row",
            "resident": True,
            "rationale": "MLA/router-sensitive — protect at int8",
        }
    if EXPERT_RE.search(name):
        return {
            "tier": "C",
            "bits": 4,
            "scheme": "int4_row",
            "resident": False,
            "rationale": "expert FFN — int4 baseline; VQ (~2.5–3bit) behind --expert-bits",
        }
    return {
        "tier": "A",
        "bits": 8,
        "scheme": "int8_row",
        "resident": True,
        "rationale": "default protected",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expert-bits", type=int, default=4, choices=[3, 4],
                    help="3 = experimental VQ placeholder (NOT implemented in kernels yet)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    model = Path(args.model)
    if not model.is_dir():
        sys.exit(f"missing model dir: {model}")

    tensors = {}
    for name, size in tensor_names(model):
        tier = assign_tier(name)
        if tier["tier"] == "C" and args.expert_bits == 3:
            tier = dict(tier)
            tier["bits"] = 3
            tier["scheme"] = "vq_pq8x256"
            tier["experimental"] = True
            tier["warning"] = "VQ kernels not shipped — profile only; do not convert yet"
        tensors[name] = {**tier, "nbytes_src": size}

    profile = {
        "profile_id": "mixed-v1-scaffold",
        "tiers": {
            "attn_qkv_out": {"bits": 8, "scheme": "int8_row"},
            "router_logits": {"bits": 8, "scheme": "int8_row"},
            "embeddings": {"bits": 8, "scheme": "int8_row", "resident": False},
            "expert_ffn": {
                "bits": args.expert_bits,
                "scheme": "vq_pq8x256" if args.expert_bits == 3 else "int4_row",
            },
        },
        "measured_quality_delta_vs_int4_baseline_pp": None,
        "measured_on": None,
        "status": "scaffold — run calibration + bench.py before promoting to default",
        "tensors": tensors,
    }
    text = json.dumps(profile, indent=2) + "\n"
    if args.dry_run:
        print(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(tensors)} tensors)", file=sys.stderr)
        if args.expert_bits == 3:
            print(
                "WARNING: --expert-bits 3 is experimental — no VQ CPU kernels yet "
                "(blueprint: ship behind --precision aggressive only after harness pass)",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
