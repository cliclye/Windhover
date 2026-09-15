import type { Tab } from "./RailIcon";
import { FAMILIES, isOllamaModel, type Installed } from "../modelMeta";
import type { ChatStats, EngineState } from "../types";
import { PlusIcon } from "./Icons";

export function AppSidebar({
  tab,
  chatCapable,
  activeModel,
  onSelectModel,
  onNewChat,
  engineTitle,
  engineState,
  lastStats,
  rssMb,
  workspace,
  onWorkspaceChange,
  workspaceReady,
  agentBusy,
  pickingFolder,
  onBrowseWorkspace,
  onApplyWorkspace,
  agentStatus,
  tree,
  query,
  onQueryChange,
  family,
  onFamilyChange,
  catalogCount,
  ollamaCount,
  appVersion,
}: {
  tab: Tab;
  chatCapable: Installed[];
  activeModel: string;
  onSelectModel: (id: string) => void;
  onNewChat: () => void;
  engineTitle: string;
  engineState: EngineState;
  lastStats: ChatStats | null;
  rssMb: number;
  workspace: string;
  onWorkspaceChange: (value: string) => void;
  workspaceReady: boolean;
  agentBusy: boolean;
  pickingFolder: boolean;
  onBrowseWorkspace: () => void;
  onApplyWorkspace: () => void;
  agentStatus: string;
  tree: Array<{ name: string; path: string; type: string }>;
  query: string;
  onQueryChange: (value: string) => void;
  family: string;
  onFamilyChange: (id: string) => void;
  catalogCount: number;
  ollamaCount: number;
  appVersion: string;
}) {
  return (
    <aside className="side-panel" aria-label={sidebarLabel(tab)}>
      {tab === "chat" ? (
        <>
          <div className="side-head">
            <strong>Chat</strong>
            <span className={`side-dot ${engineState}`} title={engineTitle} />
          </div>
          <div className="side-block">
            <button type="button" className="side-cta" onClick={onNewChat}>
              <PlusIcon /> New chat
            </button>
          </div>
          <div className="side-group">
            <div className="side-label">Models</div>
            {chatCapable.length ? (
              <ul className="side-models">
                {chatCapable.map((m) => (
                  <li key={m.id}>
                    <button
                      type="button"
                      className={m.id === activeModel ? "active" : ""}
                      onClick={() => onSelectModel(m.id)}
                    >
                      <span>{(m.name || m.id).replace(/^ollama\//, "")}</span>
                      {isOllamaModel(m) ? <em>Ollama</em> : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="side-copy">Install a model from Library to start.</p>
            )}
          </div>
          <SessionMeta engineTitle={engineTitle} lastStats={lastStats} rssMb={rssMb} />
        </>
      ) : null}

      {tab === "agent" ? (
        <>
          <div className="side-head">
            <strong>Workspace</strong>
            <span className="muted">{workspaceReady ? "Ready" : "Pick a folder"}</span>
          </div>
          <div className="side-workspace">
            <label className="workspace-field">
              <span>Folder</span>
              <input
                value={workspace}
                onChange={(e) => onWorkspaceChange(e.target.value)}
                placeholder="/path/to/project"
                disabled={agentBusy || pickingFolder}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    onApplyWorkspace();
                  }
                }}
              />
            </label>
            <div className="side-actions">
              <button
                type="button"
                className="btn ghost"
                disabled={agentBusy || pickingFolder}
                onClick={onBrowseWorkspace}
              >
                {pickingFolder ? "…" : "Browse"}
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={agentBusy || pickingFolder}
                onClick={onApplyWorkspace}
              >
                Use
              </button>
            </div>
          </div>
          {agentStatus ? <p className="side-status">{agentStatus}</p> : null}
          <div className="side-tree" aria-label="Workspace files">
            <div className="side-label">Files</div>
            {!workspaceReady ? (
              <p className="side-copy">Browse or enter a path, then Use.</p>
            ) : tree.length === 0 ? (
              <p className="side-copy">Folder is empty.</p>
            ) : (
              <ul>
                {tree.map((e) => (
                  <li key={e.path} className={e.type === "dir" ? "dir" : "file"}>
                    {e.type === "dir" ? "▸ " : ""}
                    {e.name}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : null}

      {tab === "library" ? (
        <>
          <div className="side-head">
            <strong>Library</strong>
            <span className="muted">
              {catalogCount} catalog · {ollamaCount} Ollama
            </span>
          </div>
          <div className="side-block">
            <label className="search">
              <span className="sr">Search</span>
              <input
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                placeholder="Search models"
              />
            </label>
          </div>
          <div className="side-group">
            <div className="side-label">Family</div>
            <div className="side-nav" role="tablist" aria-label="Model families">
              {FAMILIES.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="tab"
                  aria-selected={family === f.id}
                  className={family === f.id ? "active" : ""}
                  onClick={() => onFamilyChange(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {tab === "advanced" ? (
        <>
          <div className="side-head">
            <strong>Settings</strong>
            {appVersion ? <span className="muted">{appVersion}</span> : null}
          </div>
          <nav className="side-nav" aria-label="Settings">
            {[
              ["adv-updates", "Updates"],
              ["adv-engine", "Engine"],
              ["adv-routing", "Routing"],
              ["adv-windhover", "Windhover"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
              >
                {label}
              </button>
            ))}
          </nav>
          <SessionMeta engineTitle={engineTitle} lastStats={lastStats} rssMb={rssMb} />
        </>
      ) : null}
    </aside>
  );
}

function sidebarLabel(tab: Tab) {
  if (tab === "agent") return "Workspace";
  if (tab === "library") return "Model filters";
  if (tab === "advanced") return "Settings";
  return "Chat";
}

function SessionMeta({
  engineTitle,
  lastStats,
  rssMb,
}: {
  engineTitle: string;
  lastStats: ChatStats | null;
  rssMb: number;
}) {
  return (
    <div className="side-meta">
      <div className="side-label">Status</div>
      <p className="side-copy">{engineTitle}</p>
      <dl>
        <div>
          <dt>RAM</dt>
          <dd>{rssMb ? `${rssMb.toFixed(0)} MB` : "—"}</dd>
        </div>
        <div>
          <dt>Last</dt>
          <dd>{lastStats?.tokens_per_sec != null ? `${lastStats.tokens_per_sec} tok/s` : "—"}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{lastStats?.latency_ms != null ? `${lastStats.latency_ms} ms` : "—"}</dd>
        </div>
      </dl>
    </div>
  );
}
