export type CatalogModel = {
  id: string;
  name: string;
  description: string;
  size_gb: number;
  license?: string;
  tags?: string[];
  source?: string;
  family?: string;
  status?: string;
  ram_gb?: number;
  hf_repo?: string;
  preview_repo?: string;
  engine?: string;
  chat?: string;
  tier?: string;
  released?: string;
  recommended?: boolean;
  legacy?: boolean;
  params_b?: number;
  engine_path?: string;
};

export type Installed = {
  id: string;
  path?: string | null;
  name?: string;
  ready?: boolean;
  engine?: string;
  family?: string;
  incomplete?: boolean;
  chat_ok?: boolean;
  chat_mode?: string;
  impostor?: boolean;
  needs_prepare?: boolean;
  engine_ready?: boolean;
  size_bytes?: number;
  weight_bytes?: number;
  has_weights?: boolean;
  source?: string;
  backend?: string;
  description?: string;
};

export const FAMILIES = [
  { id: "mac", label: "Fits a laptop" },
  { id: "new", label: "New in 2026" },
  { id: "all", label: "All" },
  { id: "qwen", label: "Qwen" },
  { id: "gemma", label: "Gemma" },
  { id: "granite", label: "Granite" },
  { id: "minicpm", label: "MiniCPM" },
  { id: "phi", label: "Phi" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "llama", label: "Llama" },
  { id: "mistral", label: "Mistral" },
  { id: "glm", label: "GLM" },
  { id: "kimi", label: "Kimi" },
  { id: "minimax", label: "MiniMax" },
  { id: "windhover", label: "SmolLM" },
  { id: "ollama", label: "Ollama" },
] as const;

export function isNewModel(m: CatalogModel) {
  return (m.tags || []).includes("new") || (m.released || "") >= "2026-01-01";
}

export function releasedLabel(m: CatalogModel) {
  if (!m.released) return "";
  const d = new Date(`${m.released}T00:00:00`);
  if (Number.isNaN(d.getTime())) return m.released;
  return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

export function familyLabel(id?: string) {
  const f = FAMILIES.find((x) => x.id === id);
  return f ? f.label : id ? id.charAt(0).toUpperCase() + id.slice(1) : "Other";
}

export function matchInstalled(list: Installed[], id: string) {
  const key = id.replace("/", "__");
  return list.find(
    (m) => m.id === id || m.id === key || m.id?.endsWith(id.split("/").pop() || "")
  );
}

export function isOllamaModel(m: {
  id?: string;
  source?: string;
  backend?: string;
  chat_mode?: string;
}) {
  return (
    m.source === "ollama" ||
    m.backend === "ollama" ||
    m.chat_mode === "ollama" ||
    String(m.id || "").startsWith("ollama/")
  );
}

export function modelPickerLabel(m: Installed) {
  const name = m.name || m.id;
  return isOllamaModel(m) ? `Ollama · ${name.replace(/^ollama\//, "")}` : name;
}

export function isMacSmall(m: CatalogModel) {
  return m.tier === "mac16" || m.source === "hf_small" || (m.tags || []).includes("mac16");
}

export function statusBadge(m: CatalogModel) {
  if (isMacSmall(m)) return { cls: "mac", label: "Laptop" };
  if (m.status === "ready" && m.chat === "preview") return { cls: "ready", label: "Preview" };
  if (m.status === "ready" && m.chat === "engine-oracle") return { cls: "demo", label: "Engine demo" };
  if (m.status === "download") return { cls: "download", label: "Download" };
  if (m.status === "ready") return { cls: "ready", label: "Ready" };
  return { cls: "download", label: m.status || "Download" };
}

export function formatCount(n?: number) {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatParams(n?: number) {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  return String(n);
}
