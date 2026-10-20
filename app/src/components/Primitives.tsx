import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckIcon, ChevronIcon, CloseIcon } from "./Icons";

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  actions,
  wide,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  actions?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className={`modal${wide ? " modal-wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle ? <div className="modal-sub">{subtitle}</div> : null}
          </div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {actions ? <div className="modal-actions">{actions}</div> : null}
      </div>
    </div>,
    document.body
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  disabled,
  label,
}: {
  value: T;
  options: Array<{ value: T; label: string; title?: string }>;
  onChange: (v: T) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          disabled={disabled}
          className={o.value === value ? "on" : undefined}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export type PickerItem = { value: string; label: string; hint?: string; group?: string };

/** Keyboard-friendly popover select (native <select> can't show hints / groups nicely). */
export function Picker({
  value,
  items,
  onChange,
  placeholder,
  disabled,
  label,
  icon,
  active,
  title,
}: {
  value: string;
  items: PickerItem[];
  onChange: (v: string) => void;
  placeholder: string;
  disabled?: boolean;
  label: string;
  icon?: ReactNode;
  /** Accent the button (e.g. a mode that is switched on). */
  active?: boolean;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const cur = items.find((i) => i.value === value);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  useEffect(() => {
    if (open) setHi(Math.max(0, items.findIndex((i) => i.value === value)));
  }, [open, items, value]);
  return (
    <div className={`picker${open ? " open" : ""}${active ? " on" : ""}`} ref={ref}>
      <button
        type="button"
        className="picker-btn"
        title={title}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        disabled={disabled || !items.length}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setOpen(true);
            return;
          }
          if (!open) return;
          if (e.key === "Escape") setOpen(false);
          else if (e.key === "ArrowDown") {
            e.preventDefault();
            setHi((h) => Math.min(items.length - 1, h + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHi((h) => Math.max(0, h - 1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const it = items[hi];
            if (it) onChange(it.value);
            setOpen(false);
          }
        }}
      >
        {icon}
        <span className="picker-label">{cur ? cur.label : placeholder}</span>
        {cur?.hint ? <span className="picker-hint">{cur.hint}</span> : null}
        <ChevronIcon size={14} />
      </button>
      {open ? (
        <ul className="picker-menu" role="listbox" aria-label={label}>
          {items.map((it, i) => {
            const showGroup = it.group && (i === 0 || items[i - 1].group !== it.group);
            return (
              <li key={it.value} role="presentation">
                {showGroup ? <div className="picker-group">{it.group}</div> : null}
                <button
                  type="button"
                  role="option"
                  aria-selected={it.value === value}
                  className={`picker-opt${i === hi ? " hi" : ""}`}
                  onMouseEnter={() => setHi(i)}
                  onClick={() => {
                    onChange(it.value);
                    setOpen(false);
                  }}
                >
                  <span className="picker-opt-label">{it.label}</span>
                  {it.hint ? <span className="picker-opt-hint">{it.hint}</span> : null}
                  {it.value === value ? <CheckIcon size={14} /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function Progress({ pct, message }: { pct: number; message?: string }) {
  const p = Math.max(2, Math.min(100, pct));
  return (
    <div className="progress" aria-live="polite">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${p}%` }} />
      </div>
      <div className="progress-meta">
        <span className="mono">{Math.round(pct)}%</span>
        {message ? <span className="progress-msg">{message}</span> : null}
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  unit,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: "good" | "warn" | "bad";
  hint?: string;
}) {
  return (
    <div className={`stat${tone ? ` ${tone}` : ""}`} title={hint}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {value}
        {unit ? <small>{unit}</small> : null}
      </span>
    </div>
  );
}

/** Tiny dependency-free SVG sparkline. */
export function Sparkline({ values, height = 36 }: { values: number[]; height?: number }) {
  const w = 160;
  const vs = values.filter((v) => Number.isFinite(v));
  if (vs.length < 2) return <div className="spark-empty">Not enough turns yet</div>;
  const max = Math.max(...vs) * 1.1 || 1;
  const step = w / (vs.length - 1);
  const pts = vs.map((v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * height).toFixed(1)}`);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" aria-hidden>
      <polyline points={`0,${height} ${pts.join(" ")} ${w},${height}`} className="spark-area" />
      <polyline points={pts.join(" ")} className="spark-line" />
    </svg>
  );
}
