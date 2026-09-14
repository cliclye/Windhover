export type HfModelInfo = {
  ok?: boolean;
  id?: string;
  error?: string;
  downloads?: number;
  likes?: number;
  pipeline_tag?: string;
  library_name?: string;
  license?: string;
  created_at?: string;
  last_modified?: string;
  tags?: string[];
  parameters?: number;
  card_summary?: string | null;
  benchmarks?: Array<{
    task?: string;
    dataset?: string;
    metric?: string;
    value?: number | string;
  }>;
  html_url?: string;
};

export type Msg = {
  role: "user" | "assistant";
  content: string;
  stats?: ChatStats;
};

export type WindhoverStats = {
  decode_tok_s?: number;
  prefill_tok_s?: number;
  footprint_gb?: number;
  sparsity_pct?: number;
  bytes_per_tok?: number;
  au_hit_pct?: number;
  forwards?: number;
};

export type RamProfileInfo = {
  name?: string;
  label?: string;
  blurb?: string;
  ram_gb?: number | null;
  physical_ram_gb?: number | null;
  mlock?: number;
};

export type ChatStats = {
  rss_mb?: number;
  latency_ms?: number;
  tokens_per_sec?: number;
  completion_tokens?: number;
  backend?: string;
  selected_model?: string;
  preview_model?: string;
  family?: string;
  windhover?: WindhoverStats;
  engine_active?: boolean;
  engine_warm?: boolean;
  engine_error?: string;
  fallback_from?: string;
  ram_gb?: number | null;
  ram_profile?: string;
  mlock?: number;
};

export type PullProgress = {
  id: string;
  pct: number;
  message: string;
  bytes?: number;
};

export type AgentStep = {
  step: number;
  assistant?: string;
  tool_calls?: Array<Record<string, unknown>>;
  tool_results?: Array<Record<string, unknown>>;
  stats?: ChatStats;
  done?: boolean;
};

export type EngineState = "on" | "off" | "warn" | "";
