import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiUrl } from "./api";
import { cleanChatText, extractSSE } from "./chatText";
import { AdvancedView } from "./components/AdvancedView";
import { AgentView } from "./components/AgentView";
import { AppSidebar } from "./components/AppSidebar";
import { ChatView } from "./components/ChatView";
import { LibraryView } from "./components/LibraryView";
import { RailIcon, type Tab } from "./components/RailIcon";
import {
  formatCount,
  formatParams,
  isMacSmall,
  isOllamaModel,
  matchInstalled,
  modelPickerLabel,
  type CatalogModel,
  type Installed,
} from "./modelMeta";
import type { AgentStep, ChatStats, EngineState, HfModelInfo, Msg, PullProgress } from "./types";

export function App() {
  const [tab, setTab] = useState<Tab>("agent");
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [installed, setInstalled] = useState<Installed[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [engineOk, setEngineOk] = useState<boolean | null>(null);
  const [enginePresent, setEnginePresent] = useState<boolean | null>(null);
  const [family, setFamily] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [activeModel, setActiveModel] = useState<string>("");
  const [stats, setStats] = useState<{
    rss_mb?: number;
    engine?: string;
    engine_present?: boolean;
    installed?: number;
    last?: ChatStats;
    chat_preview?: string;
  } | null>(null);
  const [lastStats, setLastStats] = useState<ChatStats | null>(null);
  const [confirmUninstall, setConfirmUninstall] = useState<{ id: string; name: string; path?: string } | null>(
    null
  );
  const [progress, setProgress] = useState<PullProgress | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [agentInput, setAgentInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [agentSummary, setAgentSummary] = useState("");
  const [agentPrompt, setAgentPrompt] = useState("");
  const [agentStatus, setAgentStatus] = useState("");
  const [agentPhase, setAgentPhase] = useState("");
  const [pickingFolder, setPickingFolder] = useState(false);
  const [tree, setTree] = useState<Array<{ name: string; path: string; type: string; size?: number | null }>>([]);
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const [updateInfo, setUpdateInfo] = useState<{
    available?: boolean;
    current?: string;
    latest?: string;
    download_url?: string | null;
    html_url?: string;
    error?: string | null;
    name?: string | null;
  } | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateMsg, setUpdateMsg] = useState("");
  const [modelInfoOpen, setModelInfoOpen] = useState<CatalogModel | null>(null);
  const [modelInfo, setModelInfo] = useState<HfModelInfo | null>(null);
  const [modelInfoBusy, setModelInfoBusy] = useState(false);
  const [modelInfoErr, setModelInfoErr] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef<string | null>(null);
  const progressRef = useRef<PullProgress | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  const chatCapable = useMemo(
    () => installed.filter((m) => m.chat_ok && !m.impostor),
    [installed]
  );

  const ollamaInstalled = useMemo(
    () => installed.filter((m) => isOllamaModel(m) && m.chat_ok),
    [installed]
  );

  async function refresh() {
    try {
      const health = await fetch(apiUrl("/health")).then((r) => r.json());
      setEngineOk(!!health?.ok);
      if (health?.version) setAppVersion(String(health.version));
      setEnginePresent(
        typeof health?.engine_present === "boolean"
          ? health.engine_present
          : typeof health?.engine_on === "boolean"
            ? health.engine_on
            : null
      );
      const [c, i, s] = await Promise.all([
        fetch(apiUrl("/v1/catalog")).then((r) => r.json()),
        fetch(apiUrl("/api/installed")).then((r) => r.json()),
        fetch(apiUrl("/api/stats"))
          .then((r) => r.json())
          .catch(() => null),
      ]);
      const models = c.models || [];
      const list = (i.data || []) as Installed[];
      setCatalog(models);
      setInstalled(list);
      if (s) {
        setStats(s);
        if (typeof s.engine_present === "boolean") setEnginePresent(s.engine_present);
        if (s.last && typeof s.last === "object") setLastStats(s.last as ChatStats);
      }
      if (health?.stats) setLastStats(health.stats);
      // Don't wipe download / uninstall status from the 5s poller
      if (!busyRef.current && !progressRef.current) setStatus("");
      setActiveModel((prev) => {
        const ok = list.filter((m) => m.chat_ok && !m.impostor);
        if (prev && ok.some((m) => m.id === prev || m.id === prev.replace("/", "__"))) return prev;
        return ok[0] ? String(ok[0].id) : "";
      });
    } catch {
      setEngineOk(false);
      setEnginePresent(false);
      try {
        const c = await fetch("./catalog.json").then((r) => r.json());
        setCatalog(c.models || []);
        setStatus("Engine offline — open the Mac app or run ./windhover app");
      } catch {
        setStatus("Start Windhover: open the Mac app, or run ./windhover app");
      }
    }
  }

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 5000);
    return () => clearInterval(t);
  }, []);

  async function checkForUpdate(force = false) {
    try {
      const q = force ? "?force=1" : "";
      const j = await fetch(apiUrl(`/v1/update${q}`)).then((r) => r.json());
      setUpdateInfo(j);
      if (j?.current) setAppVersion(String(j.current));
      if (force && !j?.available) {
        setUpdateMsg(j?.error || (j?.latest ? `You're on the latest version (${j.latest}).` : "No update available."));
      }
      return j;
    } catch (e) {
      setUpdateMsg(`Update check failed: ${e instanceof Error ? e.message : String(e)}`);
      return null;
    }
  }

  async function applyUpdate() {
    if (updateBusy) return;
    setUpdateBusy(true);
    setUpdateMsg("Downloading update…");
    try {
      const j = await fetch(apiUrl("/v1/update/apply"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ download_url: updateInfo?.download_url || undefined }),
      }).then((r) => r.json());
      if (j?.ok) {
        setUpdateMsg(
          String(
            j.message ||
              "Installing update — Windhover will restart on the new version automatically."
          )
        );
        // Keep busy: the process is about to be replaced / killed by the installer.
        return;
      }
      setUpdateMsg(String(j?.error || "Update failed."));
      if (updateInfo?.html_url) {
        window.open(updateInfo.html_url, "_blank", "noopener,noreferrer");
      }
    } catch (e) {
      setUpdateMsg(`Update failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setUpdateBusy(false);
  }

  useEffect(() => {
    const t = setTimeout(() => void checkForUpdate(false), 2500);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (family === "ollama") return [];
    return catalog.filter((m) => {
      if (family === "mac") {
        if (!isMacSmall(m)) return false;
      } else if (family !== "all" && (m.family || "other") !== family) {
        return false;
      }
      if (!q) return true;
      const hay = `${m.name} ${m.id} ${m.description} ${(m.tags || []).join(" ")}`.toLowerCase();
      return hay.includes(q);
    });
  }, [catalog, family, query]);

  const filteredOllama = useMemo(() => {
    if (family !== "all" && family !== "ollama") return [];
    const q = query.trim().toLowerCase();
    return ollamaInstalled.filter((m) => {
      if (!q) return true;
      const hay = `${m.name || ""} ${m.id} ${m.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [ollamaInstalled, family, query]);

  const activeMeta = useMemo(
    () => matchInstalled(chatCapable, activeModel) || chatCapable[0],
    [chatCapable, activeModel]
  );

  async function pull(m: CatalogModel, weights = false) {
    const autoWeights = isMacSmall(m);
    let useWeights = weights || autoWeights;
    if (m.status === "download" && !useWeights) {
      const ok = confirm(
        `${m.name} is ~${m.size_gb} GB from Hugging Face.\n\n` +
          `Windhover will NOT install a fake stub. Continue with a real download?\n\n` +
          `For Mac 16GB local chat under 20GB, use the Mac 16GB filter instead.`
      );
      if (!ok) return;
      useWeights = true;
    }
    setBusy(m.id);
    setProgress({ id: m.id, pct: 1, message: `Starting ${m.name}…` });
    setStatus(
      useWeights || isMacSmall(m)
        ? `Downloading ${m.name} (~${m.size_gb} GB)…`
        : `Installing ${m.name}…`
    );
    try {
      const r = await fetch(apiUrl("/api/pull"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: m.id, weights: useWeights, async: true }),
      });
      const j = await r.json();
      if (j.async && j.job_id) {
        // Poll job progress until done/error
        for (;;) {
          await new Promise((res) => setTimeout(res, 450));
          const st = await fetch(apiUrl(`/api/jobs/${j.job_id}`)).then((x) => x.json());
          if (st.error === "unknown job") {
            setStatus("Lost download job — try again");
            setProgress(null);
            break;
          }
          const pct = Number(st.pct) || 0;
          const message = String(st.message || st.error || `Downloading ${m.name}…`);
          setProgress({
            id: m.id,
            pct,
            message,
            bytes: typeof st.bytes === "number" ? st.bytes : undefined,
          });
          setStatus(message);
          if (st.status === "done") {
            setStatus(`Installed ${m.name}`);
            setProgress({ id: m.id, pct: 100, message: "Installed" });
            if (isMacSmall(m) || m.chat === "engine") {
              setActiveModel(m.id);
            }
            break;
          }
          if (st.status === "error") {
            setStatus(st.error || `Failed: ${m.id}`);
            setProgress(null);
            break;
          }
        }
      } else if (j.ok) {
        setStatus(`Installed ${m.name}`);
        setProgress({ id: m.id, pct: 100, message: "Installed" });
        if (isMacSmall(m) || m.chat === "engine") {
          setActiveModel(m.id);
        }
      } else {
        setStatus(j.error || `Failed: ${m.id}`);
        setProgress(null);
      }
      await refresh();
      // Clear progress bar shortly after success
      setTimeout(() => setProgress((p) => (p?.id === m.id && p.pct >= 100 ? null : p)), 1200);
    } catch (e) {
      setStatus(String(e));
      setProgress(null);
    } finally {
      setBusy(null);
    }
  }

  async function uninstall(id: string, name?: string, path?: string) {
    // Prefer in-app confirm — window.confirm is unreliable in the Tauri webview.
    setConfirmUninstall({ id, name: name || id, path });
  }

  async function confirmUninstallNow() {
    if (!confirmUninstall) return;
    const { id, name, path } = confirmUninstall;
    setConfirmUninstall(null);
    setBusy(id);
    setStatus(`Uninstalling ${name}…`);
    try {
      const r = await fetch(apiUrl("/api/uninstall"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, path }),
      });
      const j = await r.json();
      if (j.ok) {
        setStatus(`Uninstalled ${name}`);
        if (activeModel === id || activeModel.replace("/", "__") === id.replace("/", "__")) {
          setActiveModel("");
          setMessages([]);
        }
      } else {
        setStatus(j.error || `Failed to uninstall ${id}`);
      }
      await refresh();
    } catch (e) {
      setStatus(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function openChat(id: string) {
    const inst = matchInstalled(installed, id);
    if (!inst?.chat_ok) {
      setStatus("That pack can’t chat — install a Hugging Face model from Library (Mac 16GB), or start Ollama.");
      return;
    }
    setActiveModel(id);
    setMessages([]);
    setTab("chat");
  }

  async function pollPrepareJob(jobId: string, modelLabel: string) {
    setProgress({ id: modelLabel, pct: 50, message: `Preparing ${modelLabel} for engine…` });
    setStatus(`Preparing ${modelLabel} for windhover-engine (one-time convert)…`);
    for (;;) {
      await new Promise((res) => setTimeout(res, 800));
      const st = await fetch(apiUrl(`/api/jobs/${jobId}`)).then((x) => x.json());
      if (st.error === "unknown job") {
        setStatus("Lost prepare job — try Chat again");
        setProgress(null);
        return false;
      }
      const pct = typeof st.pct === "number" ? st.pct : 50;
      setProgress({
        id: modelLabel,
        pct,
        message: String(st.message || `Preparing ${modelLabel}…`),
      });
      if (st.status === "done") {
        setStatus(`${modelLabel} is ready — send your message again`);
        setProgress(null);
        await refresh();
        return true;
      }
      if (st.status === "error") {
        setStatus(String(st.error || st.message || "Engine prepare failed"));
        setProgress(null);
        return false;
      }
    }
  }

  async function openModelInfo(m: CatalogModel) {
    setModelInfoOpen(m);
    setModelInfo(null);
    setModelInfoErr("");
    setModelInfoBusy(true);
    try {
      const repo = m.hf_repo || m.preview_repo || m.id;
      const j = (await fetch(
        apiUrl(`/v1/model-info?repo=${encodeURIComponent(repo)}&model=${encodeURIComponent(m.id)}`)
      ).then((r) => r.json())) as HfModelInfo;
      if (!j?.ok) {
        setModelInfoErr(String(j?.error || "Could not load Hugging Face info."));
      }
      setModelInfo(j);
    } catch (e) {
      setModelInfoErr(e instanceof Error ? e.message : String(e));
    } finally {
      setModelInfoBusy(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    const modelId = activeModel || chatCapable[0]?.id;
    if (!modelId) {
      setStatus("Install a Hugging Face model from Library first (or start Ollama)");
      setTab("library");
      return;
    }
    chatAbortRef.current?.abort();
    const ac = new AbortController();
    chatAbortRef.current = ac;
    const hardTimer = window.setTimeout(() => ac.abort(), 600_000);

    setSending(true);
    setInput("");
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    let assistant = "";
    let gotToken = false;

    const paint = (content: string, stats?: ChatStats) => {
      setMessages([...next, { role: "assistant", content, stats }]);
    };

    const useStream = !isOllamaModel(
      matchInstalled(chatCapable, modelId) || { id: modelId }
    );

    async function postChat(stream: boolean) {
      return fetch(apiUrl("/v1/chat/completions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ac.signal,
        body: JSON.stringify({
          model: modelId,
          messages: next.map(({ role, content }) => ({ role, content })),
          max_tokens: 256,
          temperature: 0.35,
          stream,
        }),
      });
    }

    try {
      let r: Response;
      let streaming = useStream;
      try {
        r = await postChat(streaming);
      } catch (e) {
        // Tauri/WebView sometimes rejects SSE (CORS / HTTP1.1 framing). Fall back once.
        if (streaming && !ac.signal.aborted) {
          streaming = false;
          r = await postChat(false);
        } else {
          throw e;
        }
      }

      const ctype = r.headers.get("content-type") || "";
      if (!streaming || !ctype.includes("text/event-stream")) {
        const j = await r.json();
        const st = (j?.stats || {}) as ChatStats;
        if (typeof j?.engine_active === "boolean") st.engine_active = j.engine_active;
        if (j?.code === "engine_inactive" || j?.engine_active === false) {
          st.engine_active = false;
          if (j?.error) st.engine_error = String(j.error);
        }
        if (j?.code === "engine_preparing" || (r.status === 202 && j?.job_id)) {
          const label = String(j?.id || modelId);
          paint(
            String(j?.error || "") ||
              `Preparing ${label} for windhover-engine. This is a one-time convert and can take a few minutes. Send again when it finishes.`,
            { engine_active: false, backend: "preparing" }
          );
          setSending(false);
          await pollPrepareJob(String(j.job_id), label);
          return;
        }
        if (!r.ok || j?.code === "engine_inactive") {
          const errMsg =
            String(j?.error || `Chat failed (${r.status})`) +
            (j?.detail ? `\n\n${j.detail}` : "");
          setLastStats(st);
          setStatus(
            j?.code === "engine_inactive" || r.status === 503
              ? "Windhover engine is not active"
              : String(j?.error || "Chat failed")
          );
          paint(errMsg, { ...st, engine_active: false, backend: st.backend || "error" });
          void refresh();
          return;
        }
        const content = j?.choices?.[0]?.message?.content || j?.error || "No response.";
        setLastStats(st);
        paint(cleanChatText(String(content)), st);
        void refresh();
        return;
      }

      if (!r.ok || !r.body) {
        paint(`Chat failed (${r.status})`);
        setStatus("Chat request failed");
        return;
      }

      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      let finalStats: ChatStats | undefined;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const { data, rest } = extractSSE(buf);
        buf = rest;
        for (const line of data) {
          if (!line || line === "[DONE]") continue;
          let obj: {
            error?: string;
            code?: string;
            detail?: string;
            stats?: ChatStats;
            message?: { role?: string; content?: string };
            choices?: Array<{ delta?: { content?: string }; finish_reason?: string | null }>;
          };
          try {
            obj = JSON.parse(line);
          } catch {
            continue;
          }
          if (obj.error || obj.code === "engine_inactive") {
            const errMsg =
              String(obj.error || "Engine inactive") + (obj.detail ? `\n\n${obj.detail}` : "");
            paint(errMsg, {
              ...(obj.stats || {}),
              engine_active: false,
              backend: "error",
            });
            setStatus(obj.code === "engine_inactive" ? "Windhover engine is not active" : String(obj.error));
            return;
          }
          if (obj.stats) finalStats = obj.stats;
          const piece = obj.choices?.[0]?.delta?.content;
          if (piece) {
            gotToken = true;
            assistant += piece;
            paint(cleanChatText(assistant), finalStats);
          }
          // Server final cleaned text replaces streamed raw (cuts trailing junk).
          if (obj.choices?.[0]?.finish_reason === "stop" && typeof obj.message?.content === "string") {
            gotToken = true;
            assistant = obj.message.content;
            paint(cleanChatText(assistant) || "No response.", finalStats);
          }
        }
      }
      if (!gotToken && !assistant.trim()) {
        paint("No response from the model. Try again, or pick another installed model.");
      } else {
        paint(cleanChatText(assistant) || "No response.", finalStats);
        if (finalStats) setLastStats(finalStats);
      }
      void refresh();
    } catch (e) {
      if (ac.signal.aborted) {
        paint(assistant.trim() ? `${assistant}\n\n_(stopped)_` : "Chat stopped.");
        setStatus("Chat cancelled");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        const friendly =
          /failed to fetch|networkerror|load failed/i.test(msg)
            ? "Could not reach the Windhover server (Failed to fetch). Is the app/API running on port 8000? Try Send again."
            : msg;
        setMessages([...next, { role: "assistant", content: friendly }]);
        setStatus("Chat request failed — is Windhover running?");
      }
    } finally {
      window.clearTimeout(hardTimer);
      if (chatAbortRef.current === ac) chatAbortRef.current = null;
      setSending(false);
    }
  }

  function stopChat() {
    chatAbortRef.current?.abort();
  }

  async function loadWorkspaceTree() {
    try {
      const treeR = await fetch(apiUrl("/api/workspace/tree?path=.")).then((x) => x.json());
      if (treeR.ok) {
        setTree(treeR.entries || []);
        setWorkspaceReady(true);
        return true;
      }
      setTree([]);
      setAgentStatus(treeR.error || "Could not list folder");
      return false;
    } catch (e) {
      setTree([]);
      setAgentStatus(String(e));
      return false;
    }
  }

  async function applyWorkspace(path?: string) {
    const root = (path ?? workspace).trim();
    if (!root) {
      // Empty field: open the native picker instead of failing silently.
      await browseWorkspace();
      return;
    }
    setAgentStatus(`Setting workspace…`);
    try {
      const r = await fetch(apiUrl("/api/workspace"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root }),
      });
      const j = await r.json();
      if (!j.ok) {
        setWorkspaceReady(false);
        setTree([]);
        setAgentStatus(j.error || "Could not set workspace");
        setStatus(j.error || "Could not set workspace");
        return;
      }
      setWorkspace(String(j.root));
      setStatus(`Workspace: ${j.root}`);
      setAgentStatus(`Using ${j.root}`);
      await loadWorkspaceTree();
    } catch (e) {
      setWorkspaceReady(false);
      setAgentStatus(String(e));
      setStatus(String(e));
    }
  }

  async function browseWorkspace() {
    if (agentBusy || pickingFolder) return;
    setPickingFolder(true);
    setAgentStatus("Choose a folder…");
    try {
      const r = await fetch(apiUrl("/api/workspace/pick"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const j = await r.json();
      if (j.cancelled) {
        setAgentStatus("Folder picker cancelled");
        return;
      }
      if (!j.ok || !j.root) {
        setWorkspaceReady(false);
        setTree([]);
        setAgentStatus(j.error || "Could not pick folder");
        setStatus(j.error || "Could not pick folder");
        return;
      }
      setWorkspace(String(j.root));
      setStatus(`Workspace: ${j.root}`);
      setAgentStatus(`Using ${j.root}`);
      await loadWorkspaceTree();
    } catch (e) {
      setWorkspaceReady(false);
      setAgentStatus(String(e));
      setStatus(String(e));
    } finally {
      setPickingFolder(false);
    }
  }

  async function runAgent() {
    const text = agentInput.trim();
    if (!text || agentBusy) return;
    const modelId = activeModel || chatCapable[0]?.id;
    if (!modelId) {
      setStatus("Install a chat-capable model from Library first");
      setTab("library");
      return;
    }
    if (!workspace.trim()) {
      setStatus("Select a workspace folder first");
      return;
    }
    setAgentBusy(true);
    setAgentSteps([]);
    setAgentSummary("");
    setAgentPrompt(text);
    setAgentInput("");
    setAgentStatus("Starting…");
    setAgentPhase("start");
    setStatus("Agent running…");
    try {
      await applyWorkspace(workspace);
      const r = await fetch(apiUrl("/api/agent"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: modelId,
          workspace,
          prompt: text,
          max_steps: 8,
          max_tokens: 384,
          temperature: 0.15,
          async: true,
        }),
      });
      const j = await r.json();
      if (!j.ok) {
        setStatus(j.error || "Agent failed");
        setAgentSummary(String(j.error || "failed"));
        setAgentStatus(String(j.error || "failed"));
        return;
      }
      // Sync fallback (older servers)
      if (!j.async || !j.job_id) {
        setAgentSteps((j.steps || []) as AgentStep[]);
        setAgentSummary(String(j.summary || ""));
        setAgentStatus("Done");
        setAgentPhase("done");
        setStatus("Agent finished");
        return;
      }
      const jobId = String(j.job_id);
      for (;;) {
        await new Promise((res) => setTimeout(res, 400));
        const st = await fetch(apiUrl(`/api/jobs?id=${encodeURIComponent(jobId)}`)).then((x) =>
          x.json()
        );
        if (Array.isArray(st.steps)) setAgentSteps(st.steps as AgentStep[]);
        if (st.message) setAgentStatus(String(st.message));
        if (st.phase) setAgentPhase(String(st.phase));
        if (st.status === "done") {
          const result = st.result || {};
          setAgentSteps((result.steps || st.steps || []) as AgentStep[]);
          setAgentSummary(String(result.summary || st.summary || ""));
          setAgentStatus("Done");
          setAgentPhase("done");
          setStatus("Agent finished");
          break;
        }
        if (st.status === "error") {
          setAgentSummary(String(st.error || st.message || "Agent failed"));
          setAgentStatus(String(st.error || st.message || "failed"));
          setAgentPhase("error");
          setStatus(String(st.error || "Agent failed"));
          break;
        }
      }
      const treeR = await fetch(apiUrl("/api/workspace/tree?path=.")).then((x) => x.json());
      if (treeR.ok) setTree(treeR.entries || []);
    } catch (e) {
      setStatus(String(e));
      setAgentSummary(String(e));
      setAgentStatus(String(e));
      setAgentPhase("error");
    } finally {
      setAgentBusy(false);
    }
  }

  const engineTitle =
    engineOk === false
      ? "Windhover API unreachable"
      : enginePresent === false
        ? "API up, but windhover-engine binary missing — run ./windhover build"
        : lastStats?.engine_active === false
          ? lastStats.engine_error ||
            "Last reply did not use windhover-engine — engine inactive for that turn"
          : engineOk
            ? "Windhover API online · windhover-engine ready"
            : "Checking…";
  const engineState: EngineState =
    engineOk === false
      ? "off"
      : enginePresent === false || lastStats?.engine_active === false
        ? "warn"
        : engineOk
          ? "on"
          : "";
  const engineInactiveBanner =
    engineOk === false
      ? "Windhover API offline — open the Mac app or run ./windhover app"
      : enginePresent === false
        ? "Windhover engine is not active — binary missing. Run ./windhover build, then restart."
        : lastStats?.engine_active === false
          ? lastStats.engine_error ||
            "Windhover engine is not active for the last reply (fallback or failure)."
          : null;

  const modelSelect = (
    <select
      className="model-select"
      value={activeModel}
      onChange={(e) => {
        setActiveModel(e.target.value);
        if (tab === "chat") setMessages([]);
      }}
      disabled={!chatCapable.length}
      aria-label="Model"
    >
      {!chatCapable.length ? (
        <option value="">Install a model or start Ollama</option>
      ) : null}
      {chatCapable.map((m) => (
        <option key={m.id} value={m.id}>
          {modelPickerLabel(m)}
        </option>
      ))}
    </select>
  );

  return (
    <div className="shell">
      {confirmUninstall && typeof document !== "undefined"
        ? createPortal(
            <div className="modal-backdrop" role="dialog" aria-modal="true">
              <div className="modal">
                <h2>Uninstall model?</h2>
                <p>
                  Remove <strong>{confirmUninstall.name}</strong> from this Mac? This deletes local
                  files under <code>~/.windhover/models</code>.
                </p>
                <div className="modal-actions">
                  <button type="button" className="btn ghost" onClick={() => setConfirmUninstall(null)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn primary danger-fill"
                    onClick={() => void confirmUninstallNow()}
                  >
                    Uninstall
                  </button>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}

      {modelInfoOpen && typeof document !== "undefined"
        ? createPortal(
            <div
              className="modal-backdrop"
              role="dialog"
              aria-modal="true"
              onClick={() => setModelInfoOpen(null)}
            >
              <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
                <h2>{modelInfoOpen.name}</h2>
                <p className="muted mono">{modelInfoOpen.hf_repo || modelInfoOpen.id}</p>
                {modelInfoBusy ? <p className="muted">Loading Hugging Face data…</p> : null}
                {modelInfoErr ? <p className="status-err">{modelInfoErr}</p> : null}
                {modelInfo?.ok ? (
                  <>
                    <div className="info-grid">
                      <div>
                        <span className="info-k">Downloads</span>
                        <strong>{formatCount(modelInfo.downloads)}</strong>
                      </div>
                      <div>
                        <span className="info-k">Likes</span>
                        <strong>{formatCount(modelInfo.likes)}</strong>
                      </div>
                      <div>
                        <span className="info-k">Parameters</span>
                        <strong>{formatParams(modelInfo.parameters)}</strong>
                      </div>
                      <div>
                        <span className="info-k">License</span>
                        <strong>{modelInfo.license || modelInfoOpen.license || "—"}</strong>
                      </div>
                      <div>
                        <span className="info-k">Pipeline</span>
                        <strong>{modelInfo.pipeline_tag || "—"}</strong>
                      </div>
                      <div>
                        <span className="info-k">Library</span>
                        <strong>{modelInfo.library_name || "—"}</strong>
                      </div>
                    </div>
                    {modelInfo.card_summary ? (
                      <p className="info-summary">{modelInfo.card_summary}</p>
                    ) : (
                      <p className="muted">{modelInfoOpen.description}</p>
                    )}
                    {modelInfo.benchmarks && modelInfo.benchmarks.length > 0 ? (
                      <div className="bench-wrap">
                        <h3>Benchmarks</h3>
                        <table className="bench-table">
                          <thead>
                            <tr>
                              <th>Dataset</th>
                              <th>Metric</th>
                              <th>Value</th>
                            </tr>
                          </thead>
                          <tbody>
                            {modelInfo.benchmarks.slice(0, 24).map((b, i) => (
                              <tr key={i}>
                                <td>{b.dataset || b.task || "—"}</td>
                                <td>{b.metric || "—"}</td>
                                <td>
                                  {typeof b.value === "number"
                                    ? Number.isInteger(b.value)
                                      ? b.value
                                      : b.value.toFixed(3)
                                    : b.value ?? "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="muted">No published model-index benchmarks on this card yet.</p>
                    )}
                    {modelInfo.tags && modelInfo.tags.length ? (
                      <div className="tag-row">
                        {modelInfo.tags.slice(0, 16).map((t) => (
                          <span className="tag-chip" key={t}>
                            {t}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </>
                ) : null}
                <div className="modal-actions">
                  <button type="button" className="btn ghost" onClick={() => setModelInfoOpen(null)}>
                    Close
                  </button>
                  {modelInfo?.html_url || modelInfoOpen.hf_repo ? (
                    <a
                      className="btn primary"
                      href={
                        modelInfo?.html_url ||
                        `https://huggingface.co/${modelInfoOpen.hf_repo || modelInfoOpen.id}`
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      Hugging Face
                    </a>
                  ) : null}
                </div>
              </div>
            </div>,
            document.body
          )
        : null}

      <header className="titlebar">
        <div className="traffic-spacer" aria-hidden />
        <span className="titlebar-label">Windhover</span>
        <div className="titlebar-end">
          {updateInfo?.available ? (
            <button
              type="button"
              className="btn update-btn"
              disabled={updateBusy}
              onClick={() => void applyUpdate()}
              title={`Update to ${updateInfo.latest}`}
            >
              {updateBusy ? "Updating…" : `Update to ${updateInfo.latest}`}
            </button>
          ) : null}
          <span className={`status-dot ${engineState}`} title={engineTitle} />
        </div>
      </header>

      {updateInfo?.available ? (
        <div className="update-banner" role="status">
          <span>
            Windhover {updateInfo.latest} is ready
            {updateInfo.current ? ` · you have ${updateInfo.current}` : ""}.
          </span>
          <button type="button" className="btn primary" disabled={updateBusy} onClick={() => void applyUpdate()}>
            {updateBusy ? "Updating…" : "Update"}
          </button>
          {updateMsg ? <span className="update-msg">{updateMsg}</span> : null}
        </div>
      ) : null}

      <div className="app-frame">
        <nav className="rail" aria-label="Primary">
          <button type="button" className="rail-brand" title="Windhover" onClick={() => setTab("agent")}>
            <img src="./windhover-icon.png" alt="" width={28} height={28} />
          </button>
          {(
            [
              { id: "agent" as Tab, label: "Agent" },
              { id: "chat" as Tab, label: "Chat" },
              { id: "library" as Tab, label: "Library" },
              { id: "advanced" as Tab, label: "Settings" },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`rail-btn${tab === item.id ? " active" : ""}`}
              aria-label={item.label}
              aria-current={tab === item.id ? "page" : undefined}
              title={item.label}
              onClick={() => setTab(item.id)}
            >
              <RailIcon name={item.id} />
            </button>
          ))}
          <div className="rail-spacer" />
          <div className={`rail-engine ${engineState}`} title={engineTitle} aria-hidden>
            <i className="dot" />
          </div>
        </nav>

        <AppSidebar
          tab={tab}
          chatCapable={chatCapable}
          activeModel={activeModel}
          onSelectModel={(id) => {
            setActiveModel(id);
            if (tab === "chat") setMessages([]);
          }}
          onNewChat={() => {
            setMessages([]);
            setInput("");
          }}
          engineTitle={engineTitle}
          engineState={engineState}
          lastStats={lastStats}
          rssMb={Number(stats?.rss_mb ?? lastStats?.rss_mb ?? 0)}
          workspace={workspace}
          onWorkspaceChange={(value) => {
            setWorkspace(value);
            setWorkspaceReady(false);
          }}
          workspaceReady={workspaceReady}
          agentBusy={agentBusy}
          pickingFolder={pickingFolder}
          onBrowseWorkspace={() => void browseWorkspace()}
          onApplyWorkspace={() => void applyWorkspace()}
          agentStatus={agentStatus}
          tree={tree}
          query={query}
          onQueryChange={setQuery}
          family={family}
          onFamilyChange={setFamily}
          catalogCount={filtered.length}
          ollamaCount={filteredOllama.length}
          appVersion={appVersion || updateInfo?.current || ""}
        />

        <main className={`work-main tab-${tab}`}>
          {tab === "library" ? (
            <LibraryView
              status={status}
              progress={progress}
              family={family}
              filtered={filtered}
              filteredOllama={filteredOllama}
              installed={installed}
              busy={busy}
              onOpenInfo={(m) => void openModelInfo(m)}
              onPull={(m, weights) => void pull(m, weights)}
              onUninstall={(id, name, path) => void uninstall(id, name, path)}
              onOpenChat={(id) => void openChat(id)}
              onUseInAgent={(id) => {
                setActiveModel(id);
                setTab("agent");
              }}
            />
          ) : null}

          {tab === "chat" ? (
            <ChatView
              messages={messages}
              sending={sending}
              input={input}
              onInput={setInput}
              onSend={() => void send()}
              onStop={stopChat}
              chatCapable={chatCapable.length > 0}
              modelSelect={modelSelect}
              threadRef={threadRef}
              emptyHint={
                activeMeta
                  ? `${activeMeta.name || activeMeta.id}${isOllamaModel(activeMeta) ? " · Ollama" : ""}`
                  : "Install a model from Library, or start Ollama."
              }
              banner={messages.length || sending ? engineInactiveBanner : null}
            />
          ) : null}

          {tab === "agent" ? (
            <AgentView
              agentSteps={agentSteps}
              agentBusy={agentBusy}
              agentPrompt={agentPrompt}
              agentInput={agentInput}
              onInput={setAgentInput}
              onRun={() => void runAgent()}
              chatCapable={chatCapable.length > 0}
              modelSelect={modelSelect}
              workspaceReady={workspaceReady}
              agentPhase={agentPhase}
              agentStatus={agentStatus}
              agentSummary={agentSummary}
            />
          ) : null}

          {tab === "advanced" ? (
            <AdvancedView
              appVersion={appVersion}
              updateInfo={updateInfo}
              updateMsg={updateMsg}
              updateBusy={updateBusy}
              onCheckUpdate={() => void checkForUpdate(true)}
              onApplyUpdate={() => void applyUpdate()}
              onRefresh={() => void refresh()}
              engineOk={engineOk}
              enginePresent={enginePresent}
              engineState={engineState}
              lastStats={lastStats}
              stats={stats}
              activeModel={activeModel}
              chatCapableCount={chatCapable.length}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}
