import type { ReactNode } from "react";
import {
  agentSummaryText,
  agentVisibleReply,
  toolActivityGroup,
  toolActivityLabel,
  type AgentToolResult,
} from "../agentUi";
import type { AgentStep } from "../types";
import { Composer } from "./Composer";
import { FileIcon, FolderIcon } from "./Icons";
import { MarkdownBody } from "./MarkdownBody";

type TreeEntry = { name: string; path: string; type: string; size?: number | null };

export function AgentView({
  agentSteps,
  agentBusy,
  agentPrompt,
  agentInput,
  onInput,
  onRun,
  chatCapable,
  composerLeft,
  workspace,
  onWorkspaceChange,
  workspaceReady,
  pickingFolder,
  onBrowseWorkspace,
  onApplyWorkspace,
  tree,
  agentPhase,
  agentStatus,
  agentSummary,
  onOpenLibrary,
}: {
  agentSteps: AgentStep[];
  agentBusy: boolean;
  agentPrompt: string;
  agentInput: string;
  onInput: (value: string) => void;
  onRun: () => void;
  chatCapable: boolean;
  composerLeft: ReactNode;
  workspace: string;
  onWorkspaceChange: (v: string) => void;
  workspaceReady: boolean;
  pickingFolder: boolean;
  onBrowseWorkspace: () => void;
  onApplyWorkspace: () => void;
  tree: TreeEntry[];
  agentPhase: string;
  agentStatus: string;
  agentSummary: string;
  onOpenLibrary: () => void;
}) {
  const sorted = [...tree].sort((a, b) =>
    a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1
  );
  return (
    <section className="pane agent-pane">
      <div className="agent-split">
        <aside className="ws-panel" aria-label="Workspace">
          <div className="ws-head">
            <h2>Workspace</h2>
            <span className={`ws-state ${workspaceReady ? "good" : ""}`}>{workspaceReady ? "Ready" : "Not set"}</span>
          </div>
          <p className="ws-note">The agent can only list, read and write inside this folder.</p>
          <div className="ws-path">
            <input
              value={workspace}
              onChange={(e) => onWorkspaceChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onApplyWorkspace();
              }}
              placeholder="/Users/you/project"
              aria-label="Workspace folder path"
              spellCheck={false}
              disabled={agentBusy}
            />
          </div>
          <div className="ws-btns">
            <button type="button" className="btn ghost sm" disabled={agentBusy || pickingFolder} onClick={onBrowseWorkspace}>
              {pickingFolder ? "Choosing…" : "Choose folder…"}
            </button>
            <button type="button" className="btn primary sm" disabled={agentBusy || !workspace.trim()} onClick={onApplyWorkspace}>
              Use path
            </button>
          </div>
          {agentStatus && !agentBusy ? <p className="ws-status">{agentStatus}</p> : null}
          <div className="ws-tree">
            {sorted.length ? (
              <ul>
                {sorted.slice(0, 400).map((t) => (
                  <li key={t.path} className={t.type === "dir" ? "dir" : "file"} title={t.path}>
                    {t.type === "dir" ? <FolderIcon size={14} /> : <FileIcon size={14} />}
                    <span>{t.name}</span>
                    {t.type !== "dir" && t.size != null ? (
                      <em>{t.size > 1024 ? `${(t.size / 1024).toFixed(1)}k` : t.size}</em>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ws-empty">{workspaceReady ? "Folder is empty." : "No folder selected."}</p>
            )}
          </div>
        </aside>

        <div className="agent-main">
          <div className="thread">
            {agentSteps.length === 0 && !agentBusy && !agentPrompt ? (
              <div className="hero small">
                <h1>Local coding agent</h1>
                <p className="hero-sub">
                  {!chatCapable
                    ? "Install a chat-capable model first, then pick a folder."
                    : workspaceReady
                      ? "Describe a change. The model explores and edits files in your workspace."
                      : "Choose a workspace folder on the left, then describe a change."}
                </p>
                {!chatCapable ? (
                  <button type="button" className="btn primary" onClick={onOpenLibrary}>
                    Browse models
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="thread-inner">
                {agentPrompt ? (
                  <div className="msg user">
                    <div className="msg-bubble">{agentPrompt}</div>
                  </div>
                ) : null}
                {agentSteps.map((s) => {
                  const results = (s.tool_results || []) as AgentToolResult[];
                  const group = toolActivityGroup(results);
                  const hasTools = results.length > 0 || (s.tool_calls || []).length > 0;
                  const reply = agentVisibleReply(s.assistant || "", hasTools);
                  return (
                    <div className="agent-step" key={s.step}>
                      {results.length ? (
                        <details className="activity">
                          <summary>
                            <span className="activity-dot" />
                            {group || `${results.length} tool call${results.length === 1 ? "" : "s"}`}
                          </summary>
                          <ul>
                            {results.map((tr, i) => (
                              <li key={i} className={tr.ok === false ? "bad" : undefined}>
                                {toolActivityLabel(tr)}
                                {tr.ok === false && tr.error ? <span className="activity-err"> — {String(tr.error)}</span> : null}
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      {reply ? (
                        <div className="md agent-reply">
                          <MarkdownBody text={reply} />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
                {agentBusy ? (
                  <div className="agent-working" aria-live="polite">
                    <span className="typing">
                      <i />
                      <i />
                      <i />
                    </span>
                    <div>
                      <strong>{agentPhase === "tool" ? "Working in your files" : "Thinking"}</strong>
                      <span>{agentStatus || "Starting…"}</span>
                    </div>
                  </div>
                ) : null}
                {agentSummaryText(agentSummary) &&
                !agentBusy &&
                !agentSteps.some(
                  (st) =>
                    agentVisibleReply(st.assistant || "", false).trim() === agentSummaryText(agentSummary)
                ) &&
                !agentSteps.some((st) =>
                  (st.tool_results || []).some(
                    (r) => String((r as AgentToolResult).summary || "").trim() === agentSummary.trim()
                  )
                ) ? (
                  <p className="agent-summary">{agentSummaryText(agentSummary)}</p>
                ) : null}
              </div>
            )}
          </div>
          <Composer
            value={agentInput}
            onChange={onInput}
            onSubmit={onRun}
            busy={agentBusy}
            placeholder={workspaceReady ? "Ask the agent to explore or edit files" : "Choose a workspace first"}
            disabled={agentBusy || !chatCapable}
            footerLeft={composerLeft}
            submitLabel="Run agent"
          />
        </div>
      </div>
    </section>
  );
}
