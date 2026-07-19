# Kestrel engine

Clean-slate CPU MoE runtime. Primary binary: `kestrel-engine`.

## Layout

| Path | Role |
|------|------|
| `io/` | safetensors, tokenizer, json headers |
| `memory/` | hard RAM budget (`budget.c`) |
| `runtime/engine.c` | forward / generate / TF oracle / CLI |
| `attn/` `moe/` `model/` `tensor/` | module boundaries for further splits |
| `fixtures/` | `glm_tiny` + `ref_glm.json` |

## Build & oracle

```bash
make ARCH=native
make test-oracle   # expect 32/32
```

Attribution: numerics lineage documented in repo-root `UPSTREAM.md` (Apache-2.0).
