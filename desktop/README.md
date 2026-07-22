# Windhover desktop (Tauri)

Native desktop app for the Windhover Library + Chat UI in [`../app`](../app).

On launch the app prefers packaged sidecars (`windhover-server` + `windhover-engine`) when present, otherwise falls back to repo-relative `python windhover app` for local development. The UI opens in a branded native window (**Windhover**, bundle ID `ai.vexilo.windhover`).

## Prerequisites

```sh
./windhover build
cd app && npm ci && npm run build && cd ..
cargo install tauri-cli --version "^2.0.0" --locked
```

## Develop

```sh
cd desktop
cargo tauri dev
```

## Release bundles

### macOS

```sh
cd desktop
cargo tauri build --bundles app,dmg
open src-tauri/target/release/bundle/macos/Windhover.app
```

Published DMG: `Windhover-macOS-arm64.dmg` (unsigned until Apple secrets exist).

### Windows

Stage sidecars first (see [`packaging/build_sidecar.ps1`](../packaging/build_sidecar.ps1)):

```powershell
powershell -File packaging/build_sidecar.ps1 -Triple x86_64-pc-windows-msvc
cd desktop
cargo tauri build --bundles nsis --target x86_64-pc-windows-msvc
```

Published installers: `Windhover-Windows-x64.exe` / `Windhover-Windows-arm64.exe` (unsigned until Authenticode secrets exist).

CI builds are **unsigned** — see [`docs/DOWNLOAD.md`](../docs/DOWNLOAD.md).
