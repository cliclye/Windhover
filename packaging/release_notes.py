#!/usr/bin/env python3
"""Write GitHub Release notes for a tag from CHANGELOG.md.

  python3 packaging/release_notes.py v0.5.0 > release-notes.md

Emits the "## [0.5.0]" section of CHANGELOG.md (falls back to "## Unreleased")
followed by the standard download / first-launch block, so both release
workflows publish the same, version-specific body.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/cliclye/Windhover"

DOWNLOADS = f"""## Download

### macOS
**[Windhover-macOS-arm64.dmg]({REPO}/releases/latest/download/Windhover-macOS-arm64.dmg)** — Apple Silicon · macOS 12+

### Windows 11
**[Windhover-Windows-x64.exe]({REPO}/releases/latest/download/Windhover-Windows-x64.exe)** — Intel/AMD 64-bit
**[Windhover-Windows-arm64.exe]({REPO}/releases/latest/download/Windhover-Windows-arm64.exe)** — Snapdragon / ARM64

### First launch
- **macOS:** unsigned — if Gatekeeper says the app is “damaged”, run `xattr -cr /Applications/Windhover.app` ([docs/DOWNLOAD.md]({REPO}/blob/main/docs/DOWNLOAD.md)).
- **Windows:** unsigned — SmartScreen may require More info → Run anyway.
"""


def section(changelog: str, version: str) -> str:
    """Body of '## [version]' (or '## Unreleased') up to the next '## ' heading."""
    for pat in (rf"^## \[{re.escape(version)}\][^\n]*\n", r"^## Unreleased[^\n]*\n"):
        m = re.search(pat, changelog, flags=re.M)
        if m:
            rest = changelog[m.end():]
            nxt = re.search(r"^## ", rest, flags=re.M)
            return rest[: nxt.start()].strip() if nxt else rest.strip()
    return ""


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    version = tag.lstrip("v")
    body = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    out = [f"## Windhover {version}" if version else "## Windhover", ""]
    if body:
        out += [body, ""]
    out += [f"Full history: [CHANGELOG.md]({REPO}/blob/main/CHANGELOG.md)", "", DOWNLOADS]
    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
