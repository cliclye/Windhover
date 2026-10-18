#!/usr/bin/env python3
"""Render README charts (light + dark SVG) from docs/bench/<run>/suite.json.

  python3 tools/render_bench_2026.py docs/bench/2026-10

Writes prefill.svg, decode.svg, ttft.svg (+ *-dark.svg) next to suite.json.
Baseline is drawn in a recessive neutral, the new engine in the accent hue;
every bar carries its value so identity is never colour-alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

THEMES = {
    "light": {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e6e5e0",
              "base": "#b9b7b0", "new": "#eb6834"},
    "dark": {"bg": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#33322f",
             "base": "#6b6a64", "new": "#d95926"},
}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

PRETTY = {
    "Qwen__Qwen2.5-0.5B-Instruct": "Qwen2.5 0.5B",
    "Qwen__Qwen3-1.7B": "Qwen3 1.7B",
    "Qwen__Qwen3.5-0.8B": "Qwen3.5 0.8B",
    "Qwen__Qwen3.5-2B": "Qwen3.5 2B",
    "ibm-granite__granite-4.2-3b": "Granite 4.2 3B",
}


def nice_max(v: float) -> tuple[float, float]:
    """Round an axis max up to a clean 4-tick scale; returns (max, step)."""
    import math
    raw = max(v, 1e-9) / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step * 4, step


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bars(title: str, unit: str, rows: list[tuple[str, float | None, float | None]], t: dict,
         note: str = "") -> str:
    """Horizontal grouped bars: one group per model, baseline then new."""
    W, left, right, top = 760, 150, 70, 64
    bar_h, gap_in, gap_out = 14, 2, 18
    group_h = bar_h * 2 + gap_in
    H = top + len(rows) * (group_h + gap_out) + 30
    vmax, _ = nice_max(max([v for _, a, b in rows for v in (a, b) if v] + [1]) * 1.04)
    plot_w = W - left - right
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="{FONT}" role="img" aria-label="{esc(title)}">',
           f'<rect width="{W}" height="{H}" fill="{t["bg"]}" rx="10"/>',
           f'<text x="20" y="28" font-size="15" font-weight="600" fill="{t["ink"]}">{esc(title)}</text>',
           f'<rect x="{W - 250}" y="18" width="10" height="10" rx="2" fill="{t["base"]}"/>'
           f'<text x="{W - 235}" y="27" font-size="12" fill="{t["ink2"]}">v0.4.3 engine</text>'
           f'<rect x="{W - 140}" y="18" width="10" height="10" rx="2" fill="{t["new"]}"/>'
           f'<text x="{W - 125}" y="27" font-size="12" fill="{t["ink2"]}">this release</text>']
    if note:
        out.append(f'<text x="20" y="46" font-size="11.5" fill="{t["ink2"]}">{esc(note)}</text>')
    for i in range(5):
        x = left + plot_w * i / 4
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{H - 26}" stroke="{t["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{H - 10}" font-size="11" text-anchor="middle" fill="{t["ink2"]}">'
                   f'{vmax * i / 4:.0f}</text>')
    y = top
    for name, a, b in rows:
        out.append(f'<text x="{left - 12}" y="{y + group_h / 2 + 4:.1f}" font-size="12.5" text-anchor="end" '
                   f'fill="{t["ink"]}">{esc(name)}</text>')
        for k, (v, col) in enumerate(((a, t["base"]), (b, t["new"]))):
            yy = y + k * (bar_h + gap_in)
            if v:
                w = max(3.0, plot_w * v / vmax)
                out.append(f'<rect x="{left}" y="{yy}" width="{w:.1f}" height="{bar_h}" rx="3" fill="{col}"/>')
                label = f"{v:.0f} {unit}" if v >= 20 else f"{v:.1f} {unit}"
                weight = "600" if k else "400"
                out.append(f'<text x="{left + w + 6:.1f}" y="{yy + bar_h - 3}" font-size="11.5" '
                           f'font-weight="{weight}" fill="{t["ink"] if k else t["ink2"]}">{label}</text>')
            else:
                out.append(f'<text x="{left + 4}" y="{yy + bar_h - 3}" font-size="11.5" fill="{t["ink2"]}">'
                           f'cannot run this model</text>')
        y += group_h + gap_out
    out.append("</svg>")
    return "\n".join(out)


def lines(title: str, series: list[tuple[str, list[float], str]], t: dict, note: str = "") -> str:
    W, H, left, right, top, bottom = 760, 300, 60, 150, 60, 40
    n = max(len(s[1]) for s in series)
    vmax, _ = nice_max(max(v for _, vs, _ in series for v in vs) * 1.04)
    pw, ph = W - left - right, H - top - bottom
    X = lambda i: left + pw * i / max(1, n - 1)  # noqa: E731
    Y = lambda v: top + ph * (1 - v / vmax)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="{FONT}" role="img" aria-label="{esc(title)}">',
           f'<rect width="{W}" height="{H}" fill="{t["bg"]}" rx="10"/>',
           f'<text x="20" y="28" font-size="15" font-weight="600" fill="{t["ink"]}">{esc(title)}</text>']
    if note:
        out.append(f'<text x="20" y="46" font-size="11.5" fill="{t["ink2"]}">{esc(note)}</text>')
    for i in range(5):
        v = vmax * i / 4
        out.append(f'<line x1="{left}" x2="{W - right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{t["grid"]}"/>')
        out.append(f'<text x="{left - 8}" y="{Y(v) + 4:.1f}" font-size="11" text-anchor="end" fill="{t["ink2"]}">{v:.1f}s</text>')
    for i in range(n):
        out.append(f'<text x="{X(i):.1f}" y="{H - 16}" font-size="11" text-anchor="middle" fill="{t["ink2"]}">turn {i + 1}</text>')
    for name, vs, col in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(vs):
            out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{col}" stroke="{t["bg"]}" stroke-width="2"/>')
        out.append(f'<text x="{X(n - 1) + 10:.1f}" y="{Y(vs[-1]) + 4:.1f}" font-size="12" fill="{t["ink"]}">'
                   f'{esc(name)} · {vs[-1]:.2f}s</text>')
    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    run = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/bench/2026-10")
    suite = json.loads((run / "suite.json").read_text())
    models = suite["models"]

    def mode(tag, m):
        return ((models[tag].get("ab") or {}).get("modes") or {}).get(m, {}).get("summary", {})

    pre = [(PRETTY.get(k, k), mode(k, "long").get("a_prefill"), mode(k, "long").get("b_prefill")) for k in models]
    dec = [(PRETTY.get(k, k), mode(k, "chat").get("a_decode"), mode(k, "chat").get("b_decode")) for k in models]
    ttft_tag = "Qwen__Qwen3-1.7B" if "Qwen__Qwen3-1.7B" in models else next(iter(models))
    sv = models[ttft_tag].get("serve") or {}
    for name, t in THEMES.items():
        sfx = "" if name == "light" else "-dark"
        (run / f"prefill{sfx}.svg").write_text(bars(
            "Prompt processing (prefill), tokens / second", "tok/s", pre, t,
            "~700-token prompt · MacBook Air M4 16 GB · median of 3 · higher is better"))
        (run / f"decode{sfx}.svg").write_text(bars(
            "Chat generation speed (T=0.7, top-k 40, top-p 0.9)", "tok/s", dec, t,
            "128 new tokens · includes sampling · higher is better"))
        series = []
        if sv.get("baseline"):
            series.append(("v0.4.3 engine", [r.get("prefill_s") or 0 for r in sv["baseline"]], t["base"]))
        if sv.get("cache_on"):
            series.append(("this release", [r.get("prefill_s") or 0 for r in sv["cache_on"]], t["new"]))
        if series:
            (run / f"ttft{sfx}.svg").write_text(lines(
                f"Multi-turn chat: time to first token ({PRETTY.get(ttft_tag, ttft_tag)})", series, t,
                "full history re-sent every turn · prefix KV cache reuses earlier turns · lower is better"))
    print("wrote charts to", run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
