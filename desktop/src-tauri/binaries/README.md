# Tauri externalBin staging

On Windows release builds, place:

- `windhover-server-<target-triple>.exe`
- `windhover-engine-<target-triple>.exe`

Examples:

- `windhover-server-x86_64-pc-windows-msvc.exe`
- `windhover-engine-aarch64-pc-windows-msvc.exe`

Generate with `packaging/build_sidecar.ps1` after `make -C engine` on Windows.
