# Packaging checklist (Windows / macOS sidecars)

Use this before cutting a release so Library Install / NSIS / smoke do not regress.

## Frozen `windhover-server` must include download deps

Library Install calls `huggingface_hub.snapshot_download` inside the PyInstaller
sidecar. Lazy imports are **invisible** to Analysis — never assume “it works on
dev Python” means it works in the `.exe`.

- [ ] `packaging/build_sidecar.ps1` / `.sh` install `huggingface_hub` **and**
      runtime deps (`httpx`, `filelock`, `fsspec`, `PyYAML`, `tqdm`, `packaging`,
      `click`, `hf-xet`).
- [ ] `packaging/windhover-server.spec` uses `collect_all(...)` for those packages.
- [ ] Build runs `windhover-server --sidecar-selfcheck` and exits **0** (imports
      `huggingface_hub` + `snapshot_download` inside the frozen binary).
- [ ] CI Release Windows smoke still hits `/health` and `/v1/catalog` with **curl.exe**
      (not `Invoke-WebRequest`).

## Do not

- Redirect `Start-Process` stdout **and** stderr to the **same** log file on Windows
  (fails immediately).
- Exclude or forget hub deps when trimming the sidecar (`torch` / `transformers`
  stay excluded on purpose; engine chat still works without them).
- Ship a Windows build without re-running sidecar selfcheck after changing
  `windhover` download code.

## Known intentional limits

- Packaged Windows app does **not** bundle `torch`/`transformers` — transformers
  preview chat needs a dev install; engine + HF download path is the product path.
- Chat-template formatting falls back to a plain prompt if `transformers` is missing.
