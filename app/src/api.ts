/** API base: same-origin when served by `kestrel app`; absolute when inside Tauri asset://. */
function detectBase(): string {
  const env = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "");
  if (env) return env;
  if (typeof window === "undefined") return "";
  const { protocol, hostname, port } = window.location;
  // Tauri custom protocol / asset host — UI is not same-origin with the engine API.
  if (protocol === "tauri:" || protocol === "asset:" || hostname === "tauri.localhost" || hostname === "asset.localhost") {
    return "http://127.0.0.1:8000";
  }
  // Embedded dist opened on a random port, or file — talk to the local server.
  if ((hostname === "127.0.0.1" || hostname === "localhost") && port && port !== "8000" && port !== "5173") {
    return "http://127.0.0.1:8000";
  }
  return "";
}

export const API_BASE = detectBase();

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${p}`;
}
