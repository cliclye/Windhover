import type { ReactNode } from "react";
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
}) {
  const canSend = !disabled && (busy || value.trim().length > 0);
  return (
    <div className="composer-wrap">
      <div className="composer-shell">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          disabled={disabled || (busy && !onStop)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (busy) onStop?.();
              else onSubmit();
            }
          }}
        />
        <div className="composer-footer">
          <div className="composer-footer-left">{footerLeft}</div>
          <button
            type="button"
            className={`send-btn${busy ? " stop" : ""}`}
            disabled={!canSend}
            aria-label={busy ? stopLabel || "Stop" : submitLabel}
            onClick={() => (busy ? onStop?.() : onSubmit())}
          >
            {busy ? <StopIcon /> : <SendIcon />}
          </button>
        </div>
      </div>
    </div>
  );
}
