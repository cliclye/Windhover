#!/usr/bin/env bash
# Build windhover-server sidecar and stage Tauri externalBin names.
# Usage (from repo root):
#   ./packaging/build_sidecar.sh [target-triple]
# Example:
#   ./packaging/build_sidecar.sh x86_64-pc-windows-msvc
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="${1:-}"
cd "$ROOT"

if [[ ! -d app/dist ]]; then
  (cd app && npm ci && npm run build)
fi

python3 -m pip install -q \
  pyinstaller \
  "huggingface_hub>=0.23" \
  "httpx>=0.23" \
  filelock \
  fsspec \
  PyYAML \
  tqdm \
  packaging \
  click \
  hf-xet \
  numpy \
  safetensors \
  ml_dtypes
python3 -c "import huggingface_hub, httpx, numpy, safetensors; from huggingface_hub import snapshot_download; print('hub', huggingface_hub.__version__, 'numpy', numpy.__version__)"
python3 -m PyInstaller packaging/windhover-server.spec --noconfirm --distpath packaging/dist --workpath packaging/build

BIN_DIR="$ROOT/desktop/src-tauri/binaries"
mkdir -p "$BIN_DIR"

SERVER_SRC="$ROOT/packaging/dist/windhover-server"
if [[ -f "${SERVER_SRC}.exe" ]]; then
  SERVER_SRC="${SERVER_SRC}.exe"
  EXT=".exe"
else
  EXT=""
fi

# Prove Library-download imports work inside the frozen binary.
"$SERVER_SRC" --sidecar-selfcheck

if [[ -z "$TRIPLE" ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TRIPLE="aarch64-apple-darwin" ;;
    Darwin-x86_64) TRIPLE="x86_64-apple-darwin" ;;
    Linux-x86_64) TRIPLE="x86_64-unknown-linux-gnu" ;;
    Linux-aarch64) TRIPLE="aarch64-unknown-linux-gnu" ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT*)
      if [[ "${PROCESSOR_ARCHITECTURE:-}" == "ARM64" ]]; then
        TRIPLE="aarch64-pc-windows-msvc"
      else
        TRIPLE="x86_64-pc-windows-msvc"
      fi
      ;;
    *) TRIPLE="unknown" ;;
  esac
fi

cp -f "$SERVER_SRC" "$BIN_DIR/windhover-server-${TRIPLE}${EXT}"
echo "Staged $BIN_DIR/windhover-server-${TRIPLE}${EXT}"

# Stage engine next to it when present
ENG="$ROOT/engine/windhover-engine"
if [[ -f "${ENG}.exe" ]]; then ENG="${ENG}.exe"; EXT=".exe"; elif [[ -f "$ENG" ]]; then EXT=""; else ENG=""; fi
if [[ -n "$ENG" ]]; then
  cp -f "$ENG" "$BIN_DIR/windhover-engine-${TRIPLE}${EXT}"
  echo "Staged $BIN_DIR/windhover-engine-${TRIPLE}${EXT}"

  # macOS: ship libomp beside the engine and rewrite the install name so end
  # users without Homebrew can still run windhover-engine (Windows static/gomp
  # path already avoids this class of bug).
  if [[ "$(uname -s)" == "Darwin" && -z "$EXT" ]]; then
    OMP_SRC=""
    for cand in \
      "$(brew --prefix libomp 2>/dev/null)/lib/libomp.dylib" \
      /opt/homebrew/opt/libomp/lib/libomp.dylib \
      /usr/local/opt/libomp/lib/libomp.dylib
    do
      if [[ -n "$cand" && -f "$cand" ]]; then
        OMP_SRC="$cand"
        break
      fi
    done
    if [[ -n "$OMP_SRC" ]]; then
      cp -f "$OMP_SRC" "$BIN_DIR/libomp.dylib"
      # Rewrite absolute Homebrew path → @loader_path (same folder as engine).
      OLD_ID="$(otool -L "$BIN_DIR/windhover-engine-${TRIPLE}" | awk '/libomp\.dylib/{print $1; exit}')"
      if [[ -n "$OLD_ID" ]]; then
        install_name_tool -change "$OLD_ID" "@loader_path/libomp.dylib" \
          "$BIN_DIR/windhover-engine-${TRIPLE}"
      fi
      install_name_tool -id "@loader_path/libomp.dylib" "$BIN_DIR/libomp.dylib" || true
      echo "Staged $BIN_DIR/libomp.dylib (rewrote $OLD_ID)"
      otool -L "$BIN_DIR/windhover-engine-${TRIPLE}" | head -n 8
    else
      echo "WARNING: libomp.dylib not found — packaged Mac engine may fail without Homebrew" >&2
    fi
  fi
fi
