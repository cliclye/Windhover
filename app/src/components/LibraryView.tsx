import type { CatalogModel, Installed } from "../modelMeta";
import { isMacSmall, matchInstalled, statusBadge } from "../modelMeta";
import type { PullProgress } from "../types";

export function LibraryView({
  status,
  progress,
  family,
  filtered,
  filteredOllama,
  installed,
  busy,
  chatReady,
  onInstallLaptop,
  onOpenChatTab,
  onOpenInfo,
  onPull,
  onUninstall,
  onOpenChat,
  onUseInAgent,
}: {
  status: string;
  progress: PullProgress | null;
  family: string;
  filtered: CatalogModel[];
  filteredOllama: Installed[];
  installed: Installed[];
  busy: string | null;
  chatReady: boolean;
  onInstallLaptop: () => void;
  onOpenChatTab: () => void;
  onOpenInfo: (m: CatalogModel) => void;
  onPull: (m: CatalogModel, weights?: boolean) => void;
  onUninstall: (id: string, name?: string, path?: string) => void;
  onOpenChat: (id: string) => void;
  onUseInAgent: (id: string) => void;
}) {
  return (
    <div className="library-scroll">
      <header className="page-head">
        <h1>Library</h1>
        <p>{status || "Install a 16GB laptop pack first. Huge MoEs need a lot of disk."}</p>
        <div className="page-actions">
          <button type="button" className="btn primary" onClick={onInstallLaptop} disabled={!!progress}>
            Install a 16GB laptop model
          </button>
          <button type="button" className="btn ghost" onClick={onOpenChatTab} disabled={!chatReady}>
            Open chat
          </button>
        </div>
      </header>

      {progress ? (
        <div className="progress global-progress" aria-live="polite">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${Math.max(2, Math.min(100, progress.pct))}%` }} />
          </div>
          <div className="progress-meta">
            <span>{Math.round(progress.pct)}%</span>
            <span>{progress.message}</span>
          </div>
        </div>
      ) : null}

      {filteredOllama.length ? (
        <div className="ollama-block">
          <div className="ollama-head">
            <h2 className="ollama-title">Ollama</h2>
            <p className="ollama-note">Already on this machine — no re-download.</p>
          </div>
          <ul className="model-list">
            {filteredOllama.map((m) => (
              <li key={m.id} className="model-row status-ollama">
                <div className="model-main">
                  <div className="model-title">
                    <h2>{(m.name || m.id).replace(/^ollama\//, "")}</h2>
                    <span className="badge ollama">Ollama</span>
                  </div>
                  <p>{m.description || "Preinstalled via Ollama"}</p>
                  <div className="meta">
                    {m.size_bytes ? <span>{(m.size_bytes / 1e9).toFixed(1)} GB</span> : null}
                    <span>chat ready</span>
                  </div>
                </div>
                <div className="model-actions">
                  <button type="button" className="btn primary" onClick={() => onOpenChat(m.id)}>
                    Chat
                  </button>
                  <button type="button" className="btn ghost" onClick={() => onUseInAgent(m.id)}>
                    Agent
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : family === "ollama" ? (
        <p className="status muted">
          No Ollama models detected. Start Ollama and pull a model, then refresh.
        </p>
      ) : null}

      {family !== "ollama" ? (
        <ul className="model-list">
          {filtered.map((m) => {
            const inst = matchInstalled(installed, m.id);
            const got = !!inst;
            const badge = statusBadge(m);
            const impostor = !!inst?.impostor && !inst?.incomplete;
            const incomplete = !!inst?.incomplete;
            const rowProgress = progress?.id === m.id ? progress : null;
            const isBusy = busy === m.id;
            const downloading = !!rowProgress || (isBusy && !!progress && progress.id === m.id);
            return (
              <li key={m.id} className={`model-row status-${badge.cls}${isBusy ? " is-busy" : ""}`}>
                <div className="model-main">
                  <div className="model-title">
                    <h2>{m.name}</h2>
                    <span className={`badge ${badge.cls}`}>{badge.label}</span>
                    {impostor ? <span className="badge bad">Fake stub</span> : null}
                    {incomplete && !downloading ? <span className="badge bad">Incomplete</span> : null}
                    {got && inst?.needs_prepare && !downloading && !incomplete ? (
                      <span className="badge download">Needs prepare</span>
                    ) : null}
                  </div>
                  <p>{m.description}</p>
                  <div className="meta">
                    <span>~{m.size_gb} GB</span>
                    {m.ram_gb ? <span>~{m.ram_gb}+ GB RAM</span> : null}
                    {m.license ? <span>{m.license}</span> : null}
                  </div>
                  {rowProgress ? (
                    <div className="progress" aria-live="polite">
                      <div className="progress-track">
                        <div
                          className="progress-fill"
                          style={{ width: `${Math.max(2, Math.min(100, rowProgress.pct))}%` }}
                        />
                      </div>
                      <div className="progress-meta">
                        <span>{Math.round(rowProgress.pct)}%</span>
                        <span>{rowProgress.message}</span>
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="model-actions">
                  <button type="button" className="btn ghost" onClick={() => onOpenInfo(m)}>
                    Info
                  </button>
                  {downloading ? (
                    <button type="button" className="btn primary" disabled>
                      {`${Math.round(rowProgress?.pct || 0)}%`}
                    </button>
                  ) : impostor ? (
                    <button
                      type="button"
                      className="btn ghost danger"
                      disabled={isBusy}
                      onClick={() => onUninstall(m.id, m.name, inst?.path ?? undefined)}
                    >
                      {isBusy ? "Removing…" : "Remove"}
                    </button>
                  ) : incomplete || !got ? (
                    <button
                      type="button"
                      className="btn primary"
                      disabled={isBusy || !!progress || m.status === "soon" || m.chat === "blocked"}
                      onClick={() => onPull(m, true)}
                    >
                      {m.status === "soon" || m.chat === "blocked"
                        ? "Unsupported"
                        : incomplete
                          ? "Reinstall"
                          : isMacSmall(m)
                            ? "Install"
                            : m.status === "download"
                              ? "Download"
                              : "Install"}
                    </button>
                  ) : (
                    <>
                      {inst?.chat_ok ? (
                        <button type="button" className="btn primary" onClick={() => onOpenChat(m.id)}>
                          Chat
                        </button>
                      ) : (
                        <button type="button" className="btn ghost" disabled>
                          No chat
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn ghost danger"
                        disabled={isBusy}
                        onClick={() => onUninstall(m.id, m.name, inst?.path ?? undefined)}
                      >
                        {isBusy ? "Removing…" : "Uninstall"}
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
