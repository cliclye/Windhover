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
  * shell commands need explicit approval unless auto-run is on

No network tools. Paths cannot escape the workspace (resolve_under).
"""
from __future__ import annotations

import difflib
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

How to work:
1. Look before you change: list_dir / search / read_file the relevant files.
2. Make focused edits with edit_file (copy `old` exactly from read_file output). Use write_file for new files.
3. Check your work when it makes sense (e.g. run the tests).
4. When the request is done, reply in plain text WITHOUT a tool block: briefly say what you changed.
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
        self.auto_run = False
        self.version = 0
        self._approvals: dict[str, threading.Event] = {}
        self._approval_answer: dict[str, bool] = {}
        self.created = _now()
        self.turns = 0
        self.stats: dict[str, Any] = {}

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
                "version": self.version,
                "events": list(self.events),
                "pending_approval": pending[0]["id"] if pending else None,
                "changed_files": sorted({c["path"] for c in self.changes.values() if not c.get("undone")}),
                "stats": dict(self.stats),
            }

    # ------------------------------------------------------------ control
    def stop(self) -> None:
        self.stop_flag = True
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

    def _tool_edit(self, rel: str, old: str, new: str) -> dict[str, Any]:
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
            rel_s = str(fp.relative_to(self.root))
            aw.write_file(self.root, rel_s, after)
            return {"ok": True, "path": rel_s, "appended": True, **self._record_change(rel_s, before, after)}
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
        rel_s = str(fp.relative_to(self.root))
        aw.write_file(self.root, rel_s, after)
        return {"ok": True, "path": rel_s, **self._record_change(rel_s, before, after)}

    def _tool_write(self, rel: str, content: str) -> dict[str, Any]:
        if not rel:
            return {"ok": False, "error": "write_file needs a path"}
        fp = aw.resolve_under(self.root, rel)
        before = fp.read_text(encoding="utf-8") if fp.is_file() else None
        if before and before.strip() and not content.strip():
            return {"ok": False, "error": f"refusing to overwrite {rel} with empty content"}
        if content and not content.endswith("\n"):
            content += "\n"
        res = aw.write_file(self.root, rel, content)
        return {**res, "created": before is None, **self._record_change(res["path"], before, content)}

    def _tool_run(self, command: str, ev: dict[str, Any]) -> dict[str, Any]:
        if not command.strip():
            return {"ok": False, "error": "run needs a command"}
        if not self.auto_run:
            gate = threading.Event()
            self._approvals[ev["id"]] = gate
            self._update(ev, status="approval", summary=f"Run: {command.strip()[:160]}")
            gate.wait(APPROVAL_TIMEOUT_S)
            self._approvals.pop(ev["id"], None)
            approved = self._approval_answer.pop(ev["id"], False)
            if self.stop_flag:
                return {"ok": False, "error": "stopped by user"}
            if not approved:
                self._update(ev, status="denied")
                return {"ok": False, "denied": True, "error": "The user declined to run this command."}
            self._update(ev, status="running")
        t0 = _now()
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
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
            if name == "edit_file":
                return self._tool_edit(str(call.get("path") or ""), str(call.get("old") or ""),
                                       str(call.get("new") if call.get("new") is not None else ""))
            if name == "write_file":
                return self._tool_write(str(call.get("path") or ""), str(call.get("content") or ""))
            if name == "run":
                return self._tool_run(str(call.get("command") or call.get("cmd") or ""), ev)
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
                    total = sum(len(x["content"]) for x in self.history)
                    if total <= CONTEXT_CHARS:
                        break
        # Merge consecutive same-role messages (chat templates expect alternation).
        for m in self.history:
            if msgs and msgs[-1]["role"] == m["role"] and m["role"] != "system":
                msgs[-1] = {"role": m["role"], "content": msgs[-1]["content"] + "\n\n" + m["content"]}
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        return msgs

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
        return re.sub(r"\n{3,}", "\n\n", t).strip()

    # ------------------------------------------------------------ the loop
    def run_turn(self, text: str, *, max_tokens: int = 768, temperature: float = 0.15) -> None:
        with self.lock:
            if self.busy:
                raise RuntimeError("agent is already working")
            self.busy = True
            self.stop_flag = False
        self.turns += 1
        self._emit({"type": "user", "text": text})
        self.history.append({"role": "user", "content": text})
        seen: set[tuple] = set()
        steps = 0
        nudges = 0
        try:
            while steps < MAX_STEPS and not self.stop_flag:
                steps += 1
                live = self._emit({"type": "assistant", "text": "", "streaming": True, "step": steps})
                buf: list[str] = []

                def on_delta(piece: str) -> None:
                    buf.append(piece)
                    # Hold back a fence opener that may still turn into ```tool.
                    vis = self._visible(re.sub(r"`{1,3}(?:t|to|too|tool|j|js|jso|json)?\Z", "",
                                               "".join(buf)))
                    if vis != live.get("text"):
                        self._update(live, text=vis)

                t0 = _now()
                raw, stats = self.generate(self._messages(), max_tokens, temperature, on_delta)
                raw = (raw or "").strip()
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
                if not calls and not visible and nudges < 2 and steps < MAX_STEPS:
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
                if not calls and nudges < 2 and steps < MAX_STEPS and _announces_next_step(visible):
                    nudges += 1
                    self.history.append({"role": "assistant", "content": raw})
                    self.history.append({"role": "user", "kind": "nudge", "content":
                                         "Go ahead — reply with exactly one tool block to do that now."})
                    continue
                if not calls or (calls[0].get("name") == "finish"):
                    # Plain-text reply (or finish) ends the turn.
                    final = visible or (calls[0].get("summary") if calls else "") or (
                        "Done." if calls else
                        "The model returned no reply. Try again, or pick a larger model for this task.")
                    self._update(live, text=final, final=True)
                    self.history.append({"role": "assistant", "content": raw or final})
                    return
                call = calls[0]
                name = (call.get("name") or "").strip()
                self.history.append({"role": "assistant", "content": raw})
                if not visible:
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
                if key in seen and name in ("list_dir", "read_file", "search"):
                    res = {"ok": True, "note": "already done — the result is earlier in this conversation"}
                    self._update(ev, status="skipped", summary="Skipped repeat")
                    self.history.append({"role": "user", "kind": "result", "content":
                                         f"You already ran {name} with the same arguments; its result is above. "
                                         "Do not repeat it. Continue with the next step or answer in plain text."})
                    continue
                seen.add(key)
                res = self._execute(call, ev)
                status = "denied" if res.get("denied") else ("ok" if res.get("ok") else "error")
                summary = self._summary(name, call, res)
                self._update(ev, status=status, summary=summary, result=self._ui_result(name, res),
                             change_id=res.get("change_id"))
                self.history.append({"role": "user", "kind": "result",
                                     "content": self._result_text(name, call, res)})
            if self.stop_flag:
                self._emit({"type": "notice", "text": "Stopped."})
            else:
                self._emit({"type": "notice", "text": f"Stopped after {MAX_STEPS} steps — send a follow-up to continue."})
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
            return f"Declined: {call.get('command', '')}"
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
        if name == "run":
            return f"Ran `{res.get('command')}` → exit {res.get('exit_code')} ({res.get('seconds')}s)"
        return name

    @staticmethod
    def _ui_result(name: str, res: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("diff", "output", "exit_code", "matches", "path", "error", "added", "removed"):
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
