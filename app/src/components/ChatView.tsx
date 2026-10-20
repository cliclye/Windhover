import { useState, type ReactNode, type Ref } from "react";
import type { ChatStats, Msg, WebSource } from "../types";
import type { Attachment } from "../images";
import { Composer } from "./Composer";
import { BoltIcon, CheckIcon, CopyIcon, GlobeIcon, RetryIcon } from "./Icons";
import { MarkdownBody } from "./MarkdownBody";

const STARTERS = [
  "Explain how a CPU cache works, simply.",
  "Write a Python script that renames files by date.",
  "Draft a polite follow-up email after an interview.",
  "Give me a 3-day itinerary for Kyoto in autumn.",
];

function StatChips({ s }: { s?: ChatStats }) {
  if (!s) return null;
  const wh = s.windhover;
  const chips: Array<{ k: string; v: string; title?: string; strong?: boolean }> = [];
  const tps = wh?.decode_tok_s ?? s.tokens_per_sec;
  if (tps) chips.push({ k: "speed", v: `${Number(tps).toFixed(1)} tok/s`, strong: true });
  if (wh?.prompt_tokens) {
    const cached = wh.cached_tokens || 0;
    chips.push({
      k: "prompt",
      v: cached > 0 ? `${cached}/${wh.prompt_tokens} cached` : `${wh.prompt_tokens} prompt tok`,
      title:
        cached > 0
          ? "Prompt tokens reused from the previous turn's KV cache (not recomputed)"
          : "Prompt tokens prefilled this turn",
    });
  }
  if (wh?.prefill_s != null) chips.push({ k: "ttft", v: `${(wh.prefill_s * 1000).toFixed(0)} ms prefill` });
  else if (s.latency_ms != null) chips.push({ k: "lat", v: `${Math.round(s.latency_ms)} ms` });
  if (wh?.rss_gb) chips.push({ k: "rss", v: `${wh.rss_gb.toFixed(2)} GB RSS` });
  if (s.backend && s.backend !== "windhover-engine") chips.push({ k: "be", v: s.backend });
  if (!chips.length) return null;
  return (
    <div className="msg-stats">
      {chips.map((c) => (
        <span key={c.k} className={`chip${c.strong ? " strong" : ""}`} title={c.title}>
          {c.k === "speed" ? <BoltIcon size={12} /> : null}
          {c.v}
        </span>
      ))}
    </div>
  );
}

function Sources({ sources }: { sources: WebSource[] }) {
  return (
    <div className="sources" aria-label="Web sources">
      {sources.map((s) => (
        <a key={s.n} className="source" href={s.url} target="_blank" rel="noreferrer" title={`${s.title}\n${s.url}`}>
          <span className="source-n">{s.n}</span>
          <span className="source-domain">{s.domain}</span>
        </a>
      ))}
    </div>
  );
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="msg-act"
      aria-label="Copy reply"
      title="Copy"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(
          () => {
            setDone(true);
            setTimeout(() => setDone(false), 1200);
          },
          () => undefined
        );
      }}
    >
      {done ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
    </button>
  );
}

export function ChatView({
  messages,
  sending,
  input,
  onInput,
  onSend,
  attachments,
  onAttachments,
  onStop,
  onRetry,
  onStarter,
  chatCapable,
  loading,
  composerLeft,
  threadRef,
  modelName,
  onOpenLibrary,
  banner,
}: {
  messages: Msg[];
  sending: boolean;
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  attachments: Attachment[];
  onAttachments: (a: Attachment[]) => void;
  onStop: () => void;
  onRetry: () => void;
  onStarter: (text: string) => void;
  chatCapable: boolean;
  loading?: boolean;
  composerLeft: ReactNode;
  threadRef: Ref<HTMLDivElement>;
  modelName: string;
  onOpenLibrary: () => void;
  banner: string | null;
}) {
  const lastAssistant = messages.length - 1;
  return (
    <section className="pane chat-pane">
      {banner ? (
        <div className="banner warn" role="alert">
          {banner}
        </div>
      ) : null}
      <div className="thread" ref={threadRef}>
        {messages.length === 0 && !sending ? (
          <div className="hero">
            <div className="hero-mark">
              <img src="./windhover-icon.png" alt="" width={44} height={44} />
            </div>
            <h1>{chatCapable ? "What can I help with?" : loading ? "Starting Windhover…" : "Install a model to start"}</h1>
            <p className="hero-sub">
              {chatCapable
                ? `${modelName} · runs entirely on this computer`
                : loading
                  ? "Connecting to the local engine."
                  : "Pick a model that fits your machine in Models. Downloads come straight from Hugging Face."}
            </p>
            {loading && !chatCapable ? null : chatCapable ? (
              <div className="starters">
                {STARTERS.map((s) => (
                  <button key={s} type="button" className="starter" onClick={() => onStarter(s)}>
                    {s}
                  </button>
                ))}
              </div>
            ) : (
              <button type="button" className="btn primary" onClick={onOpenLibrary}>
                Browse models
              </button>
            )}
          </div>
        ) : (
          <div className="thread-inner">
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div className="msg user" key={i}>
                  {m.thumbs?.length ? (
                    <div className="msg-images">
                      {m.thumbs.map((t, j) => (
                        <img key={j} src={t} alt={`Attached image ${j + 1}`} />
                      ))}
                    </div>
                  ) : null}
                  {m.content ? <div className="msg-bubble">{m.content}</div> : null}
                </div>
              ) : (
                <div className="msg assistant" key={i}>
                  <div className="msg-avatar" aria-hidden>
                    <img src="./windhover-icon.png" alt="" width={20} height={20} />
                  </div>
                  <div className="msg-body">
                    {m.webStatus && !m.content ? (
                      <div className="web-status" aria-live="polite">
                        <GlobeIcon size={14} />
                        <span>{m.webStatus}</span>
                        <span className="typing">
                          <i />
                          <i />
                          <i />
                        </span>
                      </div>
                    ) : null}
                    {m.webError ? (
                      <div className="web-note">
                        <GlobeIcon size={13} />
                        Couldn't search the web ({m.webError}) — answered from the model's own knowledge.
                      </div>
                    ) : null}
                    {m.sources?.length ? <Sources sources={m.sources} /> : null}
                    <div className={`md${sending && i === lastAssistant ? " is-streaming" : ""}`}>
                      <MarkdownBody text={m.content} streaming={sending && i === lastAssistant} sources={m.sources} />
                    </div>
                    <div className="msg-foot">
                      <StatChips s={m.stats} />
                      {!(sending && i === lastAssistant) ? (
                        <div className="msg-actions">
                          <CopyBtn text={m.content} />
                          {i === lastAssistant ? (
                            <button
                              type="button"
                              className="msg-act"
                              aria-label="Regenerate"
                              title="Regenerate"
                              onClick={onRetry}
                            >
                              <RetryIcon size={14} />
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              )
            )}
            {sending && messages[messages.length - 1]?.role !== "assistant" ? (
              <div className="msg assistant" aria-live="polite">
                <div className="msg-avatar" aria-hidden>
                  <img src="./windhover-icon.png" alt="" width={20} height={20} />
                </div>
                <div className="msg-body">
                  <span className="typing">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
      <Composer
        value={input}
        onChange={onInput}
        onSubmit={onSend}
        onStop={onStop}
        busy={sending}
        placeholder={chatCapable ? `Message ${modelName}` : "Install a model first"}
        disabled={!chatCapable && !sending}
        footerLeft={composerLeft}
        submitLabel="Send"
        stopLabel="Stop generating"
        attachments={attachments}
        onAttachments={onAttachments}
        autoFocus
      />
    </section>
  );
}
