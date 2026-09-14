import type { ReactNode, Ref } from "react";
import { Composer } from "./Composer";
import { MarkdownBody } from "./MarkdownBody";
import type { Msg } from "../types";

export function ChatView({
  messages,
  sending,
  input,
  onInput,
  onSend,
  onStop,
  chatCapable,
  modelSelect,
  threadRef,
  emptyHint,
  onOpenLibrary,
  banner,
}: {
  messages: Msg[];
  sending: boolean;
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  chatCapable: boolean;
  modelSelect: ReactNode;
  threadRef: Ref<HTMLDivElement>;
  emptyHint: string;
  onOpenLibrary: () => void;
  banner: string | null;
}) {
  return (
    <section className="work-pane chat-work">
      {banner ? (
        <div className="engine-banner" role="alert">
          {banner}
        </div>
      ) : null}
      <div className="thread work-scroll" ref={threadRef}>
        {messages.length === 0 && !sending ? (
          <div className="empty">
            <strong>{chatCapable ? "Ask anything." : "Install a model to chat."}</strong>
            <span>{emptyHint}</span>
            {!chatCapable ? (
              <button type="button" className="btn primary" onClick={onOpenLibrary}>
                Open Library
              </button>
            ) : null}
          </div>
        ) : (
          <>
            {messages.map((m, i) => (
              <div className={`bubble ${m.role}`} key={i}>
                {m.role === "assistant" ? (
                  <div className="md">
                    <MarkdownBody text={m.content} />
                  </div>
                ) : (
                  m.content
                )}
                {m.role === "assistant" && m.stats?.tokens_per_sec ? (
                  <div className="bubble-meta">
                    {m.stats.tokens_per_sec} tok/s
                    {m.stats.latency_ms != null ? ` · ${m.stats.latency_ms} ms` : ""}
                    {m.stats.ram_gb != null ? ` · cap ${m.stats.ram_gb} GB` : ""}
                    {m.stats.ram_profile ? ` · ${m.stats.ram_profile}` : ""}
                    {m.stats.backend ? ` · ${m.stats.backend}` : ""}
                  </div>
                ) : null}
              </div>
            ))}
            {sending && messages[messages.length - 1]?.role !== "assistant" ? (
              <div className="bubble assistant thinking" aria-live="polite">
                <span className="think-dots">
                  <i />
                  <i />
                  <i />
                </span>
                Thinking…
              </div>
            ) : null}
          </>
        )}
      </div>
      <Composer
        value={input}
        onChange={onInput}
        onSubmit={onSend}
        onStop={onStop}
        busy={sending}
        placeholder="Message Windhover"
        disabled={!chatCapable && !sending}
        footerLeft={modelSelect}
        submitLabel="Send"
        stopLabel="Stop"
      />
    </section>
  );
}
