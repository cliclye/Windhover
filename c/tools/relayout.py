#!/usr/bin/env python3
"""Profile-guided expert disk relayout (blueprint §3.2a / paper SSD streaming).

Zero quality risk — pure I/O engineering:
  1. Read calibration traces of (layer, expert_id) activations
  2. Build co-activation graph: weight(e_i, e_j) = P(both fire same forward)
  3. Greedy chain-merge → linear per-layer expert order
  4. Emit a layout manifest (expert_id → new rank) for a future rewriter

Input formats (any mix):
  - ROUTE_TRACE lines: "call pos layer id:gate ..." (colibrì ROUTE_TRACE)
  - .coli_usage / stats.txt heat dumps (layer expert count ...)

Usage:
  python3 tools/relayout.py --trace route.txt --out layout.json
  python3 tools/relayout.py --usage .coli_usage --out layout.json

Does NOT rewrite weight shards yet (needs full model path + safetensors rewrite);
ships the layout plan so a later pass can coalesce reads.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_route_trace(path: Path):
    """Yield sets of expert ids per (forward, layer)."""
    rows = defaultdict(dict)  # (fwd, pos) -> {layer: [ids]}
    fwd, prev_layer = 0, -1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split()
        if len(p) < 4:
            continue
        try:
            pos, layer = int(p[1]), int(p[2])
        except ValueError:
            continue
        if layer < prev_layer:
            fwd += 1
        prev_layer = layer
        ids = []
        for tok in p[3:]:
            ids.append(int(tok.split(":")[0]))
        rows[(fwd, pos)][layer] = ids
    # collapse to per-forward per-layer unique sets
    by_fwd = defaultdict(lambda: defaultdict(set))
    for (f, _pos), layers in rows.items():
        for layer, ids in layers.items():
            by_fwd[f][layer].update(ids)
    return by_fwd


def load_usage_heat(path: Path):
    """Fallback: treat high-heat experts as often co-fired within a layer.
    Produces weak edges (same-layer top-K pairing) when no route trace exists.
    """
    # format varies; accept "layer expert count" lines
    heats = defaultdict(dict)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split()
        if len(p) < 3:
            continue
        try:
            layer, eid, cnt = int(p[0]), int(p[1]), int(p[2])
        except ValueError:
            continue
        heats[layer][eid] = cnt
    by_fwd = defaultdict(lambda: defaultdict(set))
    # synthesize one pseudo-forward per layer from top experts
    for layer, d in heats.items():
        top = sorted(d, key=d.get, reverse=True)[:32]
        by_fwd[0][layer] = set(top)
    return by_fwd


def build_coactivation(by_fwd):
    """per-layer undirected co-activation counts."""
    edge = defaultdict(lambda: defaultdict(int))  # layer -> {(a,b): count} a<b
    node = defaultdict(lambda: defaultdict(int))
    for _f, layers in by_fwd.items():
        for layer, ids in layers.items():
            ids = sorted(ids)
            for e in ids:
                node[layer][e] += 1
            for i, a in enumerate(ids):
                for b in ids[i + 1 :]:
                    edge[layer][(a, b)] += 1
    return edge, node


def greedy_chain(edge, node):
    """Greedy chain-merge: start from highest-degree node, append max-edge neighbor."""
    order = {}
    for layer, nodes in node.items():
        if not nodes:
            continue
        remaining = set(nodes)
        # start at most frequent
        start = max(remaining, key=lambda e: nodes[e])
        chain = [start]
        remaining.remove(start)
        while remaining:
            last = chain[-1]
            best, best_w = None, -1
            for other in remaining:
                a, b = (last, other) if last < other else (other, last)
                w = edge[layer].get((a, b), 0)
                if w > best_w:
                    best_w, best = w, other
            if best is None:
                best = max(remaining, key=lambda e: nodes[e])
            chain.append(best)
            remaining.remove(best)
        order[layer] = chain
    return order


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", action="append", default=[], help="ROUTE_TRACE file(s)")
    ap.add_argument("--usage", default="", help=".coli_usage / heat dump fallback")
    ap.add_argument("--out", required=True, help="layout JSON path")
    args = ap.parse_args()

    by_fwd = defaultdict(lambda: defaultdict(set))
    for t in args.trace:
        part = load_route_trace(Path(t))
        for f, layers in part.items():
            for layer, ids in layers.items():
                by_fwd[f][layer].update(ids)
    if args.usage:
        part = load_usage_heat(Path(args.usage))
        for f, layers in part.items():
            for layer, ids in layers.items():
                by_fwd[f][layer].update(ids)
    if not by_fwd:
        print("no traces/usage loaded", file=sys.stderr)
        sys.exit(2)

    edge, node = build_coactivation(by_fwd)
    order = greedy_chain(edge, node)
    layout = {
        "schema": "kestrel.expert_layout.v1",
        "quality_risk": "none",
        "note": "Reorder on-disk experts per layer to this sequence; "
                "runtime may coalesce adjacent predicted experts into one pread.",
        "layers": {
            str(layer): {
                "order": chain,
                "expert_to_rank": {str(e): i for i, e in enumerate(chain)},
            }
            for layer, chain in sorted(order.items())
        },
        "stats": {
            "layers": len(order),
            "experts_total": sum(len(c) for c in order.values()),
            "forwards_observed": len(by_fwd),
        },
    }
    Path(args.out).write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out}: {layout['stats']['layers']} layers, "
        f"{layout['stats']['experts_total']} experts",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
