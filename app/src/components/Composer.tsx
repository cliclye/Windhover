import { useEffect, useRef, useState, type ReactNode } from "react";
import { CloseIcon, ImageIcon, SendIcon, StopIcon } from "./Icons";
import { fileToAttachment, imageFiles, MAX_ATTACHMENTS, type Attachment } from "../images";

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder,
  disabled,
  footerLeft,
  submitLabel,
  stopLabel,
  autoFocus,
  attachments,
  onAttachments,
  footerRight,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy?: boolean;
  placeholder: string;
  disabled?: boolean;
  footerLeft?: ReactNode;
  submitLabel: string;
  stopLabel?: string;
  autoFocus?: boolean;
  /** Image attachments; omit onAttachments to hide the attach button. */
  attachments?: Attachment[];
  onAttachments?: (next: Attachment[]) => void;
  footerRight?: ReactNode;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [attachErr, setAttachErr] = useState("");
  const atts = attachments || [];
  const canSend = !disabled && (busy ? !!onStop : value.trim().length > 0 || atts.length > 0);

  const addFiles = async (files: File[]) => {
    if (!onAttachments || !files.length) return;
    setAttachErr("");
    const room = MAX_ATTACHMENTS - atts.length;
    if (room <= 0) {
      setAttachErr(`Up to ${MAX_ATTACHMENTS} images per message.`);
      return;
    }
    const added: Attachment[] = [];
    for (const f of files.slice(0, room)) {
      try {
        added.push(await fileToAttachment(f));
      } catch {
        setAttachErr(`Couldn't read ${f.name || "that image"}.`);
      }
    }
    if (added.length) onAttachments([...atts, ...added]);
  };

  // Grow with content up to ~10 lines, then scroll.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!value) {
      el.style.height = "";
      return;
    }
    const fit = () => {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
    };
    fit();
    const raf = requestAnimationFrame(fit); // re-measure once layout has settled
    return () => cancelAnimationFrame(raf);
  }, [value]);

  useEffect(() => {
    if (autoFocus && !disabled) ref.current?.focus();
  }, [autoFocus, disabled]);

  return (
    <div className="composer-wrap">
      <div
        className={`composer${disabled ? " disabled" : ""}${dragging ? " dragging" : ""}`}
        onDragOver={(e) => {
          if (!onAttachments || disabled) return;
          if ([...e.dataTransfer.items].some((i) => i.kind === "file")) {
            e.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          setDragging(false);
          const files = imageFiles(e.dataTransfer.files);
          if (onAttachments && files.length) {
            e.preventDefault();
            void addFiles(files);
          }
        }}
      >
        {atts.length ? (
          <div className="attach-row">
            {atts.map((a) => (
              <div key={a.id} className="attach-chip" title={a.name}>
                <img src={a.thumb} alt={a.name} />
                <button
                  type="button"
                  className="attach-x"
                  aria-label={`Remove ${a.name}`}
                  onClick={() => onAttachments?.(atts.filter((x) => x.id !== a.id))}
                >
                  <CloseIcon size={12} />
                </button>
              </div>
            ))}
          </div>
        ) : null}
        {attachErr ? <div className="attach-err">{attachErr}</div> : null}
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={1}
          disabled={disabled || (busy && !onStop)}
          aria-label={placeholder}
          onPaste={(e) => {
            const files = imageFiles(e.clipboardData?.items);
            if (onAttachments && files.length) {
              e.preventDefault();
              void addFiles(files);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (busy) onStop?.();
              else if (canSend) onSubmit();
            }
          }}
        />
        <div className="composer-bar">
          <div className="composer-left">
            {onAttachments ? (
              <>
                <button
                  type="button"
                  className="icon-btn attach-btn"
                  aria-label="Attach image"
                  title="Attach image (or paste / drop one)"
                  disabled={disabled}
                  onClick={() => fileRef.current?.click()}
                >
                  <ImageIcon />
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => {
                    void addFiles(imageFiles(e.target.files));
                    e.target.value = "";
                  }}
                />
              </>
            ) : null}
            {footerLeft}
          </div>
          {footerRight ?? (
            <span className="composer-hint">
              <kbd>↵</kbd> send · <kbd>⇧↵</kbd> newline
            </span>
          )}
          <button
            type="button"
            className={`send-btn${busy ? " stop" : ""}`}
            disabled={!canSend}
            aria-label={busy ? stopLabel || "Stop" : submitLabel}
            title={busy ? stopLabel || "Stop" : submitLabel}
            onClick={() => (busy ? onStop?.() : onSubmit())}
          >
            {busy ? <StopIcon /> : <SendIcon />}
          </button>
        </div>
      </div>
    </div>
  );
}
