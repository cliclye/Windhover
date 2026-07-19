#!/usr/bin/env python3
"""Render README benchmark SVG from docs/full_bench.json (measured data only)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "docs" / "full_bench.json"
OUT = ROOT / "docs" / "screenshots" / "bench-stock-vs-kestrel.svg"


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render(data: dict) -> str:
    stock_pos = data["stock"]["pos_per_s_batch_means"]["mean"]
    kest_pos = data["kestrel"]["pos_per_s_batch_means"]["mean"]
    stock_wall = data["stock"]["batch_wall_s"]["mean"]
    kest_wall = data["kestrel"]["batch_wall_s"]["mean"]
    stock_rss = (data["stock"].get("max_rss_mb") or {}).get("mean")
    kest_rss = (data["kestrel"].get("max_rss_mb") or {}).get("mean")
    d_pos = data["comparison"]["throughput_pos_per_s"]["delta_pct"]
    d_wall = data["comparison"]["batch_wall_s"]["delta_pct"]
    ts = data["meta"].get("timestamp_utc", "")[:19].replace("T", " ") + " UTC"
    batches = data["meta"].get("batches")
    batch_size = data["meta"].get("batch_size")
    sha = (data["meta"].get("stock_upstream_sha") or "")[:12]

    wall_stock_idx = 100.0
    wall_kest_idx = (stock_wall / kest_wall) * 100.0 if kest_wall else 0.0

    w, h = 920, 520
    pad_l = 72

    def pair(x0: float, y0: float, bw: float, max_h: float, a: float, b: float, fmt: str = "{:,.0f}"):
        m = max(a, b) or 1.0
        ha = max_h * (a / m)
        hb = max_h * (b / m)
        gap = 12
        xa, xb = x0, x0 + bw + gap
        la, lb = fmt.format(a), fmt.format(b)
        return "\n".join(
            [
                f'<rect x="{xa:.1f}" y="{y0 + max_h - ha:.1f}" width="{bw}" height="{ha:.1f}" rx="5" fill="#8a9096"/>',
                f'<rect x="{xb:.1f}" y="{y0 + max_h - hb:.1f}" width="{bw}" height="{hb:.1f}" rx="5" fill="#6fbf94"/>',
                f'<text x="{xa + bw/2:.1f}" y="{y0 + max_h + 18:.1f}" text-anchor="middle" class="tick">Stock</text>',
                f'<text x="{xb + bw/2:.1f}" y="{y0 + max_h + 18:.1f}" text-anchor="middle" class="tick">Kestrel</text>',
                f'<text x="{xa + bw/2:.1f}" y="{y0 + max_h - ha - 8:.1f}" text-anchor="middle" class="val">{_esc(la)}</text>',
                f'<text x="{xb + bw/2:.1f}" y="{y0 + max_h - hb - 8:.1f}" text-anchor="middle" class="val">{_esc(lb)}</text>',
            ]
        )

    rss_panel = ""
    if stock_rss is not None and kest_rss is not None:
        # Lower RSS is better — show raw MB
        rss_panel = f"""
  <rect x="640" y="64" width="256" height="280" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="660" y="88" class="panel">Peak RSS (MB)</text>
  <text x="870" y="88" text-anchor="end" class="foot">lower is better</text>
  {pair(700, 120, 48, 160, stock_rss, kest_rss, "{:.1f}")}
"""
        pos_panel_w = 300
        wall_x = 340
    else:
        pos_panel_w = 420
        wall_x = 460
        rss_panel = ""

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img"
     aria-label="Measured fair bench: stock colibri vs Kestrel on glm_tiny">
  <defs>
    <style>
      .title {{ font: 700 20px ui-sans-serif, system-ui, sans-serif; fill: #1c2420; }}
      .sub {{ font: 400 12px ui-sans-serif, system-ui, sans-serif; fill: #5c6b63; }}
      .panel {{ font: 600 13px ui-sans-serif, system-ui, sans-serif; fill: #2a3530; }}
      .tick {{ font: 500 12px ui-sans-serif, system-ui, sans-serif; fill: #5c6b63; }}
      .val {{ font: 600 12px ui-monospace, Menlo, monospace; fill: #1c2420; }}
      .legend {{ font: 500 12px ui-sans-serif, system-ui, sans-serif; fill: #2a3530; }}
      .foot {{ font: 400 11px ui-sans-serif, system-ui, sans-serif; fill: #7a8780; }}
      .delta {{ font: 700 13px ui-monospace, Menlo, monospace; fill: #3d8f63; }}
    </style>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f4f6f4"/>
      <stop offset="100%" stop-color="#e8ece9"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#bg)" rx="12"/>
  <text x="{pad_l}" y="28" class="title">Measured fair bench · stock colibrì vs Kestrel</text>
  <text x="{pad_l}" y="48" class="sub">glm_tiny TF oracle · {batches}×{batch_size} procs/side interleaved · 32/32 · upstream { _esc(sha) }… · { _esc(ts) }</text>

  <rect x="24" y="64" width="{pos_panel_w}" height="280" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="44" y="88" class="panel">Prefill throughput (pos/s)</text>
  <text x="{24 + pos_panel_w - 16}" y="88" text-anchor="end" class="delta">+{d_pos:.0f}%</text>
  {pair(90 if pos_panel_w < 400 else 120, 120, 70 if pos_panel_w > 350 else 55, 160, stock_pos, kest_pos)}

  <rect x="{wall_x}" y="64" width="280" height="280" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="{wall_x + 20}" y="88" class="panel">Batch wall speed index</text>
  <text x="{wall_x + 264}" y="88" text-anchor="end" class="delta">{abs(d_wall):.0f}% faster</text>
  {pair(wall_x + 70, 120, 55, 160, wall_stock_idx, wall_kest_idx)}
  <text x="{wall_x + 140}" y="320" text-anchor="middle" class="foot">stock wall / measured wall × 100</text>
{rss_panel}

  <rect x="24" y="360" width="872" height="100" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="44" y="386" class="panel">Protocol (fully tested this run)</text>
  <text x="44" y="408" class="foot">• Identical glm_tiny + ref_glm.json · stripped env · no BENCH_LOOPS · ARCH=native OpenMP</text>
  <text x="44" y="426" class="foot">• Interleaved stock/kestrel batches · warmup discarded · Welch on batch means · both sides 32/32 oracle</text>
  <text x="44" y="444" class="foot">• Only this fixture is claimed. Full HF MoE checkpoints (Qwen/Kimi/…) are not fair-benched here.</text>

  <g transform="translate(44, 488)">
    <rect width="12" height="12" rx="2" fill="#8a9096"/>
    <text x="18" y="11" class="legend">Stock colibrì</text>
    <rect x="150" width="12" height="12" rx="2" fill="#6fbf94"/>
    <text x="168" y="11" class="legend">Kestrel (engine/kestrel-engine)</text>
    <text x="420" y="11" class="foot">Source: docs/full_bench.json · verify: python3 tools/verify_bench.py</text>
  </g>
</svg>
'''
    return svg


def main() -> int:
    data = json.loads(BENCH.read_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
