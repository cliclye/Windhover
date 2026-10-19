import { apiUrl } from "./api";

export type CodeToolEvent = {
  id: string;
  type: "tool";
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error" | "approval" | "denied" | "skipped";
  summary?: string;
  change_id?: string;
  undone?: boolean;
  result?: {
    diff?: string;
    output?: string;
    exit_code?: number;
    matches?: string[];
    entries?: string[];
    path?: string;
    error?: string;
    added?: number;
    removed?: number;
    lines?: number;
    background?: boolean;
    urls?: string[];
    pid?: number;
  };
};

export type CodeMode = "ask" | "accept_edits" | "plan" | "bypass";
export type CodeEffort = "low" | "medium" | "high" | "max";

export const MODES: Array<{ id: CodeMode; label: string; hint: string }> = [
  { id: "ask", label: "Ask before edits", hint: "Approve every file change and command" },
  { id: "accept_edits", label: "Accept edits", hint: "Edits apply right away; commands still ask" },
  { id: "plan", label: "Plan mode", hint: "Read-only: the agent explores and proposes a plan" },
  { id: "bypass", label: "Bypass permissions", hint: "Edits and commands run without asking" },
];

export const EFFORTS: Array<{ id: CodeEffort; label: string; hint: string }> = [
  { id: "low", label: "Low", hint: "Short replies, up to 10 steps — fastest" },
  { id: "medium", label: "Medium", hint: "Up to 20 steps" },
  { id: "high", label: "High", hint: "Thinks before acting, up to 30 steps" },
  { id: "max", label: "Max", hint: "Longest thinking, up to 50 steps — slowest" },
];

export type CodeEvent =
  | { id: string; type: "user"; text: string; images?: string[] }
  | {
      id: string;
      type: "assistant";
      text: string;
      streaming?: boolean;
      final?: boolean;
      stats?: CodeStats;
      thinking?: string;
      thought_seconds?: number;
      pending?: { name: string; path: string; lines: number } | null;
    }
  | { id: string; type: "notice" | "error"; text: string }
  | CodeToolEvent;

export type CodeStats = {
  decode_tok_s?: number;
  prompt_tokens?: number;
  cached_tokens?: number;
  step_seconds?: number;
  backend?: string;
};

export type CodeSnapshot = {
  ok: boolean;
  error?: string;
  code?: string;
  job_id?: string;
  session_id: string;
  root: string;
  model: string;
  busy: boolean;
  auto_run: boolean;
  mode?: CodeMode;
  effort?: CodeEffort;
  version: number;
  events: CodeEvent[];
  pending_approval: string | null;
  changed_files: string[];
  stats: CodeStats;
};

export type TreeEntry = { name: string; path: string; type: string; size?: number | null };

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await r.json()) as T;
}

export const codeApi = {
  start: (workspace: string, model: string, mode: CodeMode, effort: CodeEffort) =>
    post<CodeSnapshot>("/api/code/session", { workspace, model, mode, effort }),
  get: async (id: string) =>
    (await fetch(apiUrl(`/api/code/session?id=${encodeURIComponent(id)}`))).json() as Promise<CodeSnapshot>,
  send: (
    id: string,
    text: string,
    model: string,
    mode: CodeMode,
    effort: CodeEffort,
    images: string[] = [],
    thumbs: string[] = []
  ) =>
    post<{ ok: boolean; error?: string }>("/api/code/message", {
      session_id: id,
      text,
      model,
      mode,
      effort,
      images,
      thumbs,
    }),
  approve: (id: string, eventId: string, approve: boolean) =>
    post<{ ok: boolean }>("/api/code/approve", { session_id: id, event_id: eventId, approve }),
  stop: (id: string) => post<{ ok: boolean }>("/api/code/stop", { session_id: id }),
  undo: (id: string, changeId: string) =>
    post<{ ok: boolean; error?: string; path?: string }>("/api/code/undo", { session_id: id, change_id: changeId }),
  settings: (id: string, opts: { mode?: CodeMode; effort?: CodeEffort }) =>
    post<CodeSnapshot>("/api/code/settings", { session_id: id, ...opts }),
  setWorkspace: (root: string) => post<{ ok: boolean; root?: string; error?: string }>("/api/workspace", { root }),
  pickWorkspace: () =>
    post<{ ok: boolean; root?: string; error?: string; cancelled?: boolean }>("/api/workspace/pick", {}),
  tree: async (path: string) =>
    (await fetch(apiUrl(`/api/workspace/tree?path=${encodeURIComponent(path)}`))).json() as Promise<{
      ok: boolean;
      entries?: TreeEntry[];
      error?: string;
    }>,
  readFile: async (path: string) =>
    (await fetch(apiUrl(`/api/workspace/file?path=${encodeURIComponent(path)}`))).json() as Promise<{
      ok: boolean;
      content?: string;
      error?: string;
      truncated?: boolean;
    }>,
  writeFile: (path: string, content: string) =>
    post<{ ok: boolean; error?: string }>("/api/workspace/file", { path, content }),
};
