# Windhover engine benchmark

Host: Apple M4 · 16 GB · run 2026-10-17 22:24:02

| Model | Decode tok/s (base → new) | Chat-sampling tok/s | Long-prompt prefill tok/s | Prefill speed-up |
|---|---|---|---|---|
| Qwen__Qwen2.5-0.5B-Instruct | 113.7 → **128.3** | 37.1 → **126.4** | 166 → **598** | 3.61× |
| Qwen__Qwen3-1.7B | 30.4 → **31.7** | 17.6 → **29.0** | 33 → **138** | 4.17× |
| Qwen__Qwen3.5-0.8B | — → **59.8** | — → **50.7** | — → **304** | — |
| Qwen__Qwen3.5-2B | 2.9 → **25.1** | 2.7 → **26.7** | 3 → **157** | 54.10× |
| ibm-granite__granite-4.2-3b | 12.8 → **15.4** | 12.0 → **15.6** | 16 → **66** | 4.03× |

## Multi-turn chat (time to first token per turn)

**Qwen__Qwen2.5-0.5B-Instruct**

| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |
|---|---|---|---|---|---|
| 1 | 27 | 0 | 0.040 s | 0.040 s | 0.121 s |
| 2 | 146 | 122 | 0.038 s | 0.223 s | 0.539 s |
| 3 | 262 | 240 | 0.040 s | 0.428 s | 0.940 s |
| 4 | 378 | 357 | 0.042 s | 0.607 s | 1.272 s |
| 5 | 499 | 473 | 0.054 s | 0.925 s | 1.737 s |
| 6 | 616 | 594 | 0.051 s | 1.085 s | 2.133 s |

**Qwen__Qwen3-1.7B**

| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |
|---|---|---|---|---|---|
| 1 | 31 | 0 | 0.148 s | 0.241 s | 0.830 s |
| 2 | 150 | 27 | 0.851 s | 1.146 s | 3.142 s |
| 3 | 267 | 146 | 0.894 s | 1.962 s | 4.129 s |
| 4 | 383 | 263 | 0.920 s | 2.792 s | 4.965 s |
| 5 | 503 | 379 | 1.038 s | 3.766 s | 6.150 s |
| 6 | 620 | 499 | 1.152 s | 4.645 s | 7.089 s |

**Qwen__Qwen3.5-0.8B**

| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |
|---|---|---|---|---|---|
| 1 | 31 | 0 | 0.132 s | 0.090 s | — |
| 2 | 150 | 24 | 0.387 s | 0.510 s | — |
| 3 | 267 | 143 | 0.662 s | 0.898 s | — |
| 4 | 360 | 260 | 0.530 s | 1.276 s | — |
| 5 | 481 | 353 | 0.581 s | 1.479 s | — |
| 6 | 598 | 474 | 0.611 s | 1.927 s | — |

Baseline engine could not run this model: `engine exited: [wh] RoPE: rotary_dim=64/256 partial=0.250 attn_scale=1.0000
[wh] gdn qkv_rows 6144 exceeds mlp scratch 3584`

**Qwen__Qwen3.5-2B**

| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |
|---|---|---|---|---|---|
| 1 | 31 | 0 | 0.189 s | 0.198 s | 10.818 s |
| 2 | 150 | 24 | 0.924 s | 1.053 s | 50.914 s |
| 3 | 267 | 143 | 1.069 s | 1.836 s | 86.133 s |
| 4 | 382 | 260 | 0.941 s | 2.646 s | 107.651 s |
| 5 | 503 | 375 | 0.985 s | 3.524 s | 135.431 s |
| 6 | 620 | 496 | 0.914 s | 4.158 s | 174.009 s |

**ibm-granite__granite-4.2-3b**

| Turn | Prompt tok | Cached | New engine | Cache off | Baseline engine |
|---|---|---|---|---|---|
| 1 | 29 | 0 | 0.327 s | 0.390 s | 1.570 s |
| 2 | 140 | 27 | 1.690 s | 2.131 s | 8.638 s |
| 3 | 248 | 138 | 1.720 s | 3.720 s | 15.609 s |
| 4 | 356 | 246 | 1.797 s | 5.364 s | 21.535 s |
| 5 | 470 | 354 | 1.946 s | 7.340 s | 26.583 s |
| 6 | 582 | 468 | 2.029 s | 9.122 s | 33.456 s |

## Accuracy vs Hugging Face transformers (last-token logits, 5 prompts)

| Model | Reference | Engine | Top-1 match | Top-10 overlap | KL mean |
|---|---|---|---|---|---|
| Qwen__Qwen2.5-0.5B-Instruct | float32 | new | 4/5 | 0.88 | 0.1605 |
| Qwen__Qwen2.5-0.5B-Instruct | float32 | baseline | 4/5 | 0.84 | 0.2310 |
| Qwen__Qwen3-1.7B | float32 | new | 5/5 | 0.82 | 0.0311 |
| Qwen__Qwen3-1.7B | float32 | baseline | 4/5 | 0.86 | 0.0493 |
| Qwen__Qwen3.5-0.8B | float32 | new | 5/5 | 0.92 | 0.0211 |
| Qwen__Qwen3.5-0.8B | float32 | baseline | 0/0 | — | — |
| Qwen__Qwen3.5-2B | bfloat16 | new | 5/5 | 0.92 | 0.0065 |
| Qwen__Qwen3.5-2B | bfloat16 | baseline | 5/5 | 0.96 | 0.0045 |
| ibm-granite__granite-4.2-3b | bfloat16 | new | 5/5 | 0.84 | 0.0086 |
| ibm-granite__granite-4.2-3b | bfloat16 | baseline | 5/5 | 0.90 | 0.0128 |
