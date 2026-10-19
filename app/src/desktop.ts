/**
 * Desktop (Tauri) window chrome.
 *
 * On macOS the window uses an overlay title bar: the traffic lights sit on top of
 * our UI, so the page reserves a 52px title strip for them and implements window
 * dragging + double-click-to-zoom itself (WKWebView ignores -webkit-app-region).
 * Elements marked with `data-drag` are title-bar areas; clicks on interactive
 * children (buttons, inputs, links, …) are left alone.
 */

type TauriInternals = { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };

function internals(): TauriInternals | null {
  const w = window as unknown as { __TAURI_INTERNALS__?: TauriInternals };
  return w.__TAURI_INTERNALS__ && typeof w.__TAURI_INTERNALS__.invoke === "function" ? w.__TAURI_INTERNALS__ : null;
}

function detectShell(): "macos" | "windows" | "" {
  let flag = "";
  try {
    flag = new URLSearchParams(window.location.search).get("desktop") || sessionStorage.getItem("wh.desktop") || "";
    if (flag) sessionStorage.setItem("wh.desktop", flag);
  } catch {
    /* storage blocked */
  }
  if (!flag && !internals()) return "";
  const mac = /Mac/i.test(navigator.platform || navigator.userAgent);
  if (flag === "macos" || (!flag && mac)) return "macos";
  return "windows";
}

export const DESKTOP_SHELL = typeof window === "undefined" ? "" : detectShell();

const INTERACTIVE = "button, a, input, textarea, select, label, [role=button], [contenteditable=true], .no-drag";

function invoke(cmd: string): void {
  const t = internals();
  if (!t) return;
  void t.invoke(`plugin:window|${cmd}`, { label: "main" }).catch(() => undefined);
}

export function installDesktopChrome(): void {
  if (!DESKTOP_SHELL) return;
  document.documentElement.classList.add("desktop", `desktop-${DESKTOP_SHELL}`);
  if (DESKTOP_SHELL !== "macos") return;
  document.addEventListener(
    "mousedown",
    (e) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement | null;
      if (!target || !target.closest("[data-drag]")) return;
      if (target.closest(INTERACTIVE)) return;
      e.preventDefault();
      // Second click of a double-click zooms (fills the screen without entering
      // full screen), like a native title bar; a single press starts a drag.
      invoke(e.detail === 2 ? "internal_toggle_maximize" : "start_dragging");
    },
    true,
  );
}
