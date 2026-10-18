import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "./api";
import { cleanChatText, extractSSE } from "./chatText";
import { loadConversations, newConversation, saveConversations, titleFrom } from "./conversations";
import { AgentView } from "./components/AgentView";
import { ChatView } from "./components/ChatView";
import { LibraryView } from "./components/LibraryView";
import { PerformanceView } from "./components/PerformanceView";
import { Modal, Picker, Segmented, type PickerItem } from "./components/Primitives";
import { SettingsView } from "./components/SettingsView";
import { Sidebar } from "./components/Sidebar";
import { ExternalIcon, SidebarIcon } from "./components/Icons";
import {
  formatCount,
  formatParams,
  isMacSmall,
  isNewModel,
  isOllamaModel,
  matchInstalled,
  modelPickerLabel,
  type CatalogModel,
  type Installed,
} from "./modelMeta";
import type {
  AgentStep,
  ChatStats,
  Conversation,
  EngineState,
  HfModelInfo,
  Msg,
  PullProgress,
  RamProfileInfo,
  Tab,
  TelemetryPoint,
} from "./types";

type ThemePref = "light" | "dark" | "system";

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    if (v && allowed.includes(v)) return v;
  } catch {
    /* private mode / file:// */
  }
  return fallback;
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

const TABS = ["chat", "library", "agent", "performance", "settings"] as const;

function systemDark() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function App() {
  const [tab, setTab] = useState<Tab>(() => {
    // Deep link: #chat / #library / #agent / #performance / #settings
    const h = typeof window !== "undefined" ? window.location.hash.replace(/^#/, "") : "";
    if ((TABS as readonly string[]).includes(h)) return h as Tab;
    return readStored("wh.tab", TABS, "chat");
  });
  const [themePref, setThemePref] = useState<ThemePref>(() =>
    readStored("wh.theme", ["light", "dark", "system"] as const, "system")
  );
  const [sysDark, setSysDark] = useState<boolean>(systemDark);
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 860);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [installed, setInstalled] = useState<Installed[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeConv, setActiveConv] = useState<string>("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [engineOk, setEngineOk] = useState<boolean | null>(null);
  const [enginePresent, setEnginePresent] = useState<boolean | null>(null);
  const [family, setFamily] = useState<string>(() =>
    readStored("wh.family", ["mac", "new", "all", "qwen", "gemma", "granite", "minicpm", "phi", "deepseek", "llama", "mistral", "glm", "kimi", "minimax", "windhover", "ollama"] as const, "mac")
  );
  const [query, setQuery] = useState("");
  const [activeModel, setActiveModel] = useState<string>(() => {
    try {
      return localStorage.getItem("wh.model") || "";
    } catch {
      return "";
    }
  });
  const [stats, setStats] = useState<{
    rss_mb?: number;
    engine?: string;
    engine_present?: boolean;
    installed?: number;
    last?: ChatStats;
    chat_preview?: string;
    engine_warm?: boolean;
    ram_profile?: RamProfileInfo;
  } | null>(null);
  const [lastStats, setLastStats] = useState<ChatStats | null>(null);
  const [history, setHistory] = useState<TelemetryPoint[]>([]);
  const [confirmUninstall, setConfirmUninstall] = useState<{ id: string; name: string; path?: string } | null>(null);
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
  const bootFailRef = useRef(0);

  const theme: "light" | "dark" = themePref === "system" ? (sysDark ? "dark" : "light") : themePref;

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);
  useEffect(() => writeStored("wh.tab", tab), [tab]);
  useEffect(() => writeStored("wh.family", family), [family]);
  useEffect(() => {
    if (activeModel) writeStored("wh.model", activeModel);
  }, [activeModel]);
  useEffect(() => {
    writeStored("wh.theme", themePref);
    const root = document.documentElement;
    if (themePref === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", themePref);
  }, [themePref]);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const on = () => setSysDark(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  const chatCapable = useMemo(() => installed.filter((m) => m.chat_ok && !m.impostor), [installed]);
  const ollamaInstalled = useMemo(() => installed.filter((m) => isOllamaModel(m) && m.chat_ok), [installed]);

  async function refresh() {
    try {
      const health = await fetch(apiUrl("/health")).then((r) => r.json());
      bootFailRef.current = 0;
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
      setLoaded(true);
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
      bootFailRef.current += 1;
      const starting = bootFailRef.current < 12;
      try {
        const c = await fetch("./catalog.json").then((r) => r.json());
        setCatalog(c.models || []);
      } catch {
        /* offline */
      }
      setStatus(
        starting
          ? "Starting Windhover…"
          : "Can't reach the Windhover server. Open the desktop app, or run ./windhover app"
      );
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
        setUpdateMsg(String(j.message || "Installing update — Windhover will restart on the new version automatically."));
        // Keep busy: the process is about to be replaced / killed by the installer.
        return;
      }
      setUpdateMsg(String(j?.error || "Update failed."));
      if (updateInfo?.html_url) window.open(updateInfo.html_url, "_blank", "noopener,noreferrer");
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

  // ---- conversations: the active thread mirrors into localStorage history
  useEffect(() => {
    if (!activeConv || !messages.length) return;
    setConversations((prev) => {
      const existing = prev.find((c) => c.id === activeConv);
      if (existing && existing.messages === messages) return prev; // just opened, unchanged
      const next = existing
        ? prev.map((c) =>
            c.id === activeConv
              ? { ...c, messages, title: titleFrom(messages), model: activeModel || c.model, updated: Date.now() }
              : c
          )
        : [{ ...newConversation(activeModel), id: activeConv, messages, title: titleFrom(messages) }, ...prev];
      saveConversations(next);
      return next;
    });
  }, [messages, activeConv]); // eslint-disable-line react-hooks/exhaustive-deps

  const startNewChat = useCallback(() => {
    chatAbortRef.current?.abort();
    setMessages([]);
    setInput("");
    setActiveConv("");
    setTab("chat");
  }, []);

  function selectConversation(id: string) {
    const c = conversations.find((x) => x.id === id);
    if (!c) return;
    chatAbortRef.current?.abort();
    setActiveConv(id);
    setMessages(c.messages);
    if (c.model && matchInstalled(chatCapable, c.model)) setActiveModel(c.model);
    setTab("chat");
  }

  function deleteConversation(id: string) {
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== id);
      saveConversations(next);
      return next;
    });
    if (id === activeConv) {
      setActiveConv("");
      setMessages([]);
    }
  }

  // ---- keyboard shortcuts: ⌘1-5 tabs, ⌘N new chat, ⌘B sidebar
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= TABS.length) {
        e.preventDefault();
        setTab(TABS[n - 1]);
      } else if (e.key.toLowerCase() === "n" && !e.shiftKey) {
        e.preventDefault();
        startNewChat();
      } else if (e.key.toLowerCase() === "b") {
        e.preventDefault();
        setSidebarOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [startNewChat]);

  // ---- telemetry history for the Performance view
  const lastStampRef = useRef<string>("");
  function recordTelemetry(st?: ChatStats, model?: string) {
    if (!st) return;
    const wh = st.windhover;
    const stamp = JSON.stringify([wh?.decode_tok_s, wh?.prefill_s, wh?.prompt_tokens, st.latency_ms]);
    if (stamp === lastStampRef.current) return;
    lastStampRef.current = stamp;
    setHistory((h) =>
      [
        ...h,
        {
          t: Date.now(),
          model: model || st.selected_model || "",
          decode: wh?.decode_tok_s ?? st.tokens_per_sec,
          prefill: wh?.prefill_tok_s,
          prompt: wh?.prompt_tokens,
          cached: wh?.cached_tokens,
          prefillS: wh?.prefill_s,
          latencyMs: st.latency_ms,
          rssGb: wh?.rss_gb,
        },
      ].slice(-60)
    );
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (family === "ollama") return [];
    return catalog.filter((m) => {
      if (family === "mac") {
        if (!isMacSmall(m) || m.legacy) return false;
      } else if (family === "new") {
        if (!isNewModel(m)) return false;
      } else if (family !== "all" && (m.family || "other") !== family) {
        return false;
      }
      if (!q) return true;
      const hay = `${m.name} ${m.id} ${m.description} ${(m.tags || []).join(" ")}`.toLowerCase();
      return hay.includes(q);
    });
  }, [catalog, family, query]);

  const filteredOllama = useMemo(() => {
    if (family !== "all" && family !== "ollama" && family !== "mac") return [];
    const q = query.trim().toLowerCase();
    return ollamaInstalled.filter((m) => {
      if (!q) return true;
      const hay = `${m.name || ""} ${m.id} ${m.description || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [ollamaInstalled, family, query]);

  const activeMeta = useMemo(() => matchInstalled(chatCapable, activeModel) || chatCapable[0], [chatCapable, activeModel]);

  async function pull(m: CatalogModel, weights = false) {
    const autoWeights = isMacSmall(m);
    let useWeights = weights || autoWeights;
    if (m.status === "download" && !useWeights) {
      const ok = confirm(
        `${m.name} is ~${m.size_gb} GB from Hugging Face.\n\n` +
          `Windhover will NOT install a fake stub. Continue with a real download?`
      );
      if (!ok) return;
      useWeights = true;
    }
    setBusy(m.id);
    setProgress({ id: m.id, pct: 1, message: `Starting ${m.name}…` });
    setStatus(useWeights || isMacSmall(m) ? `Downloading ${m.name} (~${m.size_gb} GB)…` : `Installing ${m.name}…`);
    try {
      const r = await fetch(apiUrl("/api/pull"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: m.id, weights: useWeights, async: true }),
      });
      const j = await r.json();
      if (j.async && j.job_id) {
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
          setProgress({ id: m.id, pct, message, bytes: typeof st.bytes === "number" ? st.bytes : undefined });
          setStatus(message);
          if (st.status === "done") {
            setStatus(`Installed ${m.name}`);
            setProgress({ id: m.id, pct: 100, message: "Installed" });
            if (isMacSmall(m) || m.chat === "engine") setActiveModel(m.id);
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
        if (isMacSmall(m) || m.chat === "engine") setActiveModel(m.id);
      } else {
        setStatus(j.error || `Failed: ${m.id}`);
        setProgress(null);
      }
      await refresh();
      setTimeout(() => setProgress((p) => (p?.id === m.id && p.pct >= 100 ? null : p)), 1200);
    } catch (e) {
      setStatus(String(e));
      setProgress(null);
    } finally {
      setBusy(null);
    }
  }

  function uninstall(id: string, name?: string, path?: string) {
    // In-app confirm — window.confirm is unreliable in the Tauri webview.
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
          setActiveConv("");
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

  function openChat(id: string) {
    const inst = matchInstalled(installed, id);
    if (!inst?.chat_ok) {
      setStatus("That pack can't chat — install a Hugging Face model, or start Ollama.");
      return;
    }
    setActiveModel(id);
    startNewChat();
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
      setProgress({ id: modelLabel, pct, message: String(st.message || `Preparing ${modelLabel}…`) });
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
      if (!j?.ok) setModelInfoErr(String(j?.error || "Could not load Hugging Face info."));
      setModelInfo(j);
    } catch (e) {
      setModelInfoErr(e instanceof Error ? e.message : String(e));
    } finally {
      setModelInfoBusy(false);
    }
  }

  async function setRamProfile(name: string) {
    try {
      const j = await fetch(apiUrl("/api/ram-profile"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: name }),
      }).then((r) => r.json());
      if (j?.ok) setStats((prev) => ({ ...(prev || {}), ram_profile: j }));
    } catch {
      /* keep last known cap */
    }
  }

  async function sendText(text: string, base: Msg[]) {
    if (!text || sending) return;
    const modelId = activeModel || chatCapable[0]?.id;
    if (!modelId) {
      setStatus("Install a model first (or start Ollama)");
      setTab("library");
      return;
    }
    if (!activeConv) setActiveConv(newConversation(modelId).id);
    chatAbortRef.current?.abort();
    const ac = new AbortController();
    chatAbortRef.current = ac;
    const hardTimer = window.setTimeout(() => ac.abort(), 600_000);

    setSending(true);
    setInput("");
    const next = [...base, { role: "user" as const, content: text }];
    setMessages(next);
    let assistant = "";
    let gotToken = false;

    const paint = (content: string, st?: ChatStats) => {
      setMessages([...next, { role: "assistant", content, stats: st }]);
    };

    const useStream = !isOllamaModel(matchInstalled(chatCapable, modelId) || { id: modelId });

    async function postChat(stream: boolean) {
      return fetch(apiUrl("/v1/chat/completions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ac.signal,
        body: JSON.stringify({
          model: modelId,
          messages: next.map(({ role, content }) => ({ role, content })),
          max_tokens: 512,
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
        const st = (j?.stats || j?.windhover || {}) as ChatStats;
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
          const errMsg = String(j?.error || `Chat failed (${r.status})`) + (j?.detail ? `\n\n${j.detail}` : "");
          setLastStats(st);
          setStatus(j?.code === "engine_inactive" || r.status === 503 ? "Windhover engine is not active" : String(j?.error || "Chat failed"));
          paint(errMsg, { ...st, engine_active: false, backend: st.backend || "error" });
          void refresh();
          return;
        }
        const content = j?.choices?.[0]?.message?.content || j?.error || "No response.";
        setLastStats(st);
        recordTelemetry(st, modelId);
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
            const errMsg = String(obj.error || "Engine inactive") + (obj.detail ? `\n\n${obj.detail}` : "");
            paint(errMsg, { ...(obj.stats || {}), engine_active: false, backend: "error" });
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
        if (finalStats) {
          setLastStats(finalStats);
          recordTelemetry(finalStats, modelId);
        }
      }
      void refresh();
    } catch (e) {
      if (ac.signal.aborted) {
        paint(assistant.trim() ? `${assistant}\n\n_(stopped)_` : "Stopped.");
        setStatus("Chat cancelled");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        const friendly = /failed to fetch|networkerror|load failed/i.test(msg)
          ? "Couldn't reach the Windhover server (Failed to fetch). Is the app running on port 8000? Try again."
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

  function send() {
    void sendText(input.trim(), messages);
  }

  function retryLast() {
    if (sending) return;
    let lastUser = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUser = i;
        break;
      }
    }
    if (lastUser < 0) return;
    void sendText(messages[lastUser].content, messages.slice(0, lastUser));
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
      await browseWorkspace();
      return;
    }
    setAgentStatus("Setting workspace…");
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
        return;
      }
      setWorkspace(String(j.root));
      setAgentStatus(`Using ${j.root}`);
      await loadWorkspaceTree();
    } catch (e) {
      setWorkspaceReady(false);
      setAgentStatus(String(e));
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
        return;
      }
      setWorkspace(String(j.root));
      setAgentStatus(`Using ${j.root}`);
      await loadWorkspaceTree();
    } catch (e) {
      setWorkspaceReady(false);
      setAgentStatus(String(e));
    } finally {
      setPickingFolder(false);
    }
  }

  async function runAgent() {
    const text = agentInput.trim();
    if (!text || agentBusy) return;
    const modelId = activeModel || chatCapable[0]?.id;
    if (!modelId) {
      setStatus("Install a chat-capable model first");
      setTab("library");
      return;
    }
    if (!workspace.trim()) {
      setAgentStatus("Choose a workspace folder first");
      return;
    }
    setAgentBusy(true);
    setAgentSteps([]);
    setAgentSummary("");
    setAgentPrompt(text);
    setAgentInput("");
    setAgentStatus("Starting…");
    setAgentPhase("start");
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
        setAgentSummary(String(j.error || "failed"));
        setAgentStatus(String(j.error || "failed"));
        return;
      }
      if (!j.async || !j.job_id) {
        setAgentSteps((j.steps || []) as AgentStep[]);
        setAgentSummary(String(j.summary || ""));
        setAgentStatus("Done");
        setAgentPhase("done");
        return;
      }
      const jobId = String(j.job_id);
      for (;;) {
        await new Promise((res) => setTimeout(res, 400));
        const st = await fetch(apiUrl(`/api/jobs?id=${encodeURIComponent(jobId)}`)).then((x) => x.json());
        if (Array.isArray(st.steps)) setAgentSteps(st.steps as AgentStep[]);
        if (st.message) setAgentStatus(String(st.message));
        if (st.phase) setAgentPhase(String(st.phase));
        if (st.status === "done") {
          const result = st.result || {};
          setAgentSteps((result.steps || st.steps || []) as AgentStep[]);
          setAgentSummary(String(result.summary || st.summary || ""));
          setAgentStatus("Done");
          setAgentPhase("done");
          break;
        }
        if (st.status === "error") {
          setAgentSummary(String(st.error || st.message || "Agent failed"));
          setAgentStatus(String(st.error || st.message || "failed"));
          setAgentPhase("error");
          break;
        }
      }
      const treeR = await fetch(apiUrl("/api/workspace/tree?path=.")).then((x) => x.json());
      if (treeR.ok) setTree(treeR.entries || []);
    } catch (e) {
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
          ? lastStats.engine_error || "Last reply did not use windhover-engine"
          : engineOk
            ? "Windhover API online · windhover-engine ready"
            : "Checking…";
  const engineState: EngineState =
    engineOk === false ? "off" : enginePresent === false || lastStats?.engine_active === false ? "warn" : engineOk ? "on" : "";
  const engineLabel =
    engineOk === false
      ? "Offline"
      : enginePresent === false
        ? "No engine"
        : lastStats?.engine_warm || stats?.engine_warm
          ? "Engine warm"
          : engineOk
            ? "Engine ready"
            : "Connecting";
  const engineInactiveBanner =
    engineOk === false
      ? "Windhover API offline — open the desktop app, or run ./windhover app"
      : enginePresent === false
        ? "windhover-engine binary is missing. Run ./windhover build, then restart."
        : lastStats?.engine_active === false
          ? lastStats.engine_error || "The engine wasn't used for the last reply (fallback or failure)."
          : null;

  const modelItems: PickerItem[] = chatCapable.map((m) => ({
    value: m.id,
    label: modelPickerLabel(m).replace(/^Ollama · /, ""),
    hint: isOllamaModel(m) ? "Ollama" : m.size_bytes ? `${(m.size_bytes / 1e9).toFixed(1)} GB` : undefined,
    group: isOllamaModel(m) ? "Ollama" : "Windhover engine",
  }));

  const composerLeft = (
    <>
      <Picker
        label="Model"
        value={activeModel}
        items={modelItems}
        placeholder="No model installed"
        disabled={sending || agentBusy}
        onChange={(id) => {
          setActiveModel(id);
        }}
      />
      <Segmented
        label="Memory profile"
        value={stats?.ram_profile?.name || "balanced"}
        disabled={sending || agentBusy}
        options={[
          { value: "fast", label: "Fast", title: "Pin the full FFN — fastest, most RAM" },
          { value: "balanced", label: "Balanced", title: "~55% RAM cap with SSD paging" },
          { value: "low", label: "Low", title: "~40% RAM cap, no mlock" },
        ]}
        onChange={(v) => void setRamProfile(v)}
      />
    </>
  );

  const titles: Record<Tab, string> = {
    chat: activeConv ? conversations.find((c) => c.id === activeConv)?.title || "Chat" : "New chat",
    library: "Models",
    agent: "Agent",
    performance: "Performance",
    settings: "Settings",
  };
  const modelName = activeMeta ? modelPickerLabel(activeMeta) : "your model";
  const physGb = stats?.ram_profile?.physical_ram_gb ?? null;

  return (
    <div className={`app${sidebarOpen ? "" : " sb-collapsed"}`}>
      {confirmUninstall ? (
        <Modal
          title="Uninstall model?"
          onClose={() => setConfirmUninstall(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setConfirmUninstall(null)}>
                Cancel
              </button>
              <button type="button" className="btn danger" onClick={() => void confirmUninstallNow()}>
                Uninstall
              </button>
            </>
          }
        >
          <p>
            Remove <strong>{confirmUninstall.name}</strong> from this computer? This deletes its files from the Windhover
            models folder (<code>~/.windhover/models</code>).
          </p>
        </Modal>
      ) : null}

      {modelInfoOpen ? (
        <Modal
          wide
          title={modelInfoOpen.name}
          subtitle={<span className="mono">{modelInfoOpen.hf_repo || modelInfoOpen.id}</span>}
          onClose={() => setModelInfoOpen(null)}
          actions={
            <>
              <button type="button" className="btn ghost" onClick={() => setModelInfoOpen(null)}>
                Close
              </button>
              <a
                className="btn primary"
                href={modelInfo?.html_url || `https://huggingface.co/${modelInfoOpen.hf_repo || modelInfoOpen.id}`}
                target="_blank"
                rel="noreferrer"
              >
                Hugging Face <ExternalIcon size={14} />
              </a>
            </>
          }
        >
          {modelInfoBusy ? <p className="muted">Loading from Hugging Face…</p> : null}
          {modelInfoErr ? <p className="text-bad">{modelInfoErr}</p> : null}
          {modelInfo?.ok ? (
            <>
              <div className="info-grid">
                <div>
                  <span>Downloads</span>
                  <strong>{formatCount(modelInfo.downloads)}</strong>
                </div>
                <div>
                  <span>Likes</span>
                  <strong>{formatCount(modelInfo.likes)}</strong>
                </div>
                <div>
                  <span>Parameters</span>
                  <strong>{formatParams(modelInfo.parameters)}</strong>
                </div>
                <div>
                  <span>License</span>
                  <strong>{modelInfo.license || modelInfoOpen.license || "—"}</strong>
                </div>
                <div>
                  <span>Pipeline</span>
                  <strong>{modelInfo.pipeline_tag || "—"}</strong>
                </div>
                <div>
                  <span>Library</span>
                  <strong>{modelInfo.library_name || "—"}</strong>
                </div>
              </div>
              <p className="info-summary">{modelInfo.card_summary || modelInfoOpen.description}</p>
              {modelInfo.benchmarks && modelInfo.benchmarks.length > 0 ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Dataset</th>
                        <th>Metric</th>
                        <th className="num">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {modelInfo.benchmarks.slice(0, 24).map((b, i) => (
                        <tr key={i}>
                          <td>{b.dataset || b.task || "—"}</td>
                          <td>{b.metric || "—"}</td>
                          <td className="num mono">
                            {typeof b.value === "number"
                              ? Number.isInteger(b.value)
                                ? b.value
                                : b.value.toFixed(3)
                              : (b.value ?? "—")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">No published model-index benchmarks on this card.</p>
              )}
              {modelInfo.tags?.length ? (
                <div className="tag-row">
                  {modelInfo.tags.slice(0, 16).map((t) => (
                    <span className="tag" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              ) : null}
            </>
          ) : !modelInfoBusy && !modelInfoErr ? (
            <p className="muted">{modelInfoOpen.description}</p>
          ) : null}
        </Modal>
      ) : null}

      <Sidebar
        tab={tab}
        onTab={setTab}
        conversations={conversations}
        activeConv={activeConv}
        onSelectConv={selectConversation}
        onDeleteConv={deleteConversation}
        onNewChat={startNewChat}
        engineState={engineState}
        engineTitle={engineTitle}
        engineLabel={engineLabel}
        appVersion={appVersion || updateInfo?.current || ""}
        installedCount={chatCapable.length}
        theme={theme}
        onToggleTheme={() => setThemePref(theme === "dark" ? "light" : "dark")}
        updateLatest={updateInfo?.available ? updateInfo.latest : undefined}
        onUpdate={() => void applyUpdate()}
      />

      <main className="main">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn"
            aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            title="Toggle sidebar (⌘B)"
            onClick={() => setSidebarOpen((o) => !o)}
          >
            <SidebarIcon />
          </button>
          <h1 className="topbar-title">{titles[tab]}</h1>
          <div className="topbar-end">
            {progress && tab !== "library" ? (
              <button type="button" className="chip progress-chip" onClick={() => setTab("library")}>
                {Math.round(progress.pct)}% · {progress.message}
              </button>
            ) : null}
            {lastStats?.windhover?.decode_tok_s ? (
              <span className="chip" title="Last reply decode speed">
                {Number(lastStats.windhover.decode_tok_s).toFixed(1)} tok/s
              </span>
            ) : null}
          </div>
        </header>
        {updateInfo?.available && updateMsg && updateBusy ? <div className="banner info">{updateMsg}</div> : null}

        {tab === "chat" ? (
          <ChatView
            messages={messages}
            sending={sending}
            input={input}
            onInput={setInput}
            onSend={send}
            onStop={stopChat}
            onRetry={retryLast}
            onStarter={(t) => void sendText(t, messages)}
            chatCapable={chatCapable.length > 0}
            loading={!loaded}
            composerLeft={composerLeft}
            threadRef={threadRef}
            modelName={modelName}
            onOpenLibrary={() => setTab("library")}
            banner={messages.length || sending ? engineInactiveBanner : status && !chatCapable.length ? status : null}
          />
        ) : null}

        {tab === "library" ? (
          <LibraryView
            status={status}
            progress={progress}
            family={family}
            onFamilyChange={setFamily}
            query={query}
            onQueryChange={setQuery}
            catalog={catalog}
            filtered={filtered}
            filteredOllama={filteredOllama}
            installed={installed}
            busy={busy}
            physGb={physGb}
            onOpenInfo={(m) => void openModelInfo(m)}
            onPull={(m, weights) => void pull(m, weights)}
            onUninstall={uninstall}
            onOpenChat={openChat}
            onUseInAgent={(id) => {
              setActiveModel(id);
              setTab("agent");
            }}
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
            composerLeft={composerLeft}
            workspace={workspace}
            onWorkspaceChange={(v) => {
              setWorkspace(v);
              setWorkspaceReady(false);
            }}
            workspaceReady={workspaceReady}
            pickingFolder={pickingFolder}
            onBrowseWorkspace={() => void browseWorkspace()}
            onApplyWorkspace={() => void applyWorkspace()}
            tree={tree}
            agentPhase={agentPhase}
            agentStatus={agentStatus}
            agentSummary={agentSummary}
            onOpenLibrary={() => setTab("library")}
          />
        ) : null}

        {tab === "performance" ? (
          <PerformanceView
            lastStats={lastStats}
            history={history}
            engineState={engineState}
            ramProfile={stats?.ram_profile}
            rssMb={Number(stats?.rss_mb ?? lastStats?.rss_mb ?? 0)}
            onClear={() => setHistory([])}
          />
        ) : null}

        {tab === "settings" ? (
          <SettingsView
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
            ramProfile={stats?.ram_profile}
            onRamProfile={(v) => void setRamProfile(v)}
            theme={themePref}
            onTheme={setThemePref}
            busy={sending || agentBusy}
          />
        ) : null}
      </main>
    </div>
  );
}
