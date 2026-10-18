# Windhover engine benchmark — October 2026

Baseline = `windhover-engine` built from `main` at v0.4.3 (`ee55e60` + the
merged warm-engine PRs). New = this branch. Same machine, same packs, same
prompts, binaries interleaved run-by-run (A/B, then B/A) so thermal drift and
background load hit both equally. Medians of 3 runs unless noted.

Machine: MacBook Air **M4** (4P + 6E cores) · **16 GB** · macOS 27.2 · on battery-free
desk power with normal desktop apps open (Chrome, Claude, etc.) — i.e. a real
laptop, not an idle benchmark box. Absolute numbers move ±10% run to run;
ratios are stable.

## What is measured

| Harness | What | Notes |
|---|---|---|
| `tools/engine_ab.py` | decode tok/s (greedy, 128 tokens), chat-sampling decode (T=0.7, top-k 40, top-p 0.9), long-prompt prefill (~700-token prompt) | also dumps last-position logits from both binaries → top-1 / KL drift |
| `tools/serve_bench.py` | 6-turn chat over the warm `SERVE=1` engine, full history re-sent each turn (what the app does) | prefill seconds per turn with the prefix cache on, off, and on the baseline engine; checks greedy replies are identical with cache on/off |
| `tools/hf_parity.py` | last-token logits vs Hugging Face `transformers` (f32 for ≤2B, bf16 above) on 5 chat prompts | the accuracy number that matters for a quantized runtime |

Re-run everything with:

```bash
python3 tools/bench_suite.py --baseline /path/to/v0.4.3/windhover-engine \
  --engine engine/windhover-engine --out docs/bench/2026-10 --parity \
  --model ~/.windhover/models/Qwen__Qwen3-1.7B --model ~/.windhover/models/Qwen__Qwen3.5-2B
```

Raw results: `suite.json`, `ab_*.json`, `serve_*.json`, `parity_*.json`.
Table: [`SUMMARY.md`](SUMMARY.md).
