# Kestrel (macOS)

Native **Mac app** (Tauri v2) for the Kestrel Library + Chat UI in [`../app`](../app).

On launch the desktop app starts `../kestrel app` (local engine API + UI on `http://127.0.0.1:8000`) and opens it in a branded native window (**Kestrel**, bundle ID `ai.vexilo.kestrel`).

## Prerequisites

```sh
./kestrel build
cd app && npm ci && npm run build && cd ..
cargo install tauri-cli --version "^2.0.0" --locked
```

## Develop

```sh
cd desktop
cargo tauri dev
```

## Build `.app`

```sh
cd desktop
# Recommended:
cargo tauri build --debug --bundles app
# → src-tauri/target/debug/bundle/macos/Kestrel.app

# Release binary:
CARGO_INCREMENTAL=0 cargo build --release --manifest-path src-tauri/Cargo.toml
# Assembled release app (when present):
# → src-tauri/target/release/bundle/macos/Kestrel.app
```

## Branding

- Product name: **Kestrel**
- Bundle ID: `ai.vexilo.kestrel`
- Icons: `src-tauri/icons/` (`icon.icns` for Dock / Finder)
- UI mark: `app/public/kestrel-icon.png`
