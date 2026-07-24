"""In-app update check and silent install helpers for Windhover."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

_UPDATE_CACHE: dict = {"checked_at": 0.0, "payload": None}
_UPDATE_LOCK = threading.Lock()


def parse_semver(v: str) -> tuple[int, int, int]:
    s = (v or "").strip().lstrip("v")
    parts = []
    for p in s.split(".")[:3]:
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num or 0))
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def version_newer(latest: str, current: str) -> bool:
    return parse_semver(latest) > parse_semver(current)


def update_platform_asset() -> tuple[str, str]:
    """Return (os_key, preferred asset name substring) for GitHub release assets."""
    import platform as _platform

    mach = (_platform.machine() or "").lower()
    if sys.platform == "darwin":
        return "macos", "Windhover-macOS-arm64.dmg"
    if sys.platform == "win32":
        if mach in ("arm64", "aarch64"):
            return "windows-arm64", "Windhover-Windows-arm64.exe"
        return "windows-x64", "Windhover-Windows-x64.exe"
    return "other", ""


def pick_release_asset(assets: list, preferred_name: str) -> dict | None:
    if not assets:
        return None
    for a in assets:
        name = str(a.get("name") or "")
        if name == preferred_name:
            return a
    prefer = preferred_name.lower()
    for a in assets:
        name = str(a.get("name") or "").lower()
        if prefer and prefer in name:
            return a
    if sys.platform == "win32":
        for a in assets:
            name = str(a.get("name") or "").lower()
            if name.endswith(".exe") and "windows" in name:
                return a
    if sys.platform == "darwin":
        for a in assets:
            name = str(a.get("name") or "").lower()
            if name.endswith(".dmg"):
                return a
    return None


def check_app_update(
    *,
    current_version: str,
    github_repo: str,
    force: bool = False,
) -> dict:
    """Compare local version to GitHub latest release. Cached ~1h."""
    now = time.time()
    with _UPDATE_LOCK:
        cached = _UPDATE_CACHE.get("payload")
        if (
            not force
            and cached
            and (now - float(_UPDATE_CACHE.get("checked_at") or 0)) < 3600
        ):
            return dict(cached)

    current = current_version
    plat, preferred = update_platform_asset()
    out = {
        "ok": True,
        "current": current,
        "latest": current,
        "available": False,
        "platform": plat,
        "tag": None,
        "name": None,
        "notes": None,
        "html_url": f"https://github.com/{github_repo}/releases/latest",
        "download_url": None,
        "asset_name": None,
        "error": None,
    }
    if not preferred:
        out["error"] = "Automatic updates are only supported on macOS and Windows."
        with _UPDATE_LOCK:
            _UPDATE_CACHE["checked_at"] = now
            _UPDATE_CACHE["payload"] = dict(out)
        return out

    url = f"https://api.github.com/repos/{github_repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Windhover/{current}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        with _UPDATE_LOCK:
            _UPDATE_CACHE["checked_at"] = now
            _UPDATE_CACHE["payload"] = dict(out)
        return out

    tag = str(data.get("tag_name") or "").lstrip("v")
    asset = pick_release_asset(data.get("assets") or [], preferred)
    out.update(
        {
            "latest": tag or current,
            "available": bool(tag and version_newer(tag, current)),
            "tag": data.get("tag_name"),
            "name": data.get("name"),
            "notes": (data.get("body") or "")[:4000] or None,
            "html_url": data.get("html_url") or out["html_url"],
            "download_url": (asset or {}).get("browser_download_url"),
            "asset_name": (asset or {}).get("name"),
        }
    )
    if out["available"] and not out["download_url"]:
        out["error"] = f"Latest release has no installer for {plat}."
        out["available"] = False
    with _UPDATE_LOCK:
        _UPDATE_CACHE["checked_at"] = now
        _UPDATE_CACHE["payload"] = dict(out)
    return out


def windows_install_dir() -> str | None:
    """Best-effort path to the current NSIS install (%LOCALAPPDATA%\\Windhover)."""
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent
        if (parent / "Windhover.exe").is_file():
            return str(parent)
    local = Path(os.environ.get("LOCALAPPDATA") or "") / "Windhover"
    if (local / "Windhover.exe").is_file():
        return str(local)
    return None


def macos_app_bundle() -> Path | None:
    """Path to the running Windhover.app, or /Applications/Windhover.app if present."""
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve()
        for cand in (p, *p.parents):
            if cand.suffix == ".app" and cand.name == "Windhover.app":
                return cand
    apps = Path("/Applications/Windhover.app")
    if apps.is_dir():
        return apps
    return None


def spawn_macos_update_helper(dmg: Path, app_dst: Path) -> None:
    """Quit, replace Windhover.app from the DMG, then relaunch — outside this process."""
    import shlex

    script = Path(tempfile.gettempdir()) / f"windhover-update-{os.getpid()}.sh"
    dmg_q = shlex.quote(str(dmg))
    dst_q = shlex.quote(str(app_dst))
    script.write_text(
        f"""#!/bin/bash
set -euo pipefail
DMG={dmg_q}
DST={dst_q}
sleep 2
osascript -e 'tell application "Windhover" to quit' >/dev/null 2>&1 || true
pkill -x Windhover >/dev/null 2>&1 || true
pkill -x windhover-server >/dev/null 2>&1 || true
pkill -x windhover-engine >/dev/null 2>&1 || true
sleep 2
MNT="$(mktemp -d /tmp/wh-upd.XXXXXX)"
cleanup() {{ hdiutil detach "$MNT" -quiet >/dev/null 2>&1 || true; rm -rf "$MNT"; }}
trap cleanup EXIT
hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MNT" -quiet
SRC="$(find "$MNT" -maxdepth 3 -name 'Windhover.app' -type d | head -n 1)"
if [[ -z "${{SRC}}" || ! -d "${{SRC}}" ]]; then
  echo "Windhover.app not found in DMG" >&2
  exit 1
fi
rm -rf "$DST"
ditto "$SRC" "$DST"
xattr -cr "$DST" >/dev/null 2>&1 || true
trap - EXIT
hdiutil detach "$MNT" -quiet >/dev/null 2>&1 || true
rm -rf "$MNT"
open "$DST"
rm -f "$DMG" || true
rm -f {shlex.quote(str(script))} || true
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    subprocess.Popen(
        ["/bin/bash", str(script)],
        cwd=str(script.parent),
        start_new_session=True,
        close_fds=True,
    )


def apply_app_update(
    *,
    current_version: str,
    github_repo: str,
    download_url: str | None = None,
) -> dict:
    """Download the latest installer and apply it silently (in-place + relaunch)."""
    info = check_app_update(
        current_version=current_version, github_repo=github_repo, force=False
    )
    url = (download_url or info.get("download_url") or "").strip()
    if not url:
        info = check_app_update(
            current_version=current_version, github_repo=github_repo, force=True
        )
        url = (info.get("download_url") or "").strip()
    if not url:
        return {
            "ok": False,
            "error": info.get("error") or "No download URL for this platform.",
            "update": info,
        }

    asset_name = info.get("asset_name") or url.rsplit("/", 1)[-1] or "Windhover-update"
    dest = Path(tempfile.gettempdir()) / f"windhover-update-{info.get('latest') or 'latest'}-{asset_name}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"Windhover/{current_version}"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as e:
        return {"ok": False, "error": f"Download failed: {type(e).__name__}: {e}"}

    try:
        if sys.platform == "win32":
            args = [str(dest), "/S", "/UPDATE", "/R"]
            install_dir = windows_install_dir()
            if install_dir:
                args.append(f"/D={install_dir}")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                args,
                cwd=str(dest.parent),
                close_fds=True,
                creationflags=flags,
            )
            msg = (
                "Installing update silently — Windhover will close and reopen on the new version."
            )
        elif sys.platform == "darwin":
            app_dst = macos_app_bundle() or Path("/Applications/Windhover.app")
            spawn_macos_update_helper(dest, app_dst)
            msg = (
                "Installing update — Windhover will quit, replace itself, and reopen automatically."
            )
        else:
            return {"ok": False, "error": "Unsupported platform for in-app update.", "path": str(dest)}
    except Exception as e:
        return {"ok": False, "error": f"Could not start update: {type(e).__name__}: {e}", "path": str(dest)}

    return {
        "ok": True,
        "path": str(dest),
        "message": msg,
        "update": info,
        "restarting": True,
    }
