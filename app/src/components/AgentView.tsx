import type { ReactNode } from "react";
import {
  agentVisibleReply,
  toolActivityGroup,
  toolActivityLabel,
  type AgentToolResult,
} from "../agentUi";
import type { AgentStep } from "../types";
import { Composer } from "./Composer";
import { MarkdownBody } from "./MarkdownBody";

export function AgentView({
  agentSteps,
  agentBusy,
  agentPrompt,
  agentInput,
  onInput,
  onRun,
  chatCapable,
  modelSelect,
  workspaceReady,
  agentPhase,
  agentStatus,
  agentSummary,
}: {
  agentSteps: AgentStep[];
  agentBusy: boolean;
  agentPrompt: string;
  agentInput: string;
  onInput: (value: string) => void;
  onRun: () => void;
  chatCapable: boolean;
  modelSelect: ReactNode;
  workspaceReady: boolean;
  agentPhase: string;
  agentStatus: string;
  agentSummary: string;
}) {
  return (
    <section className="work-pane agent-work">
      <div className="agent-thread work-scroll">
        {agentSteps.length === 0 && !agentBusy && !agentPrompt ? (
          <div className="empty">
            <strong>What should we change?</strong>
            <span>
              {workspaceReady
                ? "Describe an edit. The model only touches the folder you picked."
                : "Pick a workspace folder, then describe the edit."}
            </span>
          </div>
        ) : (
          <div className="agent-transcript">
            {agentPrompt ? (
              <div className="agent-user">
                <span className="agent-role">You</span>
                <p>{agentPrompt}</p>
              </div>
            ) : null}

            {agentSteps.map((s) => {
              const results = (s.tool_results || []) as AgentToolResult[];
              const group = toolActivityGroup(results);
              const hasTools = results.length > 0 || (s.tool_calls || []).length > 0;
              const reply = agentVisibleReply(s.assistant || "", hasTools);
              return (
                <div className="agent-turn" key={s.step}>
                  {results.length ? (
                    <details className="agent-activity">
                      <summary>
                        {group || `${results.length} tool call${results.length === 1 ? "" : "s"}`}
                      </summary>
                      <ul>
                        {results.map((tr, i) => (
                          <li key={i} className={tr.ok === false ? "bad" : undefined}>
                            {toolActivityLabel(tr)}
                            {tr.ok === false && tr.error ? (
                              <span className="agent-activity-err"> — {String(tr.error)}</span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                  {reply ? (
                    <div className="agent-reply md">
                      <MarkdownBody text={reply} />
                    </div>
                  ) : null}
                </div>
              );
            })}

            {agentBusy ? (
              <div className="agent-thinking" aria-live="polite">
                <span className="think-dots">
                  <i />
                  <i />
                  <i />
                </span>
                <div className="agent-working">
                  <strong>{agentPhase === "tool" ? "Working in your files" : "Working"}</strong>
                  <span>{agentStatus || "Starting…"}</span>
                </div>
              </div>
            ) : null}

            {agentSummary && !agentBusy ? <p className="agent-footer muted">{agentSummary}</p> : null}
          </div>
        )}
      </div>

      <Composer
        value={agentInput}
        onChange={onInput}
        onSubmit={onRun}
        busy={agentBusy}
        placeholder="Ask the agent to explore or edit files"
        disabled={agentBusy || !chatCapable}
        footerLeft={modelSelect}
        submitLabel="Run"
      />
    </section>
  );
}
