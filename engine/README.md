# Windhover engine

Clean-slate CPU runtime. Primary binary: `windhover-engine` (`kestrel-engine` symlink kept for older scripts).

- **WMIR** (`kestrel.json` → `windhover.wmir`) — architecture-agnostic layer graph; packers lower HF configs via `tools/wmir/`
- **Dense / Windhover KPK** — GQA (+ KV share, linear GDN, chunked/CSA/MSA windows), SwiGLU/GELU/double-wide MLP
- **GLM MoE** (`glm_moe_dsa`) — MLA + streamed experts (oracle: `fixtures/glm_tiny`); other MoE families emit WMIR + stream markers
- **Families:** qwen2 · qwen3 · **qwen3.5 / 3.6 / 3.8 (Gated DeltaNet hybrid)** · llama (incl. MiniCPM5) · mistral · **granite** · gemma2/3/4 · phi3

## Performance architecture (dense KPK path)

| Stage | Kernel |
|---|---|
| Prefill GEMM (q/k/v/o/gate/up/lm) | `prefill_gemm.h` — 4×4 SDOT register tiles, int4 rows unpacked once per block |
| Prefill down^T | transposed int8 panels + hi/lo int8 activations per 64-group (~15-bit), ragged tail padded into the tile |
| Decode GEMV | row-parallel SDOT (int8 / int4-g64) |
| Decode down^T | int8 × int16-coefficient MLAL blocks, 64-wide output chunk in registers |
| Gated DeltaNet | batched projections, conv parallel over channels, recurrence parallel over heads |
| Sampling | size-k heap + nucleus over survivors |
| Multi-turn | prefix KV cache (`SERVE=1`), GDN state snapshot at the last role-start token |

Debug switches: `WH_PREFILL_TILED=0` (GEMV prefill), `WH_PREFIX_CACHE=0`, `WH_GDN_REF=1` (original per-token GDN), `WH_PROF=1` (per-stage timers).

## Layout

| Path | Role |
|------|------|
| `io/` | safetensors, tokenizer, json headers |
| `memory/` | hard RAM budget (`budget.c`) |
| `runtime/wmir.h` | WMIR schema + loader |
| `runtime/engine.c` | MoE forward / generate / TF oracle / CLI |
| `runtime/dense.c` | dense path (`WH=0`) |
| `runtime/windhover.c` | KPK Windhover runtime (WMIR interpreter) |
| `attn/` `moe/` `model/` `tensor/` | module boundaries for further splits |
| `fixtures/` | `glm_tiny` + `ref_glm.json` |

## Build & oracle

```bash
make ARCH=native
make test-oracle   # expect 32/32

# Dense / Windhover example (after ./windhover pull … --weights && convert):
SNAP=~/.windhover/models/Qwen__Qwen2.5-Coder-1.5B-Instruct/kpk \
  PROMPT='Say hi' NGEN=32 ./windhover-engine 64 4 4
```

Attribution: Apache-2.0 — see repo-root [LICENSE](../LICENSE).
