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
  };
};

export type CodeEvent =
  | { id: string; type: "user"; text: string }
  | { id: string; type: "assistant"; text: string; streaming?: boolean; final?: boolean; stats?: CodeStats }
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
  start: (workspace: string, model: string, autoRun: boolean) =>
    post<CodeSnapshot>("/api/code/session", { workspace, model, auto_run: autoRun }),
  get: async (id: string) =>
    (await fetch(apiUrl(`/api/code/session?id=${encodeURIComponent(id)}`))).json() as Promise<CodeSnapshot>,
  send: (id: string, text: string, model: string, autoRun: boolean) =>
    post<{ ok: boolean; error?: string }>("/api/code/message", { session_id: id, text, model, auto_run: autoRun }),
  approve: (id: string, eventId: string, approve: boolean) =>
    post<{ ok: boolean }>("/api/code/approve", { session_id: id, event_id: eventId, approve }),
  stop: (id: string) => post<{ ok: boolean }>("/api/code/stop", { session_id: id }),
  undo: (id: string, changeId: string) =>
    post<{ ok: boolean; error?: string; path?: string }>("/api/code/undo", { session_id: id, change_id: changeId }),
  settings: (id: string, autoRun: boolean) =>
    post<CodeSnapshot>("/api/code/settings", { session_id: id, auto_run: autoRun }),
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
