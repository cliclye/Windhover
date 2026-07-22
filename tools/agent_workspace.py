#!/usr/bin/env python3
"""Workspace-scoped agent tools for Windhover Agent (local LLM coding loop).

All paths must resolve under the user-selected workspace root. No network tools.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Deny writing these relative path prefixes
_DENY_WRITE_PREFIXES = (".git/",)
_MAX_READ_BYTES = 120_000
_MAX_WRITE_BYTES = 200_000
_MAX_LIST = 200

_TOOL_RE = re.compile(
    r"```(?:tool|json)\s*\n(\{.*?\})\n```",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_RE_ALT = re.compile(
    r"<tool>\s*(\{.*?\})\s*</tool>",
    re.DOTALL | re.IGNORECASE,
)


def resolve_under(root: Path, rel: str) -> Path:
    """Resolve rel under root; raise ValueError on escape."""
    root = root.resolve()
    raw = (rel or ".").strip() or "."
    # Absolute: POSIX /, home ~, or Windows drive letter / UNC
    is_abs = (
        raw.startswith("~")
        or raw.startswith("/")
        or (len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha())
        or raw.startswith("\\\\")
    )
    if is_abs:
        cand = Path(raw).expanduser().resolve()
    else:
        cand = (root / raw).resolve()
    try:
        cand.relative_to(root)
    except ValueError as e:
        raise ValueError(f"path escapes workspace: {rel!r}") from e
    return cand


def set_workspace(path: str) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"not a directory: {p}")
    return {"ok": True, "root": str(p)}


def pick_folder(prompt: str = "Choose a folder for Windhover Agent") -> dict[str, Any]:
    """Open a native folder picker (osascript on macOS, PowerShell on Windows)."""
    import subprocess
    import sys

    if sys.platform == "win32":
        # FolderBrowserDialog via PowerShell STA
        safe = prompt.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$f.Description = '{safe}'; "
            "$f.ShowNewFolderButton = $true; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::Out.Write($f.SelectedPath) } else { exit 2 }"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except FileNotFoundError as e:
            raise RuntimeError("folder picker unavailable (powershell missing)") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("folder picker timed out") from e
        if r.returncode == 2 or (r.returncode != 0 and not (r.stdout or "").strip()):
            return {"ok": False, "cancelled": True, "error": "cancelled"}
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            raise RuntimeError(err or f"powershell exited {r.returncode}")
        path = (r.stdout or "").strip().rstrip("\\/")
        if not path:
            return {"ok": False, "cancelled": True, "error": "cancelled"}
        return set_workspace(path)

    # macOS (default)
    safe = prompt.replace("\\", "\\\\").replace('"', '\\"')
    script = f'POSIX path of (choose folder with prompt "{safe}")'
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("folder picker unavailable (osascript missing)") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("folder picker timed out") from e
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "User canceled" in err or "(-128)" in err or not err:
            return {"ok": False, "cancelled": True, "error": "cancelled"}
        raise RuntimeError(err or f"osascript exited {r.returncode}")
    path = (r.stdout or "").strip().rstrip("/")
    if not path:
        return {"ok": False, "cancelled": True, "error": "cancelled"}
    return set_workspace(path)


def list_dir(root: Path, rel: str = ".") -> dict[str, Any]:
    root = root.resolve()
    d = resolve_under(root, rel)
    # Models sometimes pass a file path; list its parent instead of failing.
    if d.is_file():
        d = d.parent
    if not d.is_dir():
        raise NotADirectoryError(str(d.relative_to(root) if d != root else "."))
    entries = []
    for child in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if child.name == ".git":
            continue
        try:
            st = child.stat()
            child = child.resolve()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(root)),
                "type": "dir" if child.is_dir() else "file",
                "size": st.st_size if child.is_file() else None,
            }
        )
        if len(entries) >= _MAX_LIST:
            break
    try:
        shown = str(d.relative_to(root)) if d != root else "."
    except ValueError:
        shown = str(Path(rel or "."))
    return {"ok": True, "path": shown, "entries": entries}


def read_file(root: Path, rel: str) -> dict[str, Any]:
    root = root.resolve()
    fp = resolve_under(root, rel)
    if not fp.is_file():
        raise FileNotFoundError(str(fp.relative_to(root)))
    data = fp.read_bytes()
    if len(data) > _MAX_READ_BYTES:
        data = data[:_MAX_READ_BYTES]
        truncated = True
    else:
        truncated = False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False,
            "error": "binary or non-utf8 file",
            "path": str(fp.relative_to(root)),
            "size": fp.stat().st_size,
        }
    return {
        "ok": True,
        "path": str(fp.relative_to(root)),
        "content": text,
        "truncated": truncated,
        "bytes": fp.stat().st_size,
    }


def write_file(root: Path, rel: str, content: str) -> dict[str, Any]:
    root = root.resolve()
    fp = resolve_under(root, rel)
    rel_s = str(fp.relative_to(root)).replace("\\", "/")
    for pref in _DENY_WRITE_PREFIXES:
        if rel_s == pref.rstrip("/") or rel_s.startswith(pref):
            raise PermissionError(f"writes under {pref} are blocked")
    raw = content.encode("utf-8")
    if len(raw) > _MAX_WRITE_BYTES:
        raise ValueError(f"content too large (>{_MAX_WRITE_BYTES} bytes)")
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return {"ok": True, "path": rel_s, "bytes": len(raw)}


def str_replace(root: Path, rel: str, old: str, new: str) -> dict[str, Any]:
    root = root.resolve()
    fp = resolve_under(root, rel)
    if not fp.is_file():
        raise FileNotFoundError(str(fp.relative_to(root)))
    text = fp.read_text(encoding="utf-8")
    if old not in text:
        return {"ok": False, "error": "old_string not found", "path": str(fp.relative_to(root))}
    count = text.count(old)
    if count != 1:
        return {
            "ok": False,
            "error": f"old_string matched {count} times; need exactly 1",
            "path": str(fp.relative_to(root)),
        }
    updated = text.replace(old, new, 1)
    return write_file(root, rel, updated)


def run_tool(root: Path, call: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    name = (call.get("name") or call.get("tool") or "").strip()
    try:
        if name == "list_dir":
            return {"tool": name, **list_dir(root, call.get("path") or ".")}
        if name == "read_file":
            return {"tool": name, **read_file(root, call.get("path") or "")}
        if name == "write_file":
            return {
                "tool": name,
                **write_file(root, call.get("path") or "", call.get("content") or ""),
            }
        if name == "str_replace":
            return {
                "tool": name,
                **str_replace(
                    root,
                    call.get("path") or "",
                    call.get("old") or call.get("old_string") or "",
                    call.get("new") or call.get("new_string") or "",
                ),
            }
        if name == "finish":
            return {
                "tool": name,
                "ok": True,
                "summary": call.get("summary") or call.get("message") or "done",
            }
        return {"tool": name or "unknown", "ok": False, "error": f"unknown tool: {name!r}"}
    except Exception as e:
        return {"tool": name, "ok": False, "error": f"{type(e).__name__}: {e}"}


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    blobs: list[str] = []
    for rx in (_TOOL_RE, _TOOL_RE_ALT):
        for m in rx.finditer(text or ""):
            blobs.append(m.group(1).strip())
    # Also catch TOOL name / key: value blocks
    for m in re.finditer(
        r"(?:^|\n)TOOL\s+(\w+)\s*\n(.*?)(?:\nEND\b|\n```|\Z)",
        text or "",
        re.DOTALL | re.IGNORECASE,
    ):
        name = m.group(1).strip()
        body = m.group(2)
        fields: dict[str, str] = {"name": name}
        # key: value lines; content/old/new can be multiline until next key
        cur = None
        buf: list[str] = []
        for line in body.splitlines():
            km = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
            if km and km.group(1).lower() in (
                "path",
                "old",
                "new",
                "old_string",
                "new_string",
                "content",
                "summary",
                "message",
            ):
                if cur:
                    fields[cur] = "\n".join(buf).rstrip("\n")
                cur = km.group(1).lower()
                if cur == "old_string":
                    cur = "old"
                if cur == "new_string":
                    cur = "new"
                if cur == "message":
                    cur = "summary"
                buf = [km.group(2)] if km.group(2) else []
            else:
                if cur is not None:
                    buf.append(line)
        if cur:
            fields[cur] = "\n".join(buf).rstrip("\n")
        if fields.get("name"):
            calls.append(fields)

    for raw in blobs:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # Best-effort repair for small-model JSON damage
            obj = _loose_json_tool(raw)
        if isinstance(obj, dict) and (obj.get("name") or obj.get("tool")):
            if obj.get("tool") and not obj.get("name"):
                obj = {**obj, "name": obj.get("tool")}
            # Ignore model hallucinating tool *results* as calls
            if obj.get("ok") is True and "content" in obj and obj.get("name") == "write_file":
                # still allow write_file with content
                pass
            if set(obj.keys()) <= {"tool", "ok", "truncated", "bytes", "path", "entries", "error"}:
                # looks like a result echo, not a call — skip unless it has write content
                if not (obj.get("name") in ("write_file", "str_replace") and (
                    obj.get("content") or obj.get("new") or obj.get("old")
                )):
                    continue
            calls.append(obj)
    return calls


def _loose_json_tool(raw: str) -> dict[str, Any] | None:
    """Recover name/path/old/new/content from near-JSON tool payloads."""
    name_m = re.search(r'"(?:name|tool)"\s*:\s*"([^"]+)"', raw) or re.search(
        r"'(?:name|tool)'\s*:\s*'([^']+)'", raw
    )
    if not name_m:
        name_m = re.search(r"\b(?:name|tool)\s*[:=]\s*[\"']?([A-Za-z_]+)", raw)
    if not name_m:
        return None
    out: dict[str, Any] = {"name": name_m.group(1)}
    for key in ("path", "summary"):
        m = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', raw)
        if m:
            out[key] = bytes(m.group(1), "utf-8").decode("unicode_escape")
    for key in ("content", "old", "new", "old_string", "new_string"):
        # Non-strict: from "key": " until the last " before } 
        m = re.search(rf'"{key}"\s*:\s*"(.*)"\s*\}}\s*$', raw, re.DOTALL)
        if not m:
            m = re.search(rf'"{key}"\s*:\s*"(.*)', raw, re.DOTALL)
        if m:
            val = m.group(1)
            val = re.sub(r'"\s*\}\s*$', "", val.strip())
            # unescape common sequences
            val = (
                val.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
            k = "old" if key == "old_string" else "new" if key == "new_string" else key
            out[k] = val
    return out


AGENT_SYSTEM = """You are Windhover Agent, a local coding assistant.
You change files ONLY inside the user workspace by calling tools.
Follow the USER task only — never invent a different app or demo task.

## Tools (emit exactly ONE tool per reply)

Format A — line form:

TOOL <name>
<path or fields>
END

Allowed names and fields:
- list_dir      path: <relative dir, or .>
- read_file     path: <relative file>
- write_file    path: <relative file>
                content: <full new file text>
- str_replace   path: <relative file>
                old: <exact text to find — copy from a prior read_file result>
                new: <replacement text>
- finish        summary: <what you did for THIS user request>

You may also use a fenced JSON tool block (one tool only):

```tool
{"name":"list_dir","path":"."}
```

```tool
{"name":"read_file","path":"<relative-file>"}
```

```tool
{"name":"str_replace","path":"<relative-file>","old":"<exact old text>","new":"<replacement>"}
```

```tool
{"name":"finish","summary":"<what you did for this user request>"}
```

## Hard rules
- Do what the user asked. Paths and code must match THEIR workspace and request.
- NEVER replay format examples, sample paths, or sample code as your answer.
- NEVER claim the project is some other invented app (or invent unrelated filenames) unless the user said so.
- Prefer list_dir or read_file first when you need context.
- Prefer str_replace for small edits; copy old text EXACTLY from read_file output.
- After a successful write_file/str_replace that completes the request, call finish.
- Do not invent tools. Do not escape the workspace. UTF-8 only. Be concise.
"""

# Phrases/paths from older prompts that tiny models still regurgitate.
_ECHO_MARKERS = (
    '"""Return a + b."""',
    "Return a + b.",
    'content: print("hi")',
    'print("hi")',
    "This app is a simple calculator",
    "performs basic arithmetic operations",
    "path: hello.py",
    "def add(a, b):",
    "Here is a sample user task",
    "sample user task",
)


def looks_like_format_echo(text: str, user_prompt: str) -> bool:
    """True when the model is parroting demo tool scripts instead of the user task."""
    t = text or ""
    if not t.strip():
        return False
    prompt_l = (user_prompt or "").lower()
    hits = 0
    for marker in _ECHO_MARKERS:
        if marker in t:
            # Allow if the user actually asked about that content.
            if marker.lower() in prompt_l:
                continue
            # Special-case: user mentioned add/hello intentionally.
            if "hello.py" in marker and "hello.py" in prompt_l:
                continue
            if "def add" in marker and ("def add" in prompt_l or "add(a" in prompt_l):
                continue
            if "calculator" in marker.lower() and "calculator" in prompt_l:
                continue
            hits += 1
    # Multiple demo tools dumped in one reply is a strong echo signal.
    demo_tools = sum(
        1
        for name in ("read_file", "str_replace", "write_file", "list_dir", "finish")
        if re.search(rf"(?:^|\n)TOOL\s+{name}\b", t, re.IGNORECASE)
    )
    if demo_tools >= 3 and hits >= 1:
        return True
    return hits >= 2


def workspace_listing(root: str | Path, limit: int = 40) -> str:
    """Short top-level listing so the model grounds on real files."""
    try:
        info = list_dir(Path(root), ".")
    except Exception as e:
        return f"(could not list workspace: {type(e).__name__}: {e})"
    lines = []
    for e in info.get("entries") or []:
        kind = "dir" if e.get("type") == "dir" else "file"
        lines.append(f"- {e.get('path')} ({kind})")
        if len(lines) >= limit:
            lines.append("- …")
            break
    return "\n".join(lines) if lines else "(empty workspace)"


def build_agent_messages(
    *,
    user_prompt: str,
    workspace_root: str,
    history: list[dict[str, str]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    listing = workspace_listing(workspace_root)
    msgs: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                AGENT_SYSTEM
                + f"\n\nWorkspace root: {workspace_root}\n"
                + "Paths in tools are relative to this root.\n\n"
                + "Current workspace (top level):\n"
                + listing
            ),
        }
    ]
    for h in history or []:
        role = h.get("role") or "user"
        content = (h.get("content") or "").strip()
        if content and role in ("user", "assistant"):
            msgs.append({"role": role, "content": content})
    msgs.append(
        {
            "role": "user",
            "content": (
                "USER TASK (do only this):\n"
                + (user_prompt or "").strip()
                + "\n\nRespond with exactly one tool call for this task."
            ),
        }
    )
    if tool_results:
        blob = json.dumps(tool_results, indent=2)[:40_000]
        msgs.append(
            {
                "role": "user",
                "content": (
                    "Tool results from the last step(s):\n```json\n"
                    + blob
                    + "\n```\nContinue the USER TASK above. Call another tool or finish. "
                    "Do not switch to an unrelated demo."
                ),
            }
        )
    return msgs
