#!/usr/bin/env python3
"""Windhover Code — a local coding agent (Claude Code / Cursor style) driven by
the model windhover-engine is serving.

A CodeSession owns one workspace folder and one conversation. Each user message
runs an agent turn: the local model proposes ONE tool call per step, the host
executes it inside the workspace, the result is appended to the conversation,
and the loop continues until the model answers in plain text (or a step budget
runs out). Everything the UI needs is published as an append-only event list.

Design notes for small local models (0.8B-8B):
  * one tool per reply, three accepted syntaxes (TOOL blocks, ```tool JSON,
    Qwen XML) — parsed by agent_workspace.parse_tool_calls
  * edits are str_replace-style with a whitespace-tolerant fallback, and a
    failed edit returns the current file so the model can retry
  * identical read-only calls are not re-run (prevents read loops)
  * the conversation only ever grows by appending, so the engine's prefix KV
    cache makes every agent step prefill just the new tokens
  * permission modes (as in Claude Code): ask before edits and commands,
    accept edits automatically, plan (read-only), or bypass all prompts
  * effort (low/medium/high/max) sets the per-step token budget and step limit;
    high and max also let models with a reasoning mode think first

No network tools. Paths cannot escape the workspace (resolve_under).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_workspace as aw  # noqa: E402

# generate(messages, max_tokens, temperature, on_delta) -> (text, stats)
GenerateFn = Callable[[list, int, float, Callable[[str], None] | None], tuple[str, dict]]

MAX_STEPS = 14

# Permission modes: what needs the user's OK.
MODES = ("ask", "accept_edits", "plan", "bypass")
MODE_LABELS = {"ask": "Ask before edits", "accept_edits": "Accept edits",
               "plan": "Plan mode", "bypass": "Bypass permissions"}
# effort -> (max tokens per step, max steps per turn, thinking)
# A whole new file must fit in one reply, so even "low" allows ~2k tokens.
EFFORT = {"low": (2048, 10, False), "medium": (4096, 20, False),
          "high": (4096, 30, True), "max": (4096, 50, True)}
PLAN_NOTE = ("(Plan mode is on: explore with list_dir, read_file and search only — do not edit files or "
             "run commands. Finish with a short numbered plan of the changes you would make.)")
RESULT_CHARS = 5000          # per tool result sent to the model
CONTEXT_CHARS = 18000        # ~5k tokens of conversation before compaction
RUN_TIMEOUT_S = 90
RUN_OUTPUT_CHARS = 6000
APPROVAL_TIMEOUT_S = 900
SEARCH_MAX_HITS = 60
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}

SYSTEM_PROMPT = """You are Windhover Code, a coding agent that runs entirely on the user's computer.
You work inside ONE project folder (the workspace) and complete the user's request by using tools.

To use a tool, reply with exactly ONE tool block and nothing after it. Two formats work:

```tool
{"name": "read_file", "path": "src/app.py"}
```

or, best for multi-line code:

TOOL edit_file
path: src/app.py
old:
<exact lines copied from the file>
new:
<replacement lines>
END

Tools:
- list_dir    path            list a folder ("." is the workspace root)
- read_file   path            read a text file
- search      query, path     find text in files (like grep); path is optional
- edit_file   path, old, new  replace the exact text `old` with `new` (old must appear once)
- write_file  path, content   create a new file or overwrite a whole file
- run         command         run a shell command in the workspace (tests, build, git status…)
              add "background": true for things that keep running (dev servers, watchers)

You have real access to the user's project folder and their computer's shell through these tools.
So DO things instead of explaining them:
- When the user asks you to create or change code, SAVE it with write_file / edit_file.
  Never paste a whole file into your reply for the user to copy.
- When the user asks you to run, open, start, install or test something, use run.
  Never tell the user to run a command themselves.
  Open a file or URL in the browser:  run  open calculator.html   (Windows: start "" calculator.html)
  Serve the folder on localhost:  run  python3 -m http.server 8765  with "background": true,
  then run  open http://localhost:8765/calculator.html   (port 8000 is taken by Windhover).

Example — the user says "make a hello page and open it":

```tool
{"name": "write_file", "path": "index.html", "content": "<!DOCTYPE html>\n<html><body><h1>Hello</h1></body></html>"}
```

then, after the result:

```tool
{"name": "run", "command": "open index.html"}
```

then a short plain-text reply such as: Created index.html and opened it in your browser.

How to work:
1. Look before you change: list_dir / search / read_file the relevant files.
2. Make focused edits with edit_file (copy `old` exactly from read_file output). Use write_file for new files.
3. Check your work when it makes sense (e.g. run the tests).
4. When the request is done, reply in plain text WITHOUT a tool block: briefly say what you did (1-3 sentences).
If the user only asked a question, read what you need and then answer in plain text.
Never invent files or results. Stay inside the workspace. One tool per reply."""


# Small models often narrate the next step ("Let me check…") and stop without a
# tool call. Such replies are not final answers: nudge the model to act.
_INTENT_RE = re.compile(
    r"(?:\blet me\b|\bi(?:'ll| will| am going to| need to| should)\b|\bnext,? i\b|\bnow i\b|"
    r"\bi'm going to\b|\blet's\b)",
    re.I,
)


def _announces_next_step(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    tail = t[-240:]
    return bool(_INTENT_RE.search(tail)) or tail.endswith(":")


# A reply that pastes code / tells the user to do it, when the user asked for an action.
_ACTION_RE = re.compile(
    r"\b(?:create|make|build|write|add|implement|generate|fix|change|update|edit|refactor|rename|delete|remove|"
    r"run|open|start|launch|serve|host|install|test|execute|deploy|save|put|show me)\b", re.I)
_DEFER_RE = re.compile(
    r"(?:\bI (?:can(?:'|’)?t|cannot|am unable to|don(?:'|’)?t have)\b|\byou can (?:run|open|use|save|start|double)|"
    r"\bdouble[- ]click\b|\bcopy (?:the|this) code\b|\bsave (?:it|this|the (?:code|file)) as\b|"
    r"\bin your terminal\b|\brun (?:this|the following|`)|\bopen (?:it|the file) in your browser\b)", re.I)
_FENCE_RE = re.compile(r"```[\w+-]*\n(.*?)(?:```|\Z)", re.S)

# Commands that never exit on their own: run them in the background.
_SERVER_RE = re.compile(
    r"(?:http\.server|SimpleHTTPServer|\bnpm (?:run )?(?:dev|start|serve)\b|\byarn (?:dev|start)\b|"
    r"\bpnpm (?:dev|start)\b|\bvite\b(?! build)|\bnext dev\b|\bflask run\b|\buvicorn\b|\bgunicorn\b|"
    r"\bmanage\.py runserver\b|\brails s(?:erver)?\b|\bnpx serve\b|\blive-server\b|\bjekyll serve\b|"
    r"\bhugo server\b|\bphp -S\b)", re.I)


RESERVED_PORTS = {int(p) for p in (os.environ.get("WINDHOVER_PORT") or "8000").split(",") if p.strip().isdigit()}
_HTTP_SERVER_RE = re.compile(r"(\bhttp\.server\b|\bSimpleHTTPServer\b)(\s+(\d+))?")
_PORT_FLAG_RE = re.compile(r"((?:--port|-p|--listen|-l)[= ])(\d{2,5})\b|(\bphp -S [\w.]+:)(\d{2,5})\b")


def _free_port(start: int = 8765) -> int:
    import socket

    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
            try:
                sk.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


_PENDING_NAME_RE = re.compile(r'"name"\s*:\s*"(write_file|edit_file|run)"|(?:^|\n)\s*TOOL\s+(write_file|edit_file|run)\b')
_PENDING_PATH_RE = re.compile(r'"path"\s*:\s*"([^"]+)"|(?:^|\n)\s*path:\s*(\S+)')


def _pending_tool(text: str) -> dict[str, Any] | None:
    """What a still-streaming tool call is doing, for a live "Writing x…" row."""
    m = _PENDING_NAME_RE.search(text or "")
    if not m:
        return None
    name = m.group(1) or m.group(2)
    tail = text[m.start():]
    pm = _PENDING_PATH_RE.search(tail)
    lines = tail.count("\\n") + tail.count("\n")
    return {"name": name, "path": (pm.group(1) or pm.group(2)) if pm else "", "lines": lines}


def _tool_closed(text: str) -> bool:
    """Did the reply finish its tool block (closing fence / END / complete JSON)?"""
    t = text or ""
    i = t.find("```tool")
    if i < 0:
        i = t.find("```json")
    if i >= 0:
        body = t[i + 7:]
        if "```" in body:
            return True
        # Small models sometimes end the fence with END (or nothing): the call is
        # complete if its JSON object is.
        j = body.find("{")
        if j < 0:
            return False
        try:
            json.JSONDecoder().raw_decode(body[j:])
            return True
        except ValueError:
            return False
    # TOOL blocks often omit END; the parser handles that, so treat them as closed.
    return True


def _pasted_code_lines(text: str) -> int:
    return max((len(m.group(1).strip().splitlines()) for m in _FENCE_RE.finditer(text or "")), default=0)


def _now() -> float:
    return time.time()


def _numbered_preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.25):]
    return f"{head}\n… ({len(text) - len(head) - len(tail)} chars omitted) …\n{tail}"


def _diff(path: str, before: str, after: str) -> tuple[str, int, int]:
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return "".join(lines), added, removed


def _loose_replace(text: str, old: str, new: str) -> str | None:
    """Whitespace-tolerant single replacement: match `old` line-by-line ignoring
    trailing whitespace and uniform indentation drift. Returns None if no unique
    match."""
    old_lines = [l.rstrip() for l in old.strip("\n").splitlines()]
    if not old_lines:
        return None
    lines = text.splitlines(keepends=True)
    stripped = [l.rstrip("\r\n").rstrip() for l in lines]
    n = len(old_lines)
    hits = []
    for i in range(len(stripped) - n + 1):
        if all(stripped[i + k].strip() == old_lines[k].strip() for k in range(n)):
            hits.append(i)
    if len(hits) != 1:
        return None
    i = hits[0]
    # Re-indent the replacement to the matched block's indentation.
    have = len(stripped[i]) - len(stripped[i].lstrip())
    want = len(old_lines[0]) - len(old_lines[0].lstrip())
    shift = have - want
    new_lines = new.strip("\n").splitlines()
    if shift > 0:
        new_lines = [(" " * shift + l) if l.strip() else l for l in new_lines]
    elif shift < 0:
        new_lines = [l[-shift:] if l[: -shift].strip() == "" else l for l in new_lines]
    replacement = "".join(l + "\n" for l in new_lines)
    if not lines[i + n - 1].endswith("\n"):
        replacement = replacement.rstrip("\n")
    return "".join(lines[:i]) + replacement + "".join(lines[i + n:])


class CodeSession:
    def __init__(self, root: Path, model: str, generate: GenerateFn):
        self.id = uuid.uuid4().hex[:12]
        self.root = Path(root).resolve()
        self.model = model
        self.generate = generate
        self.history: list[dict[str, str]] = []
        self.events: list[dict[str, Any]] = []
        self.changes: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.busy = False
        self.stop_flag = False
        self.mode = "accept_edits"
        self.effort = "medium"
        self.version = 0
        self._approvals: dict[str, threading.Event] = {}
        self.procs: list[subprocess.Popen] = []  # background commands (dev servers)
        self.port_map: dict[int, int] = {}       # reserved port -> port we moved a server to
        self._approval_answer: dict[str, bool] = {}
        self.created = _now()
        self.turns = 0
        self.stats: dict[str, Any] = {}

    # Older clients toggle a single "auto-run commands" switch.
    @property
    def auto_run(self) -> bool:
        return self.mode == "bypass"

    @auto_run.setter
    def auto_run(self, on: bool) -> None:
        if on:
            self.mode = "bypass"
        elif self.mode == "bypass":
            self.mode = "accept_edits"

    def set_mode(self, mode: str | None) -> None:
        if mode in MODES:
            self.mode = mode

    def set_effort(self, effort: str | None) -> None:
        if effort in EFFORT:
            self.effort = effort

    # ------------------------------------------------------------ events
    def _emit(self, ev: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            ev.setdefault("id", uuid.uuid4().hex[:10])
            ev.setdefault("t", _now())
            self.events.append(ev)
            self.version += 1
            return ev

    def _update(self, ev: dict[str, Any], **kw) -> None:
        with self.lock:
            ev.update(kw)
            self.version += 1

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            pending = [e for e in self.events if e.get("type") == "tool" and e.get("status") == "approval"]
            return {
                "ok": True,
                "session_id": self.id,
                "root": str(self.root),
                "model": self.model,
                "busy": self.busy,
                "auto_run": self.auto_run,
                "mode": self.mode,
                "effort": self.effort,
                "version": self.version,
                "events": list(self.events),
                "pending_approval": pending[0]["id"] if pending else None,
                "changed_files": sorted({c["path"] for c in self.changes.values() if not c.get("undone")}),
                "stats": dict(self.stats),
            }

    # ------------------------------------------------------------ control
    def stop(self) -> None:
        self.stop_flag = True
        if not self.busy:
            self.stop_background()
        for ev in list(self._approvals.values()):
            ev.set()

    def answer_approval(self, event_id: str, approve: bool) -> bool:
        gate = self._approvals.get(event_id)
        if not gate:
            return False
        self._approval_answer[event_id] = bool(approve)
        gate.set()
        return True

    def undo(self, change_id: str) -> dict[str, Any]:
        ch = self.changes.get(change_id)
        if not ch:
            return {"ok": False, "error": "unknown change"}
        if ch.get("undone"):
            return {"ok": False, "error": "already undone"}
        fp = aw.resolve_under(self.root, ch["path"])
        if ch["before"] is None:
            if fp.is_file():
                fp.unlink()
        else:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(ch["before"], encoding="utf-8")
        ch["undone"] = True
        with self.lock:
            for ev in self.events:
                if ev.get("change_id") == change_id:
                    ev["undone"] = True
            self.version += 1
        # Tell the model on its next turn so it does not assume the edit is there.
        self.history.append({"role": "user", "content": f"(The user undid your change to {ch['path']}.)"})
        return {"ok": True, "path": ch["path"]}

    # ------------------------------------------------------------ tools
    def _fix_path(self, rel: str) -> tuple[str, str | None]:
        """If `rel` does not exist but exactly one workspace file has that name,
        use it (small models guess src/ prefixes). Returns (path, note)."""
        rel = (rel or "").strip()
        try:
            if not rel or aw.resolve_under(self.root, rel).exists():
                return rel, None
        except ValueError:
            return rel, None
        name = Path(rel).name
        hits = []
        for fp in self.root.rglob(name):
            if fp.is_file() and not any(p in _SKIP_DIRS for p in fp.relative_to(self.root).parts):
                hits.append(str(fp.relative_to(self.root)))
                if len(hits) > 1:
                    break
        if len(hits) == 1:
            return hits[0], f"{rel} does not exist; using {hits[0]}"
        return rel, None

    def _record_change(self, rel: str, before: str | None, after: str) -> dict[str, Any]:
        diff, added, removed = _diff(rel, before or "", after)
        cid = uuid.uuid4().hex[:10]
        self.changes[cid] = {"id": cid, "path": rel, "before": before, "after": after,
                             "diff": diff, "added": added, "removed": removed, "t": _now()}
        return {"change_id": cid, "diff": diff, "added": added, "removed": removed}

    def _ask(self, ev: dict[str, Any] | None, summary: str, preview: dict[str, Any] | None = None) -> bool | None:
        """Block until the user approves (True) or declines (False); None = stopped."""
        if ev is None:
            return True
        gate = threading.Event()
        self._approvals[ev["id"]] = gate
        self._update(ev, status="approval", summary=summary, **({"result": preview} if preview else {}))
        gate.wait(APPROVAL_TIMEOUT_S)
        self._approvals.pop(ev["id"], None)
        approved = self._approval_answer.pop(ev["id"], False)
        if self.stop_flag:
            return None
        if approved:
            self._update(ev, status="running")
        return approved

    def _commit(self, rel: str, before: str | None, after: str, ev: dict[str, Any] | None,
                **extra) -> dict[str, Any]:
        """Write a file change, first asking the user in "ask" mode (with the diff)."""
        if self.mode == "ask" and ev is not None:
            diff, added, removed = _diff(rel, before or "", after)
            verb = "Create" if before is None else "Edit"
            ok = self._ask(ev, f"{verb} {rel}  +{added} −{removed}",
                           {"diff": diff, "added": added, "removed": removed, "path": rel})
            if ok is None:
                return {"ok": False, "error": "stopped by user"}
            if not ok:
                return {"ok": False, "denied": True, "path": rel,
                        "error": "The user rejected this change. Ask what they want instead, or try another approach."}
        aw.write_file(self.root, rel, after)
        return {"ok": True, "path": rel, **extra, **self._record_change(rel, before, after)}

    def _tool_search(self, query: str, rel: str) -> dict[str, Any]:
        if not query:
            return {"ok": False, "error": "search needs a query"}
        base = aw.resolve_under(self.root, rel or ".")
        hits: list[str] = []
        q = query.lower()
        files = [base] if base.is_file() else base.rglob("*")
        for fp in files:
            if len(hits) >= SEARCH_MAX_HITS:
                break
            if not fp.is_file() or any(p in _SKIP_DIRS for p in fp.relative_to(self.root).parts):
                continue
            try:
                if fp.stat().st_size > 1_000_000:
                    continue
                text = fp.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if q in line.lower():
                    hits.append(f"{fp.relative_to(self.root)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= SEARCH_MAX_HITS:
                        break
        return {"ok": True, "query": query, "matches": hits, "count": len(hits)}

    def _tool_edit(self, rel: str, old: str, new: str, ev: dict[str, Any] | None = None) -> dict[str, Any]:
        if not rel:
            return {"ok": False, "error": "edit_file needs a path"}
        fp = aw.resolve_under(self.root, rel)
        if not fp.is_file():
            return {"ok": False, "error": f"{rel} does not exist — use write_file to create it"}
        before = fp.read_text(encoding="utf-8")
        if not new.strip() and not old.strip():
            return {"ok": False, "error": "edit_file needs `new` text (nothing to add)"}
        if not old.strip():
            # Empty `old`: append (what small models mean by "add a function").
            after = before + ("" if before.endswith("\n") or not before else "\n") + \
                ("\n\n" if before.strip() else "") + new.strip("\n") + "\n"
            return self._commit(str(fp.relative_to(self.root)), before, after, ev, appended=True)
        count = before.count(old)
        if count == 1:
            after = before.replace(old, new, 1)
        elif count > 1:
            return {"ok": False, "error": f"`old` matches {count} places — include more surrounding lines"}
        else:
            after = _loose_replace(before, old, new)
            if after is None:
                return {"ok": False, "path": rel,
                        "error": "`old` text was not found. Copy it exactly from the current file below.",
                        "content": _numbered_preview(before, RESULT_CHARS)}
        if after == before:
            return {"ok": False, "error": "that edit would not change the file"}
        if not new.strip() and len(old.strip().splitlines()) > 3:
            return {"ok": False, "error": "refusing to delete a large block with an empty `new` — "
                                          "put the replacement text after new:"}
        return self._commit(str(fp.relative_to(self.root)), before, after, ev)

    def _tool_write(self, rel: str, content: str, ev: dict[str, Any] | None = None) -> dict[str, Any]:
        if not rel:
            return {"ok": False, "error": "write_file needs a path"}
        fp = aw.resolve_under(self.root, rel)
        before = fp.read_text(encoding="utf-8") if fp.is_file() else None
        if before and before.strip() and not content.strip():
            return {"ok": False, "error": f"refusing to overwrite {rel} with empty content"}
        if before is not None and before.rstrip("\n") == content.rstrip("\n"):
            return {"ok": False, "path": rel, "error": f"{rel} already has exactly this content — nothing changed. "
                                                      "Change the part that is wrong."}
        if content and not content.endswith("\n"):
            content += "\n"
        return self._commit(str(fp.relative_to(self.root)), before, content, ev, created=before is None)

    def _tool_run(self, command: str, ev: dict[str, Any], background: bool = False) -> dict[str, Any]:
        if not command.strip():
            return {"ok": False, "error": "run needs a command"}
        background = background or bool(_SERVER_RE.search(command))
        command, port_note = self._avoid_reserved_ports(command)
        if self.mode != "bypass":
            approved = self._ask(ev, f"Run: {command.strip()[:160]}")
            if approved is None:
                return {"ok": False, "error": "stopped by user"}
            if not approved:
                self._update(ev, status="denied")
                return {"ok": False, "denied": True, "command": command,
                        "error": "The user declined to run this command."}
        t0 = _now()
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        if background:
            res = self._run_background(command, env, t0)
            if port_note:
                res["note"] = port_note
            return res
        try:
            p = subprocess.run(command, shell=True, cwd=str(self.root), capture_output=True,
                               text=True, timeout=RUN_TIMEOUT_S, env=env, errors="replace")
            out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
            code = p.returncode
        except subprocess.TimeoutExpired as e:
            out = ((e.stdout or "") if isinstance(e.stdout, str) else "") + f"\n(timed out after {RUN_TIMEOUT_S}s)"
            code = -1
        out = out.strip()
        if len(out) > RUN_OUTPUT_CHARS:
            out = "…" + out[-RUN_OUTPUT_CHARS:]
        return {"ok": code == 0, "command": command, "exit_code": code, "output": out,
                "seconds": round(_now() - t0, 2)}

    def _avoid_reserved_ports(self, command: str) -> tuple[str, str | None]:
        """Windhover itself listens on 8000: move servers the agent starts to a free
        port, and point later localhost URLs at the moved port."""
        note = None
        m = _HTTP_SERVER_RE.search(command)
        if m:
            port = int(m.group(3)) if m.group(3) else 8000
            if port in RESERVED_PORTS:
                new = _free_port()
                self.port_map[port] = new
                command = command[:m.start()] + f"{m.group(1)} {new}" + command[m.end():]
                note = f"port {port} is used by Windhover, so the server uses port {new}"
        else:
            def sub(mm: re.Match) -> str:
                nonlocal note
                pre, num = (mm.group(1), mm.group(2)) if mm.group(1) else (mm.group(3), mm.group(4))
                port = int(num)
                if port not in RESERVED_PORTS:
                    return mm.group(0)
                new = _free_port()
                self.port_map[port] = new
                note = f"port {port} is used by Windhover, so the server uses port {new}"
                return f"{pre}{new}"
            command = _PORT_FLAG_RE.sub(sub, command)
        for old, new in self.port_map.items():
            command = re.sub(rf"((?:localhost|127\.0\.0\.1|0\.0\.0\.0):){old}\b", rf"\g<1>{new}", command)
        return command, note

    def _run_background(self, command: str, env: dict, t0: float) -> dict[str, Any]:
        """Start a long-running command (dev server, watcher), give it a few seconds,
        and report what it printed. It keeps running until the session stops it."""
        import tempfile

        log = tempfile.NamedTemporaryFile(prefix="windhover-run-", suffix=".log", delete=False)
        kw: dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(command, shell=True, cwd=str(self.root), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, **kw)
        self.procs.append(proc)
        deadline = _now() + 3.0
        while _now() < deadline and proc.poll() is None:
            time.sleep(0.2)
        log.flush()
        try:
            out = Path(log.name).read_text(errors="replace").strip()[-RUN_OUTPUT_CHARS:]
        except OSError:
            out = ""
        code = proc.poll()
        if code is not None:  # exited already: report like a normal command
            return {"ok": code == 0, "command": command, "exit_code": code, "output": out,
                    "seconds": round(_now() - t0, 2)}
        urls = re.findall(r"https?://[\w.\-\[\]:]+(?:/\S*)?", out)
        return {"ok": True, "command": command, "background": True, "pid": proc.pid, "exit_code": None,
                "output": out or "(running, no output yet)", "urls": urls[:3],
                "seconds": round(_now() - t0, 2)}

    def stop_background(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                try:
                    if os.name == "nt":
                        p.terminate()
                    else:
                        os.killpg(p.pid, 15)
                except Exception:
                    pass
        self.procs = []

    def _execute(self, call: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
        name = (call.get("name") or call.get("tool") or "").strip()
        alias = {"str_replace": "edit_file", "edit": "edit_file", "replace": "edit_file",
                 "create_file": "write_file", "grep": "search", "bash": "run", "shell": "run",
                 "run_command": "run", "ls": "list_dir", "cat": "read_file", "open": "read_file"}
        name = alias.get(name, name)
        note = None
        if name in ("read_file", "edit_file") and call.get("path"):
            fixed, note = self._fix_path(str(call.get("path")))
            call = {**call, "path": fixed}
        try:
            res = self._execute_inner(name, call, ev)
        except Exception as e:  # PermissionError, ValueError (path escape), …
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if note:
            res = {**res, "note_path": note}
        return res

    def _execute_inner(self, name: str, call: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "list_dir":
                return aw.list_dir(self.root, call.get("path") or ".")
            if name == "read_file":
                path = (call.get("path") or "").strip()
                if not path:
                    return {"ok": False, "error": "read_file needs a path"}
                fp = aw.resolve_under(self.root, path)
                if fp.is_dir():
                    return {"ok": False, "error": f"{path} is a folder — use list_dir"}
                return aw.read_file(self.root, path)
            if name == "search":
                return self._tool_search(str(call.get("query") or call.get("pattern") or call.get("text") or ""),
                                         str(call.get("path") or "."))
            if name in ("edit_file", "write_file", "run") and self.mode == "plan":
                return {"ok": False, "plan_blocked": True,
                        "error": "Plan mode is on, so files can't be changed and commands can't run. "
                                 "Reply with your plan instead."}
            if name == "edit_file":
                return self._tool_edit(str(call.get("path") or ""), str(call.get("old") or ""),
                                       str(call.get("new") if call.get("new") is not None else ""), ev)
            if name == "write_file":
                return self._tool_write(str(call.get("path") or ""), str(call.get("content") or ""), ev)
            if name == "run":
                bg = str(call.get("background") or "").lower() in ("1", "true", "yes")
                return self._tool_run(str(call.get("command") or call.get("cmd") or ""), ev, bg)
            if name == "finish":
                return {"ok": True, "finish": True, "summary": call.get("summary") or ""}
            return {"ok": False, "error": f"unknown tool {name!r}. Use list_dir, read_file, search, "
                                          "edit_file, write_file or run."}
        except Exception as e:  # PermissionError, ValueError (path escape), …
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ model I/O
    @staticmethod
    def _result_text(name: str, call: dict[str, Any], res: dict[str, Any]) -> str:
        """Compact, model-facing rendering of a tool result."""
        head = f"Result of {name}" + (f" {res.get('path') or call.get('path')}" if call.get("path") else "")
        if res.get("note_path"):
            head = f"(Note: {res['note_path']}.)\n" + head
        if not res.get("ok"):
            body = f"ERROR: {res.get('error')}"
            if res.get("content"):
                body += f"\nCurrent content of {res.get('path')}:\n```\n{res['content']}\n```"
            if res.get("output"):
                body += f"\nOutput:\n```\n{res['output'][-RESULT_CHARS:]}\n```"
            return f"{head}:\n{body}"
        if name == "list_dir":
            lines = [f"{e['path']}{'/' if e['type'] == 'dir' else ''}" for e in res.get("entries", [])]
            return f"{head}:\n" + ("\n".join(lines) or "(empty folder)")
        if name == "read_file":
            return f"{head}:\n```\n{_numbered_preview(res.get('content', ''), RESULT_CHARS)}\n```"
        if name == "search":
            return f"{head} for {res.get('query')!r}: {res.get('count')} matches\n" + "\n".join(res.get("matches", []))
        if name in ("edit_file", "write_file"):
            return (f"{head}: OK, {res.get('path')} saved "
                    f"(+{res.get('added', 0)} -{res.get('removed', 0)} lines).")
        if name == "run" and res.get("background"):
            note = f" Note: {res['note']}." if res.get("note") else ""
            return (f"Started `{res.get('command')}` in the background (pid {res.get('pid')}); it keeps running.{note} "
                    f"Output so far:\n```\n{res.get('output')}\n```")
        if name == "run":
            return (f"Result of run `{res.get('command')}` (exit {res.get('exit_code')}):\n"
                    f"```\n{res.get('output') or '(no output)'}\n```")
        return f"{head}: OK"

    def _messages(self) -> list[dict[str, str]]:
        # The system prompt must stay byte-identical for the whole session: it is the
        # start of every prompt, so any change (e.g. a new .pytest_cache/ in a live
        # listing) would invalidate the engine's prefix KV cache for every step.
        if not getattr(self, "_system", None):
            listing = aw.workspace_listing(self.root, limit=60)
            self._system = (SYSTEM_PROMPT + f"\n\nWorkspace: {self.root.name}\n"
                            f"Top-level files when this session started:\n{listing}")
        sys_msg = self._system
        msgs = [{"role": "system", "content": sys_msg}]
        # Compact old tool results when the conversation outgrows the budget.
        total = sum(len(m["content"]) for m in self.history)
        if total > CONTEXT_CHARS:
            keep_tail = 6
            for m in self.history[:-keep_tail]:
                if m.get("kind") == "result" and not m.get("compacted"):
                    first = m["content"].split("\n", 1)[0]
                    m["content"] = first + "\n(earlier output omitted to save context)"
                    m["compacted"] = True
                elif m.get("kind") == "call" and not m.get("compacted") and len(m["content"]) > 600:
                    # an old write_file / edit_file with a whole file in it
                    m["content"] = m.get("brief") or "(an earlier file change; content omitted to save context)"
                    m["compacted"] = True
                else:
                    continue
                total = sum(len(x["content"]) for x in self.history)
                if total <= CONTEXT_CHARS:
                    break
        # Merge consecutive same-role messages (chat templates expect alternation).
        for m in self.history:
            if msgs and msgs[-1]["role"] == m["role"] and m["role"] != "system":
                merged = {"role": m["role"], "content": msgs[-1]["content"] + "\n\n" + m["content"]}
                imgs = list(msgs[-1].get("images") or []) + list(m.get("images") or [])
                if imgs:
                    merged["images"] = imgs
                msgs[-1] = merged
            else:
                msgs.append({"role": m["role"], "content": m["content"],
                             **({"images": list(m["images"])} if m.get("images") else {})})
        return msgs

    def _unstick(self, stuck: int, unsticks: int, path: str) -> bool:
        """After 3 fruitless steps in a row, hand the model the file it is working on
        and ask it to act. Returns True when a nudge was added."""
        if stuck < 3 or unsticks >= 2:
            return False
        body = ""
        if path:
            try:
                text = aw.resolve_under(self.root, path).read_text(encoding="utf-8")
                body = f"\n\nCurrent content of {path}:\n```\n{_numbered_preview(text, RESULT_CHARS)}\n```"
            except (OSError, ValueError, UnicodeDecodeError):
                body = ""
        self.history.append({"role": "user", "kind": "result", "content":
                             "You are going in circles (repeating searches and reads without changing anything). "
                             "Stop searching. Look at the code below, decide what is wrong, and fix it now with "
                             "edit_file (copy `old` exactly) — or, if you really can't, explain in plain text."
                             + body})
        return True

    @staticmethod
    def _split_thinking(text: str, thinking: bool) -> tuple[str, str]:
        """(thinking, answer). With thinking on, the prompt may already have opened
        <think>, so the reply can start mid-thought and only contain </think>."""
        t = text or ""
        m = re.search(r"<think>(.*?)(?:</think>|\Z)(.*)", t, flags=re.S)
        if m:
            return m.group(1).strip(), (t[:m.start()] + m.group(2)).strip()
        if thinking and "</think>" in t:
            a, b = t.split("</think>", 1)
            return a.strip(), b.strip()
        if thinking and t and "</think>" not in t and not aw.parse_tool_calls(t):
            # still thinking (streaming), or the budget ran out mid-thought
            return t.strip(), ""
        return "", t.strip()

    @staticmethod
    def _visible(text: str) -> str:
        """Assistant prose with tool syntax removed (for the transcript)."""
        # A fence still open at the end (mid-stream) is hidden until it closes.
        t = re.sub(r"```(?:tool|json)\s*\n.*?(?:```|\Z)", "", text or "", flags=re.S | re.I)
        t = re.sub(r"(?:^|\n)TOOL\s+\w+.*?(?:\nEND\b|\Z)", "\n", t, flags=re.S)
        t = re.sub(r"<tool_call>.*?(?:</tool_call>|\Z)", "", t, flags=re.S)
        t = re.sub(r"<function=\w+>.*?(?:</function>|\Z)", "", t, flags=re.S)
        t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
        t = re.sub(r"(?m)^\s*(?:TOOL|END)\s*$", "", t)
        t = re.sub(r'(?ms)^\s*\{\s*"(?:name|tool)"\s*:.*?\}\s*$', "", t)
        # a bare JSON tool call (possibly still streaming) runs to the end of the reply
        t = re.sub(r'\{\s*"(?:name|tool)"\s*:\s*"\w+".*\Z', "", t, flags=re.S)
        return re.sub(r"\n{3,}", "\n\n", t).strip()

    # ------------------------------------------------------------ the loop
    def run_turn(self, text: str, *, max_tokens: int | None = None, temperature: float = 0.15,
                 images: list | None = None, thumbs: list | None = None) -> None:
        """images: data URLs sent to the model; thumbs: small previews for the transcript."""
        with self.lock:
            if self.busy:
                raise RuntimeError("agent is already working")
            self.busy = True
            self.stop_flag = False
        step_tokens, max_steps, thinking = EFFORT.get(self.effort, EFFORT["medium"])
        if max_tokens:
            step_tokens = max_tokens
        self.turns += 1
        uev: dict[str, Any] = {"type": "user", "text": text}
        if thumbs or images:
            uev["images"] = list(thumbs or images or [])[:8]
        self._emit(uev)
        umsg: dict[str, Any] = {"role": "user", "content": text + ("\n\n" + PLAN_NOTE if self.mode == "plan" else "")}
        if images:
            umsg["images"] = list(images)[:8]
        self.history.append(umsg)
        seen: dict[tuple, dict] = {}   # read-only call -> its result message in history
        stuck = 0                      # fruitless steps in a row (repeats, empty searches, errors)
        unsticks = 0
        last_read = ""
        steps = 0
        nudges = 0
        try:
            while steps < max_steps and not self.stop_flag:
                steps += 1
                live = self._emit({"type": "assistant", "text": "", "streaming": True, "step": steps})
                buf: list[str] = []
                t_think = _now()

                def on_delta(piece: str) -> None:
                    buf.append(piece)
                    th, ans = self._split_thinking("".join(buf), thinking)
                    # Hold back a fence opener that may still turn into ```tool.
                    vis = self._visible(re.sub(r"`{1,3}(?:t|to|too|tool|j|js|jso|json)?\Z", "", ans))
                    pend = _pending_tool(ans)
                    if vis != live.get("text") or th != live.get("thinking", "") or pend != live.get("pending"):
                        self._update(live, text=vis, thinking=th, pending=pend)

                t0 = _now()
                kw = {"thinking": True} if thinking else {}
                raw, stats = self.generate(self._messages(), step_tokens, temperature, on_delta, **kw)
                raw = (raw or "").strip()
                thought, raw = self._split_thinking(raw, thinking)
                live.pop("pending", None)
                if thought:
                    self._update(live, thinking=thought, thought_seconds=round(_now() - t_think, 1))
                if os.environ.get("WINDHOVER_CODE_DEBUG"):
                    sys.stderr.write(f"[code] step {steps} raw={raw[:1200]!r}\n")
                self.stats = {
                    "decode_tok_s": (stats.get("windhover") or {}).get("decode_tok_s") or stats.get("tokens_per_sec"),
                    "prompt_tokens": (stats.get("windhover") or {}).get("prompt_tokens"),
                    "cached_tokens": (stats.get("windhover") or {}).get("cached_tokens"),
                    "step_seconds": round(_now() - t0, 2),
                    "backend": stats.get("backend"),
                }
                calls = aw.parse_tool_calls(raw)
                visible = self._visible(raw)
                self._update(live, text=visible, streaming=False, stats=dict(self.stats))
                gen_tokens = int((stats.get("windhover") or {}).get("tokens") or stats.get("completion_tokens") or 0)
                pending = _pending_tool(raw)
                # Only call it cut off when it really ran out of tokens, or the tool call
                # could not be parsed at all (an unterminated block).
                cut_off = bool(pending) and pending["name"] in ("write_file", "edit_file") and (
                    (gen_tokens and gen_tokens >= step_tokens - 4) or not calls or not _tool_closed(raw))
                if cut_off:
                    sys.stderr.write(f"[code] cut-off/unparsed {pending['name']} tokens={gen_tokens}/{step_tokens} "
                                     f"calls={len(calls)} closed={_tool_closed(raw)} raw={raw[:1500]!r} ... "
                                     f"{raw[-400:]!r}\n")
                if cut_off and nudges < 3 and steps < max_steps:
                    # The reply ran out of room in the middle of a file: never save half a file.
                    nudges += 1
                    with self.lock:
                        if live in self.events:
                            self.events.remove(live)
                            self.version += 1
                    self._emit({"type": "tool", "name": pending["name"], "args": {"path": pending["path"]},
                                "status": "error", "summary": f"{pending['path'] or 'File'} was cut off — not saved",
                                "result": {"error": "reply hit the length limit"}})
                    self.history.append({"role": "assistant", "kind": "call", "content": raw,
                                         "brief": f"(tried to write {pending['path']}; the reply was cut off)"})
                    self.history.append({"role": "user", "kind": "nudge", "content":
                                         f"Your reply hit the length limit, so {pending['path'] or 'the file'} was cut "
                                         "off and NOT saved. Write it in parts: write_file with the first part only "
                                         "(keep it under ~120 lines), then add the rest with edit_file using an "
                                         "empty `old` (that appends to the end of the file)."})
                    continue
                if not calls and not visible and nudges < 2 and steps < max_steps:
                    # Empty reply (model stopped at once): ask again instead of ending the turn.
                    nudges += 1
                    with self.lock:
                        if live in self.events:
                            self.events.remove(live)
                            self.version += 1
                    self.history.append({"role": "assistant", "content": raw or "(no reply)"})
                    self.history.append({"role": "user", "kind": "nudge", "content":
                                         "Your reply was empty. Reply with exactly one tool block for the next "
                                         "step, or answer in plain text if the task is done."})
                    continue
                if (not calls and nudges < 2 and steps < max_steps and _ACTION_RE.search(text or "")
                        and (_pasted_code_lines(visible) >= 8 or _DEFER_RE.search(visible))):
                    # The model answered with code to copy or instructions for the user,
                    # but it has tools: make it do the work.
                    nudges += 1
                    with self.lock:
                        if live in self.events:
                            self.events.remove(live)
                            self.version += 1
                    self.history.append({"role": "assistant", "content": raw})
                    self.history.append({"role": "user", "kind": "nudge", "content":
                                         "Don't give me code to copy or steps to do myself — you have tools. "
                                         "Save files with write_file / edit_file and run commands with run "
                                         "(e.g. open a page with: run open <file>). "
                                         "Reply now with exactly one tool block for the next step."})
                    continue
                if not calls and nudges < 2 and steps < max_steps and _announces_next_step(visible):
                    nudges += 1
                    self.history.append({"role": "assistant", "content": raw})
                    self.history.append({"role": "user", "kind": "nudge", "content":
                                         "Go ahead — reply with exactly one tool block to do that now."})
                    continue
                if not calls or (calls[0].get("name") == "finish"):
                    # Plain-text reply (or finish) ends the turn.
                    final = visible or (calls[0].get("summary") if calls else "") or (
                        "Done." if calls else
                        "The model ran out of room while thinking. Try a lower effort, or a larger model."
                        if thought else
                        "The model returned no reply. Try again, or pick a larger model for this task.")
                    self._update(live, text=final, final=True)
                    self.history.append({"role": "assistant", "content": raw or final})
                    return
                call = calls[0]
                name = (call.get("name") or "").strip()
                if name in ("write_file", "edit_file"):
                    self.history.append({"role": "assistant", "kind": "call", "content": raw,
                                         "brief": f"(changed {call.get('path') or 'a file'} with {name})"})
                else:
                    self.history.append({"role": "assistant", "content": raw})
                if not visible and not thought:
                    with self.lock:  # drop the empty prose bubble; the tool card speaks for itself
                        if live in self.events:
                            self.events.remove(live)
                            self.version += 1
                key = (name, str(call.get("path") or ""), str(call.get("query") or ""),
                       str(call.get("command") or ""), str(call.get("old") or "")[:200],
                       str(call.get("content") or "")[:200])
                ev = self._emit({"type": "tool", "name": name,
                                 "args": {k: v for k, v in call.items() if k != "name"},
                                 "status": "running"})
                prior = seen.get(key)
                if prior is not None and not prior.get("compacted") and name in ("list_dir", "read_file", "search"):
                    # Same call, and its result is still in the context: don't run it again.
                    self._update(ev, status="skipped", summary="Skipped repeat")
                    self.history.append({"role": "user", "kind": "result", "content":
                                         f"You already ran {name} with the same arguments; its result is above. "
                                         "Do not repeat it. Continue with the next step or answer in plain text."})
                    stuck += 1
                    if self._unstick(stuck, unsticks, last_read):
                        stuck, unsticks = 0, unsticks + 1
                    continue
                res = self._execute(call, ev)
                if name in ("edit_file", "write_file", "run") and res.get("ok"):
                    # files may have changed: reading them again is not a repeat
                    seen = {k: v for k, v in seen.items() if k[0] not in ("read_file", "list_dir", "search")}
                    stuck = 0
                elif not res.get("ok") or (name == "search" and not res.get("count")):
                    stuck += 1
                if name == "read_file" and res.get("ok"):
                    last_read = str(res.get("path") or call.get("path") or "")
                status = "denied" if res.get("denied") else ("ok" if res.get("ok") else "error")
                summary = self._summary(name, call, res)
                self._update(ev, status=status, summary=summary, result=self._ui_result(name, res),
                             change_id=res.get("change_id"))
                result_msg = {"role": "user", "kind": "result", "content": self._result_text(name, call, res)}
                self.history.append(result_msg)
                if name in ("list_dir", "read_file", "search"):
                    seen[key] = result_msg
                if self._unstick(stuck, unsticks, last_read):
                    stuck, unsticks = 0, unsticks + 1
            if self.stop_flag:
                self._emit({"type": "notice", "text": "Stopped."})
            else:
                self._emit({"type": "notice", "text": f"Stopped after {max_steps} steps — send a follow-up to continue "
                                                      "(or raise the effort for longer tasks)."})
        except Exception as e:
            self._emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            with self.lock:
                self.busy = False
                self.version += 1

    @staticmethod
    def _summary(name: str, call: dict[str, Any], res: dict[str, Any]) -> str:
        p = res.get("path") or call.get("path") or ""
        if res.get("denied"):
            if name == "run":
                return f"Declined: {call.get('command', '')}"
            return f"Rejected change to {p}"
        if res.get("plan_blocked"):
            return f"Plan mode — {name} not run"
        if not res.get("ok"):
            return f"{name} failed{(' · ' + p) if p else ''}: {str(res.get('error') or '')[:140]}"
        if name == "list_dir":
            return f"Listed {res.get('path') or '.'} ({len(res.get('entries', []))} items)"
        if name == "read_file":
            return f"Read {p}"
        if name == "search":
            return f"Searched “{res.get('query')}” — {res.get('count')} matches"
        if name == "edit_file":
            return f"Edited {p}  +{res.get('added', 0)} −{res.get('removed', 0)}"
        if name == "write_file":
            return f"{'Created' if res.get('created') else 'Rewrote'} {p}  +{res.get('added', 0)} −{res.get('removed', 0)}"
        if name == "run" and res.get("background"):
            return f"Started `{res.get('command')}` (running in the background)"
        if name == "run":
            return f"Ran `{res.get('command')}` → exit {res.get('exit_code')} ({res.get('seconds')}s)"
        return name

    @staticmethod
    def _ui_result(name: str, res: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("diff", "output", "exit_code", "matches", "path", "error", "added", "removed",
                  "background", "urls", "pid"):
            if k in res:
                out[k] = res[k]
        if name == "list_dir":
            out["entries"] = [e["path"] for e in res.get("entries", [])][:80]
        if name == "read_file" and res.get("ok"):
            out["lines"] = res.get("content", "").count("\n") + 1
        return out


class SessionStore:
    def __init__(self):
        self._s: dict[str, CodeSession] = {}
        self._lock = threading.Lock()

    def create(self, root: Path, model: str, generate: GenerateFn) -> CodeSession:
        s = CodeSession(root, model, generate)
        with self._lock:
            self._s[s.id] = s
            # keep the store bounded
            if len(self._s) > 24:
                for sid in sorted(self._s, key=lambda k: self._s[k].created)[:-24]:
                    if not self._s[sid].busy:
                        self._s.pop(sid, None)
        return s

    def get(self, sid: str) -> CodeSession | None:
        return self._s.get(sid or "")


STORE = SessionStore()


def _stop_all_background() -> None:
    for sess in list(getattr(STORE, "_s", {}).values()):
        sess.stop_background()


import atexit  # noqa: E402

atexit.register(_stop_all_background)
