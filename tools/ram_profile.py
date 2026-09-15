"""Fast / Balanced / Low-RAM profiles for Chat and Agent.

Maps a named profile onto RAM_GB (AU budget), MLOCK, and WH_SPARSE.
Default is Balanced on advertised ≤16 GB machines (16 GiB laptops) so
laptop Chat actually hits the residency ceiling. Do not classify with
bytes/1e9: a 16 GiB Mac is ~17.18 decimal GB and would look like Fast.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

PROFILES = ("fast", "balanced", "low")
_BYTES_PER_GIB = 1024 ** 3
# Advertised 16 GB laptops. 18 GB and up stay Fast.
_LAPTOP_GIB = 16.5

# Fast = today's 0.4.2 chat defaults (AU off, full FFN hot + mlock).
# Balanced ≈ 55% of physical RAM (OS + browser stay). Low ≈ 40%, no mlock.
_FRAC = {"fast": None, "balanced": 0.55, "low": 0.40}
_MLOCK = {"fast": 1, "balanced": 1, "low": 0}
_SPARSE = {"fast": 25, "balanced": 25, "low": 25}
_LABELS = {
    "fast": "Fast",
    "balanced": "Balanced",
    "low": "Low-RAM",
}
_BLURBS = {
    "fast": "Pin the full FFN (no RAM_GB ceiling). Fastest tok/s, highest wired RAM.",
    "balanced": "Cap at ~55% of RAM so AU can page cold FFN. Default on ≤16 GB laptops.",
    "low": "Cap at ~40% of RAM, AU on, MLOCK off — leaves more room for the OS.",
}

_LOCK = threading.Lock()
_CURRENT: str | None = None
_PHYS_CACHE: float | None = None


def settings_path() -> Path:
    env = os.environ.get("WINDHOVER_SETTINGS")
    if env:
        return Path(env)
    return Path.home() / ".windhover" / "settings.json"


def gib_from_bytes(n: int | float) -> float:
    """Physical RAM in GiB — the unit Macs/PCs advertise as '16 GB'."""
    return float(n) / _BYTES_PER_GIB


def physical_ram_gb() -> float:
    """Installed physical RAM in GiB (not free/available). 0 if unknown."""
    global _PHYS_CACHE
    if _PHYS_CACHE is not None:
        return _PHYS_CACHE
    gb = _probe_physical_ram_gb()
    _PHYS_CACHE = gb
    return gb


def _probe_physical_ram_gb() -> float:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        if pages and page and pages > 0 and page > 0:
            return gib_from_bytes(pages * page)
    except (AttributeError, OSError, ValueError):
        pass
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
            ).strip()
            if out.isdigit():
                return gib_from_bytes(int(out))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            total_kb = ctypes.c_ulonglong(0)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.c_void_p]
            kernel32.GetPhysicallyInstalledSystemMemory.restype = ctypes.c_int
            if kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(total_kb)) and total_kb.value:
                return gib_from_bytes(total_kb.value * 1024)
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
            kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
            kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) and stat.ullTotalPhys:
                return gib_from_bytes(stat.ullTotalPhys)
        except Exception:
            pass
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return gib_from_bytes(kb * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name).strip().lower().replace("_", "-")
    if n in ("low-ram", "lowram", "ram"):
        n = "low"
    if n in PROFILES:
        return n
    return None


def _is_laptop_class(phys: float) -> bool:
    """Advertised ≤16 GB machines, including 16 GiB Macs.

    physical_ram_gb() is GiB (bytes/1024**3), so 16 GiB == 16.0. A leftover
    bytes/1e9 value for that hardware is ~17.18, which used to miss 16.5 and
    default Fast (same as 0.4.3). 18 GB Macs are 18.0 GiB or ~19.3 decimal GB.
    """
    if phys <= 0 or phys <= _LAPTOP_GIB:
        return True
    if phys >= 18.0:
        return False
    return gib_from_bytes(phys * 1e9) <= _LAPTOP_GIB


def default_name(physical_gb: float | None = None) -> str:
    """Balanced on ≤16 GB laptops; Fast on larger machines (today's speed bias)."""
    phys = physical_ram_gb() if physical_gb is None else float(physical_gb)
    if _is_laptop_class(phys):
        return "balanced"
    return "fast"


def _read_saved_name() -> str | None:
    path = settings_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return normalize_name(data.get("ram_profile"))


def _write_saved_name(name: str) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}
        data["ram_profile"] = name
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def active_name() -> str:
    with _LOCK:
        if _CURRENT:
            return _CURRENT
    env = normalize_name(os.environ.get("WINDHOVER_RAM_PROFILE"))
    if env:
        return env
    saved = _read_saved_name()
    if saved:
        return saved
    return default_name()


def set_active_name(name: str) -> str:
    n = normalize_name(name)
    if not n:
        raise ValueError(f"unknown RAM profile {name!r} (fast|balanced|low)")
    with _LOCK:
        global _CURRENT
        _CURRENT = n
    _write_saved_name(n)
    return n


def cap_gb(name: str, physical_gb: float) -> float | None:
    """RAM_GB to export, or None to leave AU off (Fast)."""
    frac = _FRAC[name]
    if frac is None:
        return None
    phys = max(float(physical_gb), 0.0)
    if phys <= 0:
        phys = 16.0
    raw = phys * frac
    # Leave ~1.5 GB for the OS; never go below 2 GB.
    raw = min(raw, max(phys - 1.5, 2.0))
    raw = max(raw, 2.0)
    return round(raw, 1)


def resolve(name: str | None = None, *, physical_gb: float | None = None) -> dict[str, Any]:
    n = normalize_name(name) or active_name()
    phys = physical_ram_gb() if physical_gb is None else float(physical_gb)
    ram = cap_gb(n, phys)
    return {
        "name": n,
        "label": _LABELS[n],
        "blurb": _BLURBS[n],
        "ram_gb": ram,
        "mlock": _MLOCK[n],
        "sparse": _SPARSE[n],
        "au": ram is not None,
        "physical_ram_gb": round(phys, 1) if phys > 0 else None,
        "default": n == default_name(phys),
    }


def public_payload() -> dict[str, Any]:
    cur = resolve()
    return {
        **cur,
        "profiles": [
            {
                "name": n,
                "label": _LABELS[n],
                "blurb": _BLURBS[n],
                "ram_gb": cap_gb(n, cur["physical_ram_gb"] or 16.0),
                "mlock": _MLOCK[n],
                "active": n == cur["name"],
            }
            for n in PROFILES
        ],
    }


def apply_to_env(env: dict[str, str], profile: dict[str, Any] | None = None) -> dict[str, str]:
    """Write profile knobs into a child env unless the user already exported them."""
    prof = profile if profile is not None else resolve()
    if "RAM_GB" not in os.environ:
        ram = prof.get("ram_gb")
        if ram is None:
            env.pop("RAM_GB", None)
            env.pop("COLI_HARD_CAP", None)
        else:
            env["RAM_GB"] = str(ram)
            env["COLI_HARD_CAP"] = "1"
    if "MLOCK" not in os.environ:
        env["MLOCK"] = str(int(prof.get("mlock") or 0))
    if "WH_SPARSE" not in os.environ:
        env["WH_SPARSE"] = str(int(prof.get("sparse") or 25))
    env["WINDHOVER_RAM_PROFILE"] = str(prof.get("name") or "balanced")
    return env
