<p align="center">
  <img src="docs/screenshots/icon.png" alt="Kestrel" width="96" height="96" />
</p>

<h1 align="center">Kestrel</h1>

<p align="center">
  <strong>Local MoE runtime for macOS</strong> — a faster CPU engine on the same laptop, plus Library, Chat, and a folder-scoped Agent.
</p>

<p align="center">
  <a href="#performance">Performance</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#mac-app">Mac app</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#license">License</a>
</p>

---

**Kestrel** is a clean-slate product for running open Mixture-of-Experts models on your machine. It ships:

- **`kestrel-engine`** — modular CPU MoE runtime (primary binary under [`engine/`](engine/))
- **Mac app** — Tauri shell around Library · Chat · Agent · Advanced
- **CLI** — `./kestrel build | pull | app | chat | oracle`

Numerics lineage (Apache-2.0) is documented in [UPSTREAM.md](UPSTREAM.md). Kestrel is a separate product: the ship engine is **`engine/kestrel-engine`**.

---

## Screenshots

### Library

Browse GLM, Qwen, Kimi, DeepSeek, Mistral, and Llama. Install / uninstall locally; everything is tagged for `kestrel-engine`.

![Kestrel Library](docs/screenshots/library.png)

### Chat

Markdown replies, a thinking indicator, and per-message speed / RSS chips. Model selection routes to the active catalog pack (family-aware chat weights until a full MoE convert lands).

![Kestrel Chat](docs/screenshots/chat.png)

### Advanced

Live telemetry: process RSS, latency, tok/s, selected model, backend, and the family → chat-model map.

![Kestrel Advanced](docs/screenshots/advanced.png)

---

## Performance

### Important: what `glm_tiny` is

**`glm_tiny` is not a real language model.** It is a synthetic ~2 MB teacher-forcing oracle fixture (`vocab_size=256`, `hidden_size=128`, 5 tiny layers) used to prove numerics / scheduling and to compare the baseline engine path vs `kestrel-engine` on the **same laptop**. It is **not** GLM-5.2, Kimi K2.6, or any Hugging Face checkpoint.

### Same laptop · without Kestrel vs with Kestrel (micro-fixture)

Measured on that synthetic `glm_tiny` oracle only:

- **12 batches × 40 processes per side**, warmup discarded, interleaved A/B
- Both sides **32/32** oracle

Full dump: [`docs/full_bench.json`](docs/full_bench.json). Chart: [`docs/screenshots/bench-without-vs-with-kestrel.svg`](docs/screenshots/bench-without-vs-with-kestrel.svg).

```bash
python3 tools/full_bench.py          # micro-fixture protocol → docs/full_bench.json
python3 tools/render_bench_chart.py
python3 tools/verify_bench.py
```

![Without Kestrel vs with Kestrel](docs/screenshots/bench-without-vs-with-kestrel.svg)

| Metric (batch means) | Without Kestrel | With Kestrel | Δ |
|---|---:|---:|---:|
| Prefill throughput (pos/s) | 11 978 | 77 563 | **+548%** |
| 95% CI (pos/s) | 11 587–12 370 | 76 721–78 404 | non-overlap |
| Batch wall (s) | 0.297 | 0.178 | **−40%** (faster) |
| Peak RSS (MB) | 5.83 | 5.20 | lower |
| Oracle correctness | 32/32 | 32/32 | match |

Welch on batch-mean pos/s is decisive on this fixture. **Do not** treat these % as tok/s claims on GLM-5.2 or Kimi.

### Frontier MoE benches (GLM-5.2 / Kimi K2.6 / K2.7 Code)

To fair-bench a **real** model the same way (without vs with `kestrel-engine` on this laptop) you need:

1. Free disk for the HF download (~**600–756 GB**) plus convert room  
2. `./kestrel pull <id> --weights` then FP8→int4 convert where required  
3. `KESTREL_SNAP=<converted_dir> python3 tools/real_model_bench.py`

| Model | Approx download | Status on this repo / typical Mac |
|---|---:|---|
| **GLM-5.2** (`zai-org/GLM-5.2-FP8`) | ~756 GB | **Not run** — needs download + convert |
| **Kimi K2.6** / **K2.7 Code** | ~600 GB | **Not run** — needs download + convert |
| `glm_tiny` | ~0.002 GB | Measured above — **synthetic only** |

```bash
python3 tools/real_model_bench.py   # prints requirements; writes docs/real_model_bench.json
# After you have a converted SNAP:
KESTREL_SNAP=~/.kestrel/models/<converted> python3 tools/real_model_bench.py
```

Until a real SNAP exists locally, we **publish no invented GLM/Kimi speedups**. Status file: [`docs/real_model_bench.json`](docs/real_model_bench.json).

### Real model · Qwen2.5-7B Instruct (same laptop)

Installed and measured on a **MacBook Air M4 16 GB** (same machine as above):

| | Without Kestrel | With Kestrel |
|---|---|---|
| Path | stock `transformers` · **CPU** · float16 | Kestrel Mac preview · **MPS** · float16 |
| Download | ~15.2 GB HF weights | same local SNAP |
| Decode tok/s | **~0.013** | **~0.008** |
| Peak RSS | ~9.0 GB | ~9–10 GB |
| `kestrel-engine` | — | **does not load** (dense Qwen ≠ GLM MoE SNAP) |

Full dump: [`docs/qwen7b_bench.json`](docs/qwen7b_bench.json).

```bash
./kestrel pull Qwen/Qwen2.5-7B-Instruct --weights
python3 tools/qwen7b_bench.py
# or: ./kestrel bench --qwen
```

**Honest takeaway:** on 16 GB unified memory with a normal desktop session open, **Qwen2.5-7B fp16 is memory/swap-bound** — both sides land near **~0.01 tok/s**, so this is **not** a throughput win to advertise. Prefer ≤3–4B on this class of Mac, quit other apps / free RAM before 7B, or use a larger machine. Engine speedups in the micro-fixture section still apply only to the GLM MoE `kestrel-engine` path.

### Laptop-limit stress (synthetic MoE · pushes this machine)

On a **MacBook Air M4 16 GB**, a **synthetic** MoE stress SNAP (`kestrel__glm-stress`, ~1.3 GB when present) was used for without/with `kestrel-engine` single-stream and concurrent soak. See [`docs/laptop_limit_bench.json`](docs/laptop_limit_bench.json) (single-stream: without ~201 tok/s, with ~185 tok/s, Δ **−7.7%** on that fixture).

```bash
./kestrel bench --laptop
```

This is still **not** a frontier MoE claim.

**What moved the needle on the micro-fixture (engine)**

- Batched `lm_head` on the TF path  
- DSA short-context skip where the baseline path still indexes every layer  
- Attention / MoE / dense scratch reuse (`model_ws`, `attn_ws`)  
- Lean TF path (skip unused DSA load, quieter I/O, clamped expert capacity)  
- Hand NEON f32 matmul (Accelerate was tried and reverted — better internal pos/s, worse process wall + RSS)

---

## How it works

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Mac app /  │────▶│  ./kestrel   │────▶│  kestrel-engine  │
│  Library UI │     │  app :8000   │     │  SNAP=model dir  │
└─────────────┘     └──────────────┘     └──────────────────┘
                           │
                           ├─ /v1/catalog      curated models
                           ├─ /api/pull        install runner pack
                           ├─ /api/uninstall   remove local pack
                           ├─ /v1/chat/...     generate
                           ├─ /api/workspace   Agent folder root
                           ├─ /api/agent       local tool loop (list/read/write)
                           └─ /api/stats       RSS · tok/s · routing
```

1. **Library** lists open MoE families (GLM, Qwen, Kimi, DeepSeek, Mistral, Llama) plus a **Mac 16GB** filter.  
   - **Kestrel Chat Preview** — honest small on-device chat (SmolLM2).  
   - **Mac 16GB** — small HF instruct models under ~20GB (Qwen2.5/3, SmolLM2 1.7B, Phi-3.5, Gemma 2 2B, TinyLlama, R1-distill). Install downloads real weights.  
   - **Download weights** — real Hugging Face download for frontier MoEs (confirms size); **never** installs a tiny stub labeled as Kimi/Qwen/etc.  
2. **Chat** only lists installs that are actually chat-capable. Requesting an uninstalled id (e.g. K2.6) returns an error — it will **not** silently use another model.  
3. **Agent** — pick a folder on disk; a local model can list/read/edit files under that root only (Cursor-style, fully on-device). Prefer a small coder (e.g. Qwen2.5-Coder-1.5B) on 16GB Macs.  
4. **Advanced** samples live RSS, latency, tok/s, and the true backend / weights path.  
5. **Hard RAM ceiling** — engine budget path (`RAM_GB` / `COLI_HARD_CAP`) for production snaps.

---

## Mac app

Bundle ID: `ai.vexilo.kestrel`

```bash
./kestrel build
cd app && npm ci && npm run build && cd ..
cd desktop && cargo tauri build --bundles app,dmg
open desktop/src-tauri/target/release/bundle/macos/Kestrel.app   # or debug/ after --debug
```

Dev loop:

```bash
cd desktop && cargo tauri dev
```

The app starts (or reuses) `./kestrel app` on `http://127.0.0.1:8000` and loads the UI there. Prefer the project venv (`c/.venv`) so Chat previews have `torch` / `transformers`.

See also [`desktop/README.md`](desktop/README.md).

---

## Quick start

### CLI

```bash
git clone <your-fork-or-repo> && cd Kestrel
./kestrel build
./kestrel oracle                          # TF 32/32 self-test
./kestrel pull kestrel/glm-tiny-demo      # demo runner
./kestrel app                             # Library + Chat + API on :8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) or the Mac `.app`.

### Chat from the shell

```bash
./kestrel pull Qwen/Qwen3-30B-A3B-Instruct-2507
./kestrel chat --model ~/.kestrel/models/Qwen__Qwen3-30B-A3B-Instruct-2507 \
  --prompt "Hello" --ngen 64
```

### Uninstall a model

```bash
./kestrel uninstall Qwen/Qwen3-30B-A3B-Instruct-2507
# or use Uninstall in Library
```

### Fair bench (same laptop)

```bash
./kestrel bench              # synthetic glm_tiny micro-fixture (not a real model)
./kestrel bench --smoke
./kestrel bench --qwen       # Qwen2.5-7B without/with Mac preview (needs pull)
./kestrel bench --laptop     # glm_stress single-stream + concurrent soak (16GB class)
./kestrel bench --real       # GLM-5.2 / Kimi — needs KESTREL_SNAP + hundreds of GB free
```

Micro-fixture numbers: [`docs/full_bench.json`](docs/full_bench.json).  
Qwen2.5-7B: [`docs/qwen7b_bench.json`](docs/qwen7b_bench.json).  
Laptop-limit: [`docs/laptop_limit_bench.json`](docs/laptop_limit_bench.json), [`docs/laptop_soak_bench.json`](docs/laptop_soak_bench.json).  
Frontier status: [`docs/real_model_bench.json`](docs/real_model_bench.json).

---

## Layout

| Path | Role |
|------|------|
| [`engine/`](engine/) | Product CPU MoE engine → `kestrel-engine` |
| [`kestrel`](kestrel) | CLI + Library/Chat HTTP API |
| [`app/`](app/) | Vite/React UI (Library · Chat · Advanced) |
| [`desktop/`](desktop/) | Tauri macOS app |
| [`c/`](c/) | Reference convert / plan helpers (not the ship binary) |
| [`docs/`](docs/) | Benches, screenshots, notes |
| [`UPSTREAM.md`](UPSTREAM.md) | License / numerics lineage pin |

---

## Models

Catalog (`app/public/catalog.json`) tracks:

- **Mac 16GB (≤20GB)** — SmolLM2 1.7B, Qwen2.5 0.5B–7B, Qwen3 0.6B–4B, TinyLlama, Phi-3.5 Mini, Gemma 2 2B, DeepSeek R1 Distill 1.5B  
- **GLM** — Tiny demo, 5.2 / 5.1 FP8, 4.7 Flash  
- **Qwen** — 30B-A3B / 235B-A22B Instruct 2507, Qwen3 Coder  
- **Kimi** — K2.7 Code, K2.6, K2 Thinking  
- **DeepSeek** — V3.2, V3.2 Exp  
- **Mistral** — Magistral Small  
- **Llama** — 4 Maverick, 4 Scout  

Install is honest: **Chat Preview** / **Mac 16GB** models download real small HF weights (≤20GB); frontier MoEs require an explicit **Download weights** (~tens–hundreds of GB). Chat never pretends a stub is Kimi/Qwen/etc.

---

## Requirements

- macOS 12+ (Apple Silicon recommended)  
- Xcode CLT, Rust (for Tauri), Node 18+  
- Python 3.10+ with `torch` + `transformers` for Chat preview (`c/.venv` recommended)  
- Optional: Hugging Face CLI for `--weights` pulls  

---

## License

Apache-2.0 — see [LICENSE](LICENSE). Upstream attribution in [UPSTREAM.md](UPSTREAM.md).
