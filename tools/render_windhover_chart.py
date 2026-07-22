#!/usr/bin/env python3
"""Render Windhover real-model decode chart from docs/windhover_bench.json + dense baseline."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WH = ROOT / "docs" / "windhover_bench.json"
DENSE = ROOT / "docs" / "dense_qwen_bench.json"
OUT = ROOT / "docs" / "screenshots" / "bench-windhover-real.svg"


def main() -> int:
    wh = json.loads(WH.read_text())
    dense = json.loads(DENSE.read_text()) if DENSE.is_file() else {}
    m15 = wh["models"]["1.5b"]["windhover"]
    m7 = wh["models"]["7b"]["windhover"]
    without_15 = (dense.get("without") or {}).get("mean_tok_s") or 20.6
    decode_15 = m15["mean_decode_tok_s"]
    decode_7 = m7["mean_decode_tok_s"]
    rss_15 = m15["mean_rss_gb"]
    rss_7 = m7["mean_rss_gb"]
    d15 = 100.0 * (decode_15 - without_15) / without_15

    def bar(x, y, w, h, fill):
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h:.1f}" rx="5" fill="{fill}"/>'

    # Scale bars to max decode among shown
    max_d = max(without_15, decode_15, decode_7)
    H = 160

    def h_for(v):
        return H * (v / max_d)

    y0 = 120
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="920" height="420" viewBox="0 0 920 420" role="img"
     aria-label="Windhover real-model decode on MacBook Air M4 16GB">
  <defs>
    <style>
      .title {{ font: 700 20px ui-sans-serif, system-ui, sans-serif; fill: #1c2420; }}
      .sub {{ font: 400 12px ui-sans-serif, system-ui, sans-serif; fill: #5c6b63; }}
      .panel {{ font: 600 13px ui-sans-serif, system-ui, sans-serif; fill: #2a3530; }}
      .tick {{ font: 500 11px ui-sans-serif, system-ui, sans-serif; fill: #5c6b63; }}
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
  <rect width="920" height="420" fill="url(#bg)" rx="12"/>
  <text x="48" y="28" class="title">Windhover · real models on M4 16GB</text>
  <text x="48" y="48" class="sub">Decode-only tok/s · greedy · measured docs/windhover_bench.json · transformers CPU baseline for 1.5B</text>

  <rect x="24" y="64" width="560" height="280" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="44" y="88" class="panel">Decode tok/s</text>
  <text x="560" y="88" text-anchor="end" class="delta">1.5B +{d15:.0f}%</text>

  {bar(70, y0 + H - h_for(without_15), 52, h_for(without_15), "#8a9096")}
  {bar(134, y0 + H - h_for(decode_15), 52, h_for(decode_15), "#6fbf94")}
  {bar(250, y0 + H - h_for(decode_7), 52, h_for(decode_7), "#6fbf94")}

  <text x="96" y="{y0 + H + 18}" text-anchor="middle" class="tick">1.5B without</text>
  <text x="160" y="{y0 + H + 18}" text-anchor="middle" class="tick">1.5B Windhover</text>
  <text x="276" y="{y0 + H + 18}" text-anchor="middle" class="tick">7B Windhover</text>

  <text x="96" y="{y0 + H - h_for(without_15) - 8}" text-anchor="middle" class="val">{without_15:.1f}</text>
  <text x="160" y="{y0 + H - h_for(decode_15) - 8}" text-anchor="middle" class="val">{decode_15:.1f}</text>
  <text x="276" y="{y0 + H - h_for(decode_7) - 8}" text-anchor="middle" class="val">{decode_7:.1f}</text>

  <text x="400" y="140" class="panel">RSS</text>
  <text x="400" y="168" class="val">1.5B → {rss_15:.2f} GB</text>
  <text x="400" y="190" class="foot">was 6.18 GB without</text>
  <text x="400" y="222" class="val">7B → {rss_7:.2f} GB</text>
  <text x="400" y="244" class="foot">was ~9 GB / swap-bound without</text>
  <text x="400" y="280" class="foot">FFN sparsity ~23% / ~26%</text>
  <text x="400" y="300" class="foot">KPK mmap · int8 KV · CATS</text>

  <rect x="600" y="64" width="296" height="280" rx="10" fill="#ffffff" stroke="#d5ddd7"/>
  <text x="620" y="88" class="panel">Honest notes</text>
  <text x="620" y="120" class="foot">• Same MacBook Air M4 16GB</text>
  <text x="620" y="142" class="foot">• 7B without was ~0.01 tok/s</text>
  <text x="620" y="164" class="foot">  (swap) — not a fair %</text>
  <text x="620" y="186" class="foot">• Prefer ≤3–4B for snappy chat</text>
  <text x="620" y="208" class="foot">• Re-run: ./windhover bench</text>
  <text x="620" y="230" class="foot">  --windhover</text>
  <text x="620" y="270" class="foot">Source JSON:</text>
  <text x="620" y="290" class="foot">docs/windhover_bench.json</text>
  <text x="620" y="310" class="foot">docs/dense_qwen_bench.json</text>

  <g transform="translate(44, 380)">
    <rect width="12" height="12" rx="2" fill="#8a9096"/>
    <text x="18" y="11" class="legend">Without (transformers CPU)</text>
    <rect x="240" width="12" height="12" rx="2" fill="#6fbf94"/>
    <text x="258" y="11" class="legend">With Windhover (KPK)</text>
  </g>
</svg>
'''
    OUT.write_text(svg)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
