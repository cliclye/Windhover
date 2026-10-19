import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  codeApi,
  EFFORTS,
  MODES,
  type CodeEffort,
  type CodeEvent,
  type CodeMode,
  type CodeSnapshot,
  type CodeToolEvent,
  type TreeEntry,
} from "../codeApi";
import type { Attachment } from "../images";
import { Composer } from "./Composer";
import { BrainIcon, ChevronIcon, CloseIcon, FileIcon, FolderIcon, PlusIcon, RetryIcon, ShieldIcon } from "./Icons";
import { MarkdownBody } from "./MarkdownBody";

function stored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

type OpenFile = { path: string; content: string; saved: string; loading?: boolean; error?: string };
type Pane = { kind: "file"; path: string } | { kind: "diff"; eventId: string };

const STARTERS = [
  "Give me an overview of this project.",
  "Find and fix any obvious bugs.",
  "Add tests for the main module and run them.",
  "Add docstrings to functions that are missing them.",
];

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="diff">
      {diff.split("\n").map((l, i) => {
        const cls = l.startsWith("+++") || l.startsWith("---")
          ? "meta"
          : l.startsWith("@@")
            ? "hunk"
            : l.startsWith("+")
              ? "add"
              : l.startsWith("-")
                ? "del"
                : "";
        return (
          <span key={i} className={cls}>
            {l || " "}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}

function CodeEditor({
  value,
  onChange,
  onSave,
}: {
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
}) {
  const ta = useRef<HTMLTextAreaElement>(null);
  const gutter = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => value.split("\n").length, [value]);
  return (
    <div className="editor">
      <div className="editor-gutter" ref={gutter} aria-hidden>
        {Array.from({ length: lines }, (_, i) => (
          <span key={i}>{i + 1}</span>
        ))}
      </div>
      <textarea
        ref={ta}
        className="editor-text"
        value={value}
        spellCheck={false}
        wrap="off"
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
            e.preventDefault();
            onSave();
          } else if (e.key === "Tab" && !e.shiftKey) {
            e.preventDefault();
            const el = e.currentTarget;
            const { selectionStart: a, selectionEnd: b } = el;
            const next = value.slice(0, a) + "    " + value.slice(b);
            onChange(next);
            requestAnimationFrame(() => el.setSelectionRange(a + 4, a + 4));
          }
        }}
        aria-label="File editor"
      />
    </div>
  );
}

function ToolCard({
  ev,
  onOpenDiff,
  onOpenFile,
  onApprove,
  onUndo,
}: {
  ev: CodeToolEvent;
  onOpenDiff: (id: string) => void;
  onOpenFile: (path: string) => void;
  onApprove: (id: string, ok: boolean) => void;
  onUndo: (changeId: string) => void;
}) {
  const r = ev.result || {};
  const path = (ev.args.path as string) || r.path;
  const editing = ev.name === "edit_file" || ev.name === "write_file";
  const icon =
    ev.status === "running" ? "spin" : ev.status === "error" ? "bad" : ev.status === "approval" ? "ask" : ev.status;
  let details: ReactNode = null;
  if (ev.name === "run") {
    details = (
      <>
        <pre className="term">
          <span className="term-cmd">$ {String(ev.args.command || "")}</span>
          {r.output ? `\n${r.output}` : ev.status === "running" ? "\n…" : ""}
        </pre>
      </>
    );
  } else if (editing && r.diff) {
    details = <DiffView diff={r.diff} />;
  } else if (ev.name === "search" && r.matches?.length) {
    details = <pre className="term">{r.matches.slice(0, 40).join("\n")}</pre>;
  } else if (ev.name === "list_dir" && r.entries?.length) {
    details = <pre className="term">{r.entries.join("\n")}</pre>;
  } else if (ev.status === "error" && r.error) {
    details = <pre className="term">{r.error}</pre>;
  }
  return (
    <div className={`tcard ${ev.status}${ev.undone ? " undone" : ""}`}>
      <details open={ev.status === "approval" || (editing && ev.status === "ok" && !ev.undone)}>
        <summary>
          <i className={`tdot ${icon}`} />
          <span className="tsum">{ev.summary || `${ev.name} ${path || ""}`}</span>
          {editing && ev.status === "ok" && r.diff ? (
            <span className="tbadge">
              <b className="plus">+{r.added ?? 0}</b> <b className="minus">−{r.removed ?? 0}</b>
            </span>
          ) : null}
        </summary>
        {details}
      </details>
      {ev.status === "approval" ? (
        <div className="tapprove">
          <span>{editing ? "Apply this change?" : "Run this command in your project?"}</span>
          <button type="button" className="btn ghost sm" onClick={() => onApprove(ev.id, false)}>
            {editing ? "Reject" : "Deny"}
          </button>
          <button type="button" className="btn primary sm" onClick={() => onApprove(ev.id, true)}>
            {editing ? "Apply" : "Run"}
          </button>
        </div>
      ) : null}
      {editing && ev.status === "ok" && ev.change_id ? (
        <div className="tactions">
          {path ? (
            <button type="button" className="linkbtn" onClick={() => onOpenFile(path)}>
              Open file
            </button>
          ) : null}
          <button type="button" className="linkbtn" onClick={() => onOpenDiff(ev.id)}>
            View diff
          </button>
          {ev.undone ? (
            <span className="tundone">Undone</span>
          ) : (
            <button type="button" className="linkbtn" onClick={() => onUndo(ev.change_id!)}>
              Undo
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function CodeView({
  modelPicker,
  activeModel,
  chatCapable,
  onOpenLibrary,
}: {
  modelPicker: ReactNode;
  activeModel: string;
  chatCapable: boolean;
  onOpenLibrary: () => void;
}) {
  const [root, setRoot] = useState<string>(() => {
    try {
      return localStorage.getItem("wh.code.root") || "";
    } catch {
      return "";
    }
  });
  const [pathInput, setPathInput] = useState(root);
  const [tree, setTree] = useState<Record<string, TreeEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["."]));
  const [files, setFiles] = useState<OpenFile[]>([]);
  const [pane, setPane] = useState<Pane | null>(null);
  const paneRef = useRef<Pane | null>(null);
  paneRef.current = pane;
  const [snap, setSnap] = useState<CodeSnapshot | null>(null);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [mode, setMode] = useState<CodeMode>(() =>
    stored("wh.code.mode", MODES.map((m) => m.id), "ask")
  );
  const [effort, setEffort] = useState<CodeEffort>(() =>
    stored("wh.code.effort", EFFORTS.map((e) => e.id), "medium")
  );
  const [status, setStatus] = useState("");
  const [starting, setStarting] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const seenVersion = useRef(-1);
  const editsSeen = useRef<Set<string>>(new Set());

  const busy = !!snap?.busy || starting;
  const sessionId = snap?.session_id || "";

  useEffect(() => {
    try {
      localStorage.setItem("wh.code.mode", mode);
      localStorage.setItem("wh.code.effort", effort);
    } catch {
      /* ignore */
    }
  }, [mode, effort]);

  // Mode/effort apply to the running session too (e.g. switch to Bypass mid-task).
  function changeMode(m: CodeMode) {
    setMode(m);
    if (sessionId) void codeApi.settings(sessionId, { mode: m });
  }
  function changeEffort(e: CodeEffort) {
    setEffort(e);
    if (sessionId) void codeApi.settings(sessionId, { effort: e });
  }
  function cycleMode() {
    const i = MODES.findIndex((m) => m.id === mode);
    changeMode(MODES[(i + 1) % MODES.length].id);
  }

  // ---------------------------------------------------------------- workspace
  const loadDir = useCallback(async (dir: string) => {
    const r = await codeApi.tree(dir);
    if (r.ok) setTree((t) => ({ ...t, [dir]: r.entries || [] }));
    else setStatus(r.error || "Could not list folder");
  }, []);

  const openWorkspace = useCallback(
    async (path: string) => {
      const p = path.trim();
      if (!p) return;
      const r = await codeApi.setWorkspace(p);
      if (!r.ok || !r.root) {
        setStatus(r.error || "Could not open folder");
        return;
      }
      setRoot(r.root);
      setPathInput(r.root);
      try {
        localStorage.setItem("wh.code.root", r.root);
      } catch {
        /* ignore */
      }
      setTree({});
      setExpanded(new Set(["."]));
      setFiles([]);
      setPane(null);
      setSnap(null);
      setStatus("");
      await loadDir(".");
    },
    [loadDir]
  );

  useEffect(() => {
    if (root) void openWorkspace(root);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function pickFolder() {
    const r = await codeApi.pickWorkspace();
    if (r.cancelled) return;
    if (!r.ok || !r.root) {
      setStatus(r.error || "Could not pick a folder");
      return;
    }
    await openWorkspace(r.root);
  }

  // -------------------------------------------------------------------- files
  const openFile = useCallback(async (path: string, force = false) => {
    setPane({ kind: "file", path });
    let known = false;
    setFiles((fs) => {
      known = fs.some((f) => f.path === path);
      return known ? fs : [...fs, { path, content: "", saved: "", loading: true }];
    });
    if (known && !force) return;
    const r = await codeApi.readFile(path);
    setFiles((fs) =>
      fs.map((f) =>
        f.path === path
          ? r.ok
            ? { path, content: r.content || "", saved: r.content || "" }
            : { ...f, loading: false, error: r.error || "Cannot open" }
          : f
      )
    );
  }, []);

  async function saveFile(path: string) {
    const f = files.find((x) => x.path === path);
    if (!f) return;
    const r = await codeApi.writeFile(path, f.content);
    if (r.ok) setFiles((fs) => fs.map((x) => (x.path === path ? { ...x, saved: x.content } : x)));
    else setStatus(r.error || "Save failed");
  }

  function closeFile(path: string) {
    const f = files.find((x) => x.path === path);
    if (f && f.content !== f.saved && !confirm(`Discard unsaved changes to ${path}?`)) return;
    const rest = files.filter((x) => x.path !== path);
    setFiles(rest);
    if (pane?.kind === "file" && pane.path === path) setPane(rest.length ? { kind: "file", path: rest[rest.length - 1].path } : null);
  }

  // -------------------------------------------------------------------- agent
  const applySnapshot = useCallback(
    (s: CodeSnapshot) => {
      if (s.version === seenVersion.current) return;
      seenVersion.current = s.version;
      setSnap(s);
      // Agent edited files: refresh tree + any clean open copies.
      for (const ev of s.events) {
        if (ev.type !== "tool" || ev.status !== "ok") continue;
        if (!["edit_file", "write_file"].includes(ev.name)) continue;
        const key = `${ev.id}:${ev.undone ? 1 : 0}`;
        if (editsSeen.current.has(key)) continue;
        editsSeen.current.add(key);
        const p = (ev.result?.path as string) || (ev.args.path as string);
        if (!p) continue;
        const dir = p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : ".";
        void loadDir(dir);
        setFiles((fs) => {
          const f = fs.find((x) => x.path === p);
          if (f && f.content === f.saved) void openFileRefresh(p);
          return fs;
        });
        // Show the file the agent just changed when the editor is free.
        if (!paneRef.current) void openFile(p, true);
      }
    },
    [loadDir] // eslint-disable-line react-hooks/exhaustive-deps
  );

  async function openFileRefresh(path: string) {
    const r = await codeApi.readFile(path);
    if (r.ok) setFiles((fs) => fs.map((f) => (f.path === path ? { path, content: r.content || "", saved: r.content || "" } : f)));
  }

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await codeApi.get(sessionId);
        if (alive && s.ok) applySnapshot(s);
      } catch {
        /* server restarting */
      }
    };
    const t = setInterval(tick, busy ? 500 : 2500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [sessionId, busy, applySnapshot]);

  useEffect(() => {
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [snap?.version]);

  async function send(text: string, atts: Attachment[] = []) {
    const msg = text.trim();
    if ((!msg && !atts.length) || busy) return;
    if (!root) {
      setStatus("Choose a project folder first.");
      return;
    }
    if (!activeModel) {
      setStatus("Install a model first.");
      return;
    }
    setInput("");
    setAttachments([]);
    setStatus("");
    let sid = sessionId;
    if (!sid) {
      setStarting(true);
      const s = await codeApi.start(root, activeModel, mode, effort);
      setStarting(false);
      if (!s.ok) {
        setStatus(s.error || "Could not start the agent");
        setInput(msg);
        setAttachments(atts);
        return;
      }
      applySnapshot(s);
      sid = s.session_id;
    }
    const r = await codeApi.send(
      sid,
      msg,
      activeModel,
      mode,
      effort,
      atts.map((a) => a.dataUrl),
      atts.map((a) => a.thumb)
    );
    if (!r.ok) {
      setStatus(r.error || "Send failed");
      setInput(msg);
      setAttachments(atts);
      return;
    }
    const s = await codeApi.get(sid);
    if (s.ok) applySnapshot(s);
  }

  async function approve(eventId: string, ok: boolean) {
    if (!sessionId) return;
    await codeApi.approve(sessionId, eventId, ok);
  }

  async function undo(changeId: string) {
    if (!sessionId) return;
    const r = await codeApi.undo(sessionId, changeId);
    if (!r.ok) setStatus(r.error || "Undo failed");
    else if (r.path) {
      void openFileRefresh(r.path);
      const dir = r.path.includes("/") ? r.path.slice(0, r.path.lastIndexOf("/")) : ".";
      void loadDir(dir);
    }
    const s = await codeApi.get(sessionId);
    if (s.ok) applySnapshot(s);
  }

  function newSession() {
    if (busy && sessionId) void codeApi.stop(sessionId);
    setSnap(null);
    seenVersion.current = -1;
    editsSeen.current = new Set();
  }

  // -------------------------------------------------------------------- render
  const changed = new Set(snap?.changed_files || []);
  const renderDir = (dir: string, depth: number): ReactNode =>
    (tree[dir] || []).map((e) => {
      const isDir = e.type === "dir";
      const open = expanded.has(e.path);
      const active = pane?.kind === "file" && pane.path === e.path;
      return (
        <div key={e.path}>
          <button
            type="button"
            className={`xrow${active ? " on" : ""}${changed.has(e.path) ? " changed" : ""}`}
            style={{ paddingLeft: 8 + depth * 14 }}
            title={e.path}
            onClick={() => {
              if (isDir) {
                const next = new Set(expanded);
                if (open) next.delete(e.path);
                else {
                  next.add(e.path);
                  if (!tree[e.path]) void loadDir(e.path);
                }
                setExpanded(next);
              } else void openFile(e.path);
            }}
          >
            {isDir ? (
              <span className={`xchev${open ? " open" : ""}`}>
                <ChevronIcon size={12} />
              </span>
            ) : (
              <span className="xchev" />
            )}
            {isDir ? <FolderIcon size={14} /> : <FileIcon size={14} />}
            <span className="xname">{e.name}</span>
            {changed.has(e.path) ? <i className="xmod">M</i> : null}
          </button>
          {isDir && open ? renderDir(e.path, depth + 1) : null}
        </div>
      );
    });

  const activeFile = pane?.kind === "file" ? files.find((f) => f.path === pane.path) : undefined;
  const diffEvent =
    pane?.kind === "diff"
      ? (snap?.events.find((e) => e.id === pane.eventId) as CodeToolEvent | undefined)
      : undefined;
  const events: CodeEvent[] = snap?.events || [];
  const live = events.length && events[events.length - 1].type === "assistant" ? events[events.length - 1] : null;
  const wsName = root ? root.split(/[\\/]/).filter(Boolean).pop() : "";

  return (
    <section className="pane code-pane">
      <div className="code-grid">
        {/* ---------------------------------------------------------- explorer */}
        <aside className="explorer" aria-label="Project files">
          <div className="x-head">
            <span className="x-title" title={root}>
              {wsName || "No folder"}
            </span>
            {root ? (
              <button type="button" className="icon-btn" title="Refresh" aria-label="Refresh files" onClick={() => void loadDir(".")}>
                <RetryIcon size={14} />
              </button>
            ) : null}
          </div>
          {!root ? (
            <div className="x-empty">
              <p>Open a project folder. The agent can only read, edit and run commands inside it.</p>
              <button type="button" className="btn primary sm" onClick={() => void pickFolder()}>
                Choose folder…
              </button>
              <input
                className="x-path"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void openWorkspace(pathInput);
                }}
                placeholder="or paste a path and press Enter"
                spellCheck={false}
                aria-label="Project folder path"
              />
            </div>
          ) : (
            <div className="x-tree">{renderDir(".", 0)}</div>
          )}
          {root ? (
            <button type="button" className="x-switch" onClick={() => void pickFolder()}>
              <FolderIcon size={13} /> Change folder…
            </button>
          ) : null}
        </aside>

        {/* ------------------------------------------------------------ editor */}
        <div className="editor-col">
          <div className="etabs" role="tablist">
            {files.map((f) => (
              <div
                key={f.path}
                role="tab"
                aria-selected={pane?.kind === "file" && pane.path === f.path}
                className={`etab${pane?.kind === "file" && pane.path === f.path ? " on" : ""}`}
              >
                <button type="button" className="etab-name" onClick={() => setPane({ kind: "file", path: f.path })} title={f.path}>
                  {f.path.split("/").pop()}
                  {f.content !== f.saved ? <i className="edirty" /> : null}
                </button>
                <button type="button" className="etab-x" aria-label={`Close ${f.path}`} onClick={() => closeFile(f.path)}>
                  <CloseIcon size={12} />
                </button>
              </div>
            ))}
            {diffEvent ? (
              <div className="etab on diff-tab">
                <span className="etab-name">Diff · {String(diffEvent.result?.path || diffEvent.args.path || "")}</span>
                <button type="button" className="etab-x" aria-label="Close diff" onClick={() => setPane(null)}>
                  <CloseIcon size={12} />
                </button>
              </div>
            ) : null}
          </div>
          <div className="ebody">
            {activeFile ? (
              activeFile.loading ? (
                <div className="e-empty">Loading…</div>
              ) : activeFile.error ? (
                <div className="e-empty">{activeFile.error}</div>
              ) : (
                <>
                  <div className="ebar">
                    <span className="mono">{activeFile.path}</span>
                    <button
                      type="button"
                      className="btn ghost sm"
                      disabled={activeFile.content === activeFile.saved}
                      onClick={() => void saveFile(activeFile.path)}
                    >
                      Save <kbd>⌘S</kbd>
                    </button>
                  </div>
                  <CodeEditor
                    value={activeFile.content}
                    onChange={(v) => setFiles((fs) => fs.map((x) => (x.path === activeFile.path ? { ...x, content: v } : x)))}
                    onSave={() => void saveFile(activeFile.path)}
                  />
                </>
              )
            ) : diffEvent?.result?.diff ? (
              <div className="ediff">
                <DiffView diff={diffEvent.result.diff} />
              </div>
            ) : (
              <div className="e-empty">
                <strong>Windhover Code</strong>
                <span>
                  A coding agent that runs on {activeModel ? activeModel.split("/").pop() : "your local model"} — nothing
                  leaves this computer. Open a file, or ask the agent on the right.
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ------------------------------------------------------------- agent */}
        <div className="agent-col">
          <div className="a-head">
            <strong>Agent</strong>
            <button type="button" className="icon-btn" title="New session" aria-label="New agent session" onClick={newSession}>
              <PlusIcon size={15} />
            </button>
          </div>
          <div className="a-thread" ref={thread}>
            {!events.length ? (
              <div className="a-empty">
                <h3>Build with your local model</h3>
                <p>
                  Ask for a change and the agent reads your code, edits files (with diffs you can undo) and runs
                  commands. {MODES.find((m) => m.id === mode)?.hint}. Paste a screenshot to show it what you mean.
                </p>
                {!chatCapable ? (
                  <button type="button" className="btn primary sm" onClick={onOpenLibrary}>
                    Install a model
                  </button>
                ) : root ? (
                  <div className="a-starters">
                    {STARTERS.map((s) => (
                      <button key={s} type="button" className="starter" onClick={() => void send(s, attachments)}>
                        {s}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              events.map((ev) => {
                if (ev.type === "user")
                  return (
                    <div key={ev.id} className="a-user-wrap">
                      {ev.images?.length ? (
                        <div className="msg-images">
                          {ev.images.map((src, j) => (
                            <img key={j} src={src} alt={`Attached image ${j + 1}`} />
                          ))}
                        </div>
                      ) : null}
                      {ev.text ? <div className="a-user">{ev.text}</div> : null}
                    </div>
                  );
                if (ev.type === "assistant") {
                  if (!ev.text && !ev.streaming && !ev.thinking) return null;
                  const thinkingNow = ev.streaming && !!ev.thinking && !ev.text;
                  return (
                    <div key={ev.id} className={`a-msg${ev.final ? " final" : ""}`}>
                      {ev.thinking ? (
                        <details className="a-think" open={thinkingNow}>
                          <summary>
                            <BrainIcon size={13} />
                            {thinkingNow
                              ? "Thinking…"
                              : ev.thought_seconds
                                ? `Thought for ${Math.max(1, Math.round(ev.thought_seconds))}s`
                                : "Thoughts"}
                          </summary>
                          <div className="a-think-body">{ev.thinking}</div>
                        </details>
                      ) : null}
                      {ev.text ? <MarkdownBody text={ev.text} /> : null}
                      {ev.streaming && !ev.text && !ev.thinking ? (
                        <span className="typing">
                          <i />
                          <i />
                          <i />
                        </span>
                      ) : null}
                    </div>
                  );
                }
                if (ev.type === "tool")
                  return (
                    <ToolCard
                      key={ev.id}
                      ev={ev}
                      onOpenDiff={(id) => setPane({ kind: "diff", eventId: id })}
                      onOpenFile={(p) => void openFile(p, true)}
                      onApprove={(id, ok) => void approve(id, ok)}
                      onUndo={(cid) => void undo(cid)}
                    />
                  );
                return (
                  <div key={ev.id} className={`a-notice ${ev.type}`}>
                    {ev.text}
                  </div>
                );
              })
            )}
            {busy && !(live && live.type === "assistant" && live.streaming) ? (
              <div className="a-working">
                <span className="typing">
                  <i />
                  <i />
                  <i />
                </span>
                {starting ? "Starting the agent…" : snap?.pending_approval ? "Waiting for your approval" : "Working…"}
              </div>
            ) : null}
          </div>
          {status ? <div className="a-status">{status}</div> : null}
          {snap?.stats?.decode_tok_s ? (
            <div className="a-stats">
              {Number(snap.stats.decode_tok_s).toFixed(1)} tok/s
              {snap.stats.prompt_tokens ? ` · ${snap.stats.cached_tokens || 0}/${snap.stats.prompt_tokens} cached` : ""}
              {snap.stats.step_seconds ? ` · ${snap.stats.step_seconds}s/step` : ""}
            </div>
          ) : null}
          <div
            className="a-composer"
            onKeyDown={(e) => {
              // Shift+Tab cycles the permission mode, as in Claude Code.
              if (e.key === "Tab" && e.shiftKey) {
                e.preventDefault();
                cycleMode();
              }
            }}
          >
          <Composer
            value={input}
            onChange={setInput}
            attachments={attachments}
            onAttachments={setAttachments}
            footerRight={
              <div className="a-controls">
                <label className={`pill-select mode-${mode}`} title={`${MODES.find((m) => m.id === mode)?.hint} (⇧Tab to switch)`}>
                  <ShieldIcon size={13} />
                  <select value={mode} onChange={(e) => changeMode(e.target.value as CodeMode)} aria-label="Permission mode">
                    {MODES.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="pill-select" title={EFFORTS.find((x) => x.id === effort)?.hint}>
                  <BrainIcon size={13} />
                  <select value={effort} onChange={(e) => changeEffort(e.target.value as CodeEffort)} aria-label="Effort">
                    {EFFORTS.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            }
            onSubmit={() => void send(input, attachments)}
            onStop={sessionId ? () => void codeApi.stop(sessionId) : undefined}
            busy={busy}
            placeholder={root ? "Ask the agent to change, explain or fix code" : "Choose a project folder first"}
            disabled={!root || !chatCapable}
            footerLeft={modelPicker}
            submitLabel="Send to agent"
            stopLabel="Stop agent"
          />
          </div>
        </div>
      </div>
    </section>
  );
}
