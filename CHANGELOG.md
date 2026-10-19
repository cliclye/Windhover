# Changelog

## [0.6.0] — 2026-10-19

### Smoother everything
- Replies stream in smoothly: text is revealed a few characters per frame (faster when the model gets ahead) with a soft caret, new paragraphs and list items fade in, and the thread stays pinned to the bottom unless you scroll up to read. The Code agent's replies stream the same way. A half-streamed `**bold` no longer flashes raw asterisks.
- Motion across the app: views fade up on tab switch, messages, tool rows and banners slide in, the welcome screen and starters animate in sequence, buttons/cards/inputs ease their hover and press states, the sidebar collapses softly, and modals use gentler easing. Reduced-motion settings turn it all off.

### Math and headings render cleanly
- LaTeX in replies (`$e^x$`, `$$\frac{d}{dx}…$$`, `\(…\)`, `\[…\]`) is converted to italic unicode math (`eˣ`, `d/dx(eˣ)`, `α/2`, `√(b²−4ac)`, `≤`) instead of showing raw `$` and backslashes; prices like "$5 and $10" are left alone, and code is never touched. `#` headings render as bold lines.

### Chat stopped mid-answer on math
- The "keyboard smash" early stop (engine, server and UI copies) treated LaTeX and equations — `\\frac{1}{2}`, `$u(x) =`, `f'(x) = cos^2(x)` — as gibberish and cut answers off mid-derivation. Text with LaTeX commands, `$`, or `=` with parentheses is never counted as smash; real keyboard smash is still caught.
- Chat replies may now run to 2048 tokens (was 512, server cap 1024), so long step-by-step solutions reach the final answer.

### Images (vision)
- Paste, drop or attach images in **Chat** and **Code**. Qwen3.5 packs see them through their own vision encoder, run locally in numpy (`tools/vision_qwen35.py`); output matches `transformers` (cosine ≥ 0.99999).
- Engine: new serve flag (bit 1) followed by an image block. Embeddings are placed at `<|image_pad|>` slots, and full-attention layers use interleaved M-RoPE (3D positions) when an image is present; text-only requests keep the old path. Image slots carry hash-derived ids, so the prefix cache reuses the same picture across turns (260/267 tokens cached on the second turn in our test).
- Ollama vision models receive images too (`image_url` parts / `images`). Models without a vision encoder say so instead of guessing.
- Saved chats store thumbnails only; the sidecar now bundles Pillow.

### Code — does the work instead of describing it
- The agent saves files and runs commands itself. A reply that pastes a whole file, or tells you to run something yourself, is sent back with a nudge to use its tools. The system prompt also shows how to open a page or serve a folder on localhost.
- `run` can keep long-running commands going in the background (dev servers, `http.server`, `npm run dev` … are detected automatically). Servers started on Windhover's port 8000 are moved to a free port, and later `localhost:8000` URLs are rewritten to match. Background processes stop with the session or the app.
- A reply that runs out of tokens in the middle of a file is never saved; the agent is asked to write it in parts. Per-step budgets went up (Low 2048, Medium–Max 4096 tokens), so a whole page fits in one step.
- Stuck detection: after three fruitless steps (repeated reads, empty searches, errors) the agent gets the current file and is told to make the fix. Repeated reads run again once their earlier result has been compacted out of the context; a `write_file` that changes nothing is reported as such.
- The panel shows compact step rows ("Created index.html, ran `open index.html` +236 −0", expandable) and a live "Writing index.html… 120 lines" row instead of streaming code. Long code blocks in replies fold into one line.

### Code — permission modes, effort, edit approval
- Permission modes like Claude Code: *Ask before edits* (diff preview, Apply / Reject), *Accept edits*, *Plan mode* (read-only, ends with a plan), *Bypass permissions*. ⇧Tab cycles them; changes apply to a running session.
- Effort *Low / Medium / High / Max*: 768 → 4096 tokens per step and 10 → 50 steps; *High* and *Max* turn on the model's thinking, shown as a collapsible "Thought for Ns". Thoughts are kept out of the conversation history.
- The file the agent edits opens in the editor; open clean files refresh after agent edits.

### Desktop window (macOS)
- Quitting the app (⌘Q) now stops its server sidecar and engine (whole process group). Before, they kept running and held port 8000.
- The overlay title bar no longer covers the sidebar. A 52 px title strip holds the traffic lights and lines up with the top bar. Dragging and double-click-to-zoom on the title areas work through the window plugin (WKWebView ignores `-webkit-app-region`), and the remote page is granted only those window permissions.

### New logo
- Replaced the kestrel silhouette with a new mark: two swept copper wing blades that cross into a W. App, desktop (macOS, Windows), site and README icons and screenshots updated.

### Code — a local coding agent
- New **Code** section (replaces Agent): project explorer, tabbed editor with save, and an agent panel that reads, searches, edits and tests code using the model Windhover is running (or an Ollama model) — no API key.
- Tools: `list_dir`, `read_file`, `search`, `edit_file`, `write_file`, `run`. Edits show diffs and can be undone; `run` asks for approval unless *Auto-run commands* is on (90 s timeout). File tools can't leave the folder.
- Handles how small models actually write tool calls: ```` ```tool ```` JSON, `TOOL … END` blocks, Qwen XML `<tool_call>`, bare JSON. Edits that don't match exactly fall back to a whitespace-tolerant match, and a failed edit sends the current file back to the model. Wiping a file or deleting more than 3 lines with an empty replacement is refused. A model that only narrates its next step, or returns nothing, is asked to continue instead of ending the turn.
- The system prompt is fixed for the session so the engine's prefix KV cache is reused between agent steps.
- Engine: optional serve flag / `WH_NO_GIBBERISH=1` turns off the keyboard-smash early stop, so code output (lots of symbols) is never cut. The server's default context is now 8192 (`WINDHOVER_CTX`).
- Evaluation (feature + test, question, bug fix, follow-up; results checked on disk): Qwen3.5 4B 8/8, Qwen3.5 2B 7/8.

## [0.5.0] — 2026-10-18

### Highlights
- **Prompts 3.6–4.3× faster** on dense models; **multi-turn chat** time-to-first-token **6–40× lower** (prefix KV cache), ~190× on Qwen3.5-2B.
- **2026 models:** Qwen3.5 (0.8B / 2B / 4B), Granite 4.2 (3B / 8B), MiniCPM5 2B, Qwen3.8 27B — Qwen3.5 is now correct and ~10× faster to generate.
- **Redesigned app:** saved chats, Models with fit-for-this-Mac/PC hints, a live Performance view, light/dark themes.
- Accuracy checked against Hugging Face `transformers` on every benchmarked model — equal or better than 0.4.3. Benchmarks: [`docs/bench/2026-10`](https://github.com/cliclye/Windhover/tree/main/docs/bench/2026-10).

### Engine — faster prefill, prefix cache, new architectures
- **Tiled int8 prefill GEMM** (`engine/runtime/prefill_gemm.h`): 4 rows × 4 tokens SDOT micro-tiles with pairwise-add reductions; int4-g64 rows are unpacked once per block instead of once per token. Prompt processing is **3.6–4.3× faster** on dense models (Qwen3-1.7B ~700-token prompt: 33 → 138 tok/s on a throttling M4 Air; see `docs/bench/2026-10`).
- **Tiled down^T for prefill:** transposed int8 panels per 64-column block with the row scale folded into the activations, quantized as a **hi/lo int8 pair per 64-group** (~15-bit; single-plane int8 cost KL ≈ 0.1). The ragged tail is padded into the same tile so prompt numerics no longer depend on chunking.
- **Decode down-projection:** int8 × int16-coefficient MLAL block kernel with the 64-wide output chunk held in registers (was one f32 axpy per row) — the only compute-bound decode matmul; ~30% faster.
- **Prefix KV cache across turns (SERVE mode):** each chat turn reuses the KV of the longest shared token prefix and only prefills the new suffix. Hybrid (GDN) models snapshot the recurrent + conv state at the last role-start token so the next turn resumes from there. Turn-6 time-to-first-token is 6–40× lower than v0.4.3 on dense models; greedy replies are identical with the cache on or off. `WH_PREFIX_CACHE=0` disables it.
- **Qwen3.5 / Qwen3.6 / Qwen3.8 (Gated DeltaNet) rewritten:** batched int8 projections over all prompt tokens, conv parallel over channels, recurrence parallel over heads with a two-pass row-wise state update — Qwen3.5-2B **~10× decode, ~54× prefill** vs v0.4.3.
- **Qwen3.5 correctness fixes:** zero-centred RMSNorm `x·(1+w)` (was `x·w`, producing blank output), q/gate rows split **per head** as in `transformers` (old packs are repaired at load), and scratch sized for GDN projections wider than the MLP (Qwen3.5-0.8B previously aborted on load).
- **IBM Granite 4.x support:** `embedding_multiplier`, `attention_multiplier`, `residual_multiplier`, `logits_scaling` in the descriptor, WMIR lowerer and forward pass.
- **Sampling:** top-k via a size-k heap and nucleus over the k survivors (was k full vocabulary passes + 24 bisection passes — several ms per token at chat temperatures); vectorized argmax.
- **Early-stop heuristic** no longer treats Markdown (`* _ # \` | -`) and apostrophes as keyboard smash — bold/list answers were being cut mid-sentence (engine, server and UI copies).
- Engine stats now report `prompt_tokens`, `cached_tokens` and `prefill_s`; server replies may run up to 1024 tokens (was 256).

### Models
- New in the catalog: **Qwen3.5 0.8B / 2B / 4B**, **Granite 4.2 3B / 8B**, **MiniCPM5 2B**, **Qwen3.8 27B**, **DeepSeek V4 Flash (0731)**. Entries carry release date, parameter count and a recommended flag; 2024-era packs are tagged legacy.
- Chat-template fallback detects the format from the pack's own template (MiniCPM5 and Granite speak ChatML despite `llama`/`granite` model types) and applies the family's "thinking off" suffix.

### App — redesigned UI
- New layout: sidebar with **saved conversations** (local only), New chat, and Chat / Models / Agent / **Performance** / Settings.
- Chat: auto-growing composer, model picker with sizes, memory-profile switch, per-reply chips (tok/s, cached prompt tokens, prefill ms, RSS), copy, regenerate, starter prompts.
- Models: recommended picks for this machine's RAM, "fits / tight / needs" hints, release dates, cards with install progress, Hugging Face info dialog.
- Performance: live decode/prefill/TTFT/prefix-cache/RSS/bytes-per-token telemetry with per-turn history.
- Light/dark/system theme, keyboard shortcuts (⌘1–5, ⌘N, ⌘B), system fonts (no Google Fonts fetch), responsive down to narrow windows.

### Agent
- Tool calls in Qwen's XML style (`<path>calc.py`, `<parameter=path>…`, native `<tool_call><function=…>`) are parsed — Qwen3.5 previously failed every `read_file`.
- The agent keeps a bounded history of tool results instead of only the last one, skips read-only calls it already made, and asks for a final answer once it starts repeating; `read_file` on a directory points to `list_dir`. Qwen3.5-2B now answers "what does calc.py do?" in 6 steps instead of looping to the step limit.
- Tool syntax and duplicate summaries are hidden from the agent transcript.

### Tools
- `tools/engine_ab.py` (A/B speed + logit drift), `tools/serve_bench.py` (multi-turn prefix-cache bench), `tools/hf_parity.py` (accuracy vs `transformers`), `tools/bench_suite.py` (all of the above → `docs/bench/`).
- Release notes are generated from this changelog (`packaging/release_notes.py`); the Windows release body no longer carries stale 0.3.12 text.

### App
- **First run opens Library** (not Agent), remembers the last tab, and defaults the catalog filter to **16GB laptop**.
- **Windows/Mac copy:** badges and errors say 16GB laptop / this computer / desktop app — not “Mac 16GB” on Windows.
- First-launch status says **Starting Windhover…** while the sidecar boots instead of a false “engine offline.”
- Chat/Agent empty states send you to Library when no model is installed; first-reply copy mentions cold model load.
- Catalog: **Qwen2.5 1.5B Instruct** and **Qwen2.5 3B Instruct** (dense, chat after download).
- Trailing-fence cleanup no longer deletes real markdown code after a sentence (smash-fences still cut).
- Download links and the landing page point at `cliclye/Windhover` (old Kestrel URLs still redirect).

### Desktop
- Health probe requires Windhover’s `engine_present` field so an unrelated server on `:8000` is not reused.

### Performance
- **Warm `windhover-engine`:** Chat and Agent keep one SERVE process per loaded pack (KPK + dense). Tokens still stream; the process unloads on model switch, RAM-profile change, uninstall, or idle (~10 min). Cold mmap+init no longer runs every message.
- **Fast / Balanced / Low-RAM profiles** actually set `RAM_GB` (AU on when capped), `MLOCK`, and `WH_SPARSE`. Default **Balanced** on advertised ≤16 GB machines, including 16 GiB Macs (`bytes/1024**3`, not `bytes/1e9`). Chat shows the cap and a profile picker.

## [0.4.3] — 2026-07-24

### Fixed — macOS parity with Windows
- **Mac DMGs now ship sidecars:** `tauri.macos.conf.json` declares `externalBin` for `windhover-server` + `windhover-engine` (previously only Windows did). Release CI builds the engine + PyInstaller sidecar before `cargo tauri build`.
- **Bundled `libomp.dylib`:** Mac engine no longer depends on Homebrew `/opt/homebrew/.../libomp.dylib`; install name rewritten to `@loader_path` so chat works without brew.
- **Torch-free KPK convert on Mac:** same in-process numpy/safetensors Phi/Gemma path as Windows (`darwin` + frozen).
- **HF/tqdm quiet + UTF-8-safe stdio** on Mac packaged sidecars (same download crash class as Windows cp1252).
- **Longer first-launch health wait** on Mac (30s, was ~8s) and broader sidecar discovery under `.app/Contents`.
- Clears quarantine attrs on the engine (+ libomp) at sidecar start.

## [0.4.2] — 2026-07-24

### Fixed
- **Trailing gibberish after answers:** cuts keyboard-smash / code-fence junk after a finished sentence (server + UI), and the engine early-stops when that pattern appears mid-decode.
- **Chat sampling:** nucleus (`TOPP=0.9`) + `TOPK=40`, lower default temp (`0.35`) and max tokens (`256`) so short replies don’t fill the budget with nonsense.

### Performance
- **Spend RAM for speed:** `MLOCK=1` pins full FFN/attn weights when AU is off; larger prefill batch (`WH_PREFILL_S`/`WH_MAXS` 128).
- **Mac OMP uses P-cores only** (E-cores were lowering tok/s); mild `WH_SPARSE=25` on all platforms for chat.
- Greedy chat enables `WH_SPEC=1` when temperature is 0.

## [0.4.1] — 2026-07-24

### Fixed
- **Chat `TypeError: Failed to fetch`:** SSE responses were missing CORS headers required by the Tauri WebView (UI is not same-origin with `127.0.0.1:8000`). Streaming now sends `Access-Control-Allow-Origin`, and the UI falls back to non-stream chat if SSE still fails.

## [0.4.0] — 2026-07-24

### App
- **Chat no longer hangs on “thinking”:** desktop chat streams SSE tokens, drains engine stderr (no pipe deadlock), and enforces a wall-clock timeout. Stop cancels the in-flight request.
- **Thinking label** shows the active model name (`Phi-4 Mini is thinking…`) instead of “Windhover is thinking…”.
- **Library → More info** opens Hugging Face downloads/likes/params/tags and published model-index benchmarks (proxied via `/v1/model-info`).
- Qwen3/3.5 chat templates use `enable_thinking=False` so reply budget isn’t burned on hidden `<think>` blocks.

### Runtime
- **macOS parity:** OMP thread tuning (same idea as Windows) before spawning `windhover-engine`; silent in-app updates already replace `.app` and relaunch on Mac.
- Engine chat timeouts + stderr drain on stream path (Mac + Windows).

### Carry-forward from 0.3.15
- Silent Windows in-app updates (`/S /UPDATE /R`) and macOS DMG auto-replace.
- **Qwen3.5 9B · engine Q4** (`Qwen/Qwen3.5-9B`) via faithful GDN + gated attention KPK.

## [0.3.15] — 2026-07-24

### App — seamless in-app updates
- **Windows:** Update now runs the NSIS installer silently (`/S /UPDATE /R`) — no uninstall/reinstall wizard. The app closes, upgrades in place, and relaunches on the new version.
- **macOS:** Update now mounts the DMG, replaces `Windhover.app`, clears quarantine attrs, and relaunches automatically (no drag-to-Applications step).

### Engine — Qwen3.5 9B · engine Q4
- **Official `Qwen/Qwen3.5-9B`** is installable and chat-capable via windhover-engine (text-only KPK).
- Faithful **Gated DeltaNet** (recurrent) + **gated full-attention** (`q_proj` split + sigmoid gate), correct RoPE theta from `rope_parameters`.
- Catalog entry: **Qwen3.5 9B · engine Q4** (`engine_path: kpk`).

## [0.3.14] — 2026-07-24

### Performance — Windows Phi / Qwen tok/s (round 2)
- **AVX2 MLP `axpy_i4g_row` / `axpy_i8_row`:** decode was still scalar on the down^T FFN path after the previous IDOT fix; this is now vectorized (shared `idot_avx.h`).
- **AVX2 attention KV:** `kv_score` + `kv_axpy_v` use AVX2 int8 dots / axpy instead of scalar.
- **Dense path:** wire `wh_dot_i4i8_avx` + AVX exact f32×int8 for QKV (`matmul_q_exact_*`) so non-KPK Qwen is not stuck on scalar.
- **Prefill chunk** raised 64 → 80; Windows Chat defaults `WH_SPARSE=25` (set `WH_SPARSE=0` for full FFN quality).

## [0.3.13] — 2026-07-24

### Fixed — Windows tok/s + RAM (Phi / Qwen / dense KPK)
- **RAM stuck at 0 on Windows:** Process RSS used Unix-only `resource.getrusage`, which always failed on native Windows CPython. Now uses `GetProcessMemoryInfo` (WorkingSet). Chat stats also prefer the engine’s `rss_gb` / `footprint_gb` when present so the UI reflects real model memory without inflating it via fake counters.
- **Extremely slow decode (~300s) on Windows x64:** KPK / dense kernels (`windhover.c`, `dense.c`) were ARM-NEON-only and fell back to **scalar** matmul on x86. Added AVX2 (+ AVX-VNNI when available) IDOT helpers shared via `engine/runtime/idot_avx.h` so Phi-4 Mini, Qwen, and other dense packs run at normal CPU tok/s.
- **OpenMP defaults missing on desktop Windows:** Engine spawn now applies the same Windows OMP/I/O env as `coli` (`OMP_NUM_THREADS` = physical cores, `OMP_WAIT_POLICY=active`, `DIRECT`/`PIPE`/`PILOT_REAL`) **before** launching `windhover-engine.exe`, so libgomp actually sees them.

## [0.3.12] — 2026-07-23

### Fixed
- **Windows WinError 267** when chatting: packaged app launched `windhover-engine` with
  cwd=`bundle/engine` (often missing). Use the engine binary’s directory (or another
  existing path) so CreateProcess succeeds.

## [0.3.11] — 2026-07-23

### Engine — Universal Windhover Model IR (WMIR)
- Replaced architecture allowlists with a layer-typed IR (`windhover.wmir` in `kestrel.json`).
- HF configs lower via `tools/wmir/` (Gemma 4, Qwen3.5/3.6, Llama 4, Kimi, DeepSeek V4, MiniMax, Mistral Large 3, plus classic dense/GLM).
- Runtime executes ops by kind: GQA (+ KV share, chunked/CSA/MSA windows), linear GDN, double-wide MLP, MoE-stream markers.
- Catalog installable entries now require a WMIR lowerer + registered kernels (`tools/catalog_engine_audit.py`).

## [0.3.10] — 2026-07-23

### Catalog
- **Engine-truth audit:** only models Windhover can actually run stay installable. Gemma 4 / Qwen3.5–3.6 hybrid / Llama 4 / Kimi K2.x / DeepSeek V4 / MiniMax M3 / broken HF ids are marked `soon` + blocked.
- Ready list is Qwen2.5/3 dense + SmolLM2 + DeepSeek R1 Distill (chat immediately after download) and Phi-4 Mini (install finishes with KPK convert). Same paths on Mac and Windows.
- Added `tools/catalog_engine_audit.py` to verify HF `model_type` vs engine support before release.

### Bugs fixed
- **Windows Phi-4 / Gemma engine prepare:** first chat no longer hard-fails while converting. Convert runs in the background with progress; install fails clearly if Phi/Gemma KPK convert fails; Chat returns `engine_preparing` and the UI polls until ready.

## [0.3.8] — 2026-07-23

### Bugs fixed
- **UI squashed into top quarter of the window:** shell grid reserved an empty `1fr` row when the update banner was hidden. Titlebar + banners are one chrome block again so the app fills the window.

## [0.3.7] — 2026-07-23

### Bugs fixed
- **Windows Phi-4 “KPK convert failed”:** torch-free safetensors BF16 reads were returning flat arrays, which broke Phi’s fused `qkv` / `gate_up` split during convert. Tensor shapes are restored from the safetensors header so Phi-4 Mini converts and chats via windhover-engine without torch.

## [0.3.6] — 2026-07-23

### App
- **In-app updates:** when a newer GitHub Release exists, Windhover shows an **Update** button. Windows downloads the NSIS installer and upgrades in place (no uninstall). macOS opens the new DMG. Also under Advanced → Check for updates.

## [0.3.5] — 2026-07-23

### Bugs fixed
- **Windows Chat `No module named 'torch'` after Library download:** chat no longer routes downloaded models through transformers preview when KPK is missing. Packaged apps use windhover-engine (dense load-time quant for Qwen/Llama/Mistral; torch-free numpy KPK convert for Phi/Gemma).
- **Packaging:** sidecar bundles `numpy` / `safetensors` / `kestrel_pack` for convert; selfcheck covers chat routing helpers; torch/transformers stay excluded on purpose.

## [0.3.4] — 2026-07-23

### Bugs fixed
- **Windows Library download `ModuleNotFoundError: No module named 'huggingface_hub'`:** package `huggingface_hub` (and deps) into the `windhover-server` PyInstaller sidecar so Install from Library works without a system Python.
- **Packaging hardening:** also collect `httpx` / hub runtime stack; `windhover-server --sidecar-selfcheck` fails the sidecar build if download imports are missing.

## [0.3.3] — 2026-07-23

### Bugs fixed
- **Windows Library install crash:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` during model download — UTF-8-safe stdio, HF/tqdm progress bars disabled on Windows, and ASCII-safe progress messages.
- **Windows setup “Error opening file for writing: …\windhover-server.exe”:** NSIS preinstall hooks stop `Windhover` / `windhover-server` / `windhover-engine` and delete locked sidecars before copy.
- **Windows app freezes ~1 minute on first launch:** backend sidecar starts on a background thread so the UI window is responsive immediately; packaged startup defers impostor cleanup until after `/health` is up.
- **Windows release CI:** catalog/health smoke uses `curl.exe` (not flaky `Invoke-WebRequest` / `ResponseEnded`); do not redirect stdout+stderr to the same file in `Start-Process`; JSON catalog/meta reads always use UTF-8; WinARM engine links `winpthread` for static OpenMP builds.

## [0.3.1] — 2026-07-22

### App / API
- **Engine inactive errors:** missing binary, launch failure, or non-zero engine exit now return HTTP 503 with `code: engine_inactive` so Chat/Agent clearly show the engine is not active (no silent pretend-success).
- Chat UI banner + status pill when engine binary is missing or the last reply fell back / failed.
- Soft transformers fallback (unusable decode) still works when HF weights exist, but is marked `engine_active: false`.

### Catalog
- **Qwen3 8B · engine Q4** (`Qwen/Qwen3-8B`) — dense `qwen3`, Windhover int4/KPK path for ~9B-class local engine chat.
- **Qwen3.5 9B** listed as `soon` / blocked: official `qwen3_5` hybrid multimodal is not supported by windhover-engine yet.

## [0.3.0] — 2026-07-22

### Highlights
- **Phi-4 Mini engine fidelity:** windhover-engine now matches transformers quality on math/reasoning while staying faster and lighter.
- **Partial RoPE + longrope attention scale** for `phi3` packs (`partial_rotary_factor`, attn scale ≈ 1.19).
- **Higher-precision KPK quant for Phi-class models** (D ≤ 4096): int8 `o`/`gate`/`up`/`down`, AWQ kept for near-tied tokens.
- Chat prefers accurate engine path for Phi again; transformers remains fallback for garbage/unsupported RoPE types.

### Engine
- Parse `partial_rotary_factor`, longrope `attention_factor`, and related config in `model_desc.h`.
- Apply RoPE only on `rope_dim` with correct inv-freq base and attn scale (`windhover.c`).
- Support int8 transposed `down_proj` (was int4-only).
- Default `WH_SPARSE=0` for quality; Chat sets it unless overridden.
- Multi-stop / denser stop-token handling for instruct packs.

### Pack / convert
- `tools/kestrel_pack.py`: int8 FFN path for medium dense models; `./windhover convert` uses the ML venv Python.
- Phi-4 Mini KPK rebuild: ~4.5 GB, AWQ + int8 FFN.

### App / API
- Cursor-like shell (Agent/Chat/Library), live engine status strip.
- Catalog refresh (Gemma 4, Phi-4, Qwen3.6, …) and incomplete-pack / download UX fixes.
- Engine→transformers fallback when replies look degenerate.

### Benchmarks (Phi-4 Mini Instruct)
- Engine accuracy suite: **100%** on math/reasoning prompts; mean **~20 tok/s**, peak **~3.8 GB** RSS.
- Transformers (MPS): mean **~2.5 tok/s**, peak **~5.3 GB** — engine ~1.5 GB lighter.
- Details: `docs/phi4_engine_acc.json`, `docs/phi4_detail_bench.json`.

### Downloads
- macOS: `Windhover-macOS-arm64.dmg`
- Windows: `Windhover-Windows-x64.exe`, `Windhover-Windows-arm64.exe`

## [0.2.0] — prior
- Ollama bridge, macOS DMG Gatekeeper fixes, Windows ARM64 engine, PyInstaller sidecar.
