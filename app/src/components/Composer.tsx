import { useEffect, useRef, type ReactNode } from "react";
import { SendIcon, StopIcon } from "./Icons";

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
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && (busy ? !!onStop : value.trim().length > 0);

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
      <div className={`composer${disabled ? " disabled" : ""}`}>
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={1}
          disabled={disabled || (busy && !onStop)}
          aria-label={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (busy) onStop?.();
              else if (canSend) onSubmit();
            }
          }}
        />
        <div className="composer-bar">
          <div className="composer-left">{footerLeft}</div>
          <span className="composer-hint">
            <kbd>↵</kbd> send · <kbd>⇧↵</kbd> newline
          </span>
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
