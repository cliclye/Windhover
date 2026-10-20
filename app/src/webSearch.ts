import { apiUrl } from "./api";
import { extractSSE } from "./chatText";
import type { Msg, WebSource } from "./types";

export type { WebSource };

/** Per-message choice in the composer. */
export type WebMode = "off" | "search" | "research";
/** Settings permission: never, ask before going online, or go online without asking. */
export type WebAccess = "off" | "ask" | "auto";

export type WebResult = {
  ok: boolean;
  sources?: WebSource[];
  queries?: string[];
  error?: string;
  code?: string;
};

/** Is the open internet reachable? Asks the local server, which can actually try. */
export async function checkOnline(fresh = false): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return false;
  try {
    const j = await fetch(apiUrl(`/api/web/status${fresh ? "?fresh=1" : ""}`)).then((r) => r.json());
    return !!j?.online;
  } catch {
    return false;
  }
}

const RECENT =
  /\b(latest|newest|recent(ly)?|currently|today'?s?|tonight|yesterday|this (week|month|year|season)|right now|as of now|breaking|news|headlines|prices?|stock price|weather|forecast|scores?|standings|election|who (won|is winning))\b/i;

/** Questions a model trained months ago will likely get wrong. */
export function looksTimeSensitive(text: string): boolean {
  const year = new Date().getFullYear();
  return RECENT.test(text) || new RegExp(`\\b(${year - 1}|${year}|${year + 1})\\b`).test(text);
}

/** Search the web for this turn; `onProgress` gets "Searching…", "Reading…" lines. */
export async function runWebSearch({
  messages,
  mode,
  model,
  signal,
  onProgress,
}: {
  messages: Msg[];
  mode: Exclude<WebMode, "off">;
  model: string;
  signal: AbortSignal;
  onProgress: (message: string) => void;
}): Promise<WebResult> {
  const post = (stream: boolean) =>
    fetch(apiUrl("/api/web/search"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        mode,
        model,
        stream,
        messages: messages.map(({ role, content }) => ({ role, content })),
      }),
    });
  let r: Response;
  try {
    r = await post(true);
  } catch (e) {
    if (signal.aborted) throw e;
    r = await post(false); // WebView rejected SSE — same fallback as chat
  }
  if (!(r.headers.get("content-type") || "").includes("text/event-stream") || !r.body) {
    return (await r.json()) as WebResult;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let result: WebResult = { ok: false, error: "web search ended early" };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { data, rest } = extractSSE(buf);
    buf = rest;
    for (const line of data) {
      if (!line || line === "[DONE]") continue;
      try {
        const obj = JSON.parse(line) as WebResult & { stage?: string; message?: string };
        if (obj.stage === "result") result = obj;
        else if (obj.message) onProgress(obj.message);
      } catch {
        /* partial frame */
      }
    }
  }
  return result;
}

/** Turn [1] / [2][3] citations into `[1](url)` links (outside code); MarkdownBody styles them. */
export function linkCitations(text: string, sources?: WebSource[]): string {
  if (!sources?.length) return text;
  const byN = new Map(sources.map((s) => [s.n, s.url]));
  return text
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/)
    .map((part, i) =>
      i % 2
        ? part
        : part.replace(/\[(\d{1,2})\](?![(:\]])/g, (m, d: string) => {
            const url = byN.get(Number(d));
            return url ? `[${d}](${url.replace(/[()\s]/g, encodeURIComponent)})` : m;
          })
    )
    .join("");
}
