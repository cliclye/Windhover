import type { ChatStats, EngineState, RamProfileInfo, TelemetryPoint } from "../types";
import { Sparkline, Stat } from "./Primitives";

function fmt(n: number | undefined | null, digits = 1) {
  return n == null || Number.isNaN(n) ? "—" : Number(n).toFixed(digits);
}

export function PerformanceView({
  lastStats,
  history,
  engineState,
  ramProfile,
  rssMb,
  onClear,
}: {
  lastStats: ChatStats | null;
  history: TelemetryPoint[];
  engineState: EngineState;
  ramProfile?: RamProfileInfo | null;
  rssMb: number;
  onClear: () => void;
}) {
  const wh = lastStats?.windhover;
  const decode = history.map((h) => h.decode ?? NaN);
  const prefill = history.map((h) => h.prefill ?? NaN);
  const cachedTotal = history.reduce((a, h) => a + (h.cached || 0), 0);
  const promptTotal = history.reduce((a, h) => a + (h.prompt || 0), 0);
  const hitRate = promptTotal ? (100 * cachedTotal) / promptTotal : 0;
  const best = decode.filter(Number.isFinite);
  const avgDecode = best.length ? best.reduce((a, b) => a + b, 0) / best.length : undefined;
  return (
    <section className="pane scroll-pane">
      <div className="page">
        <header className="page-head">
          <div>
            <h1>Performance</h1>
            <p className="page-sub">Live telemetry from windhover-engine. Everything is measured on this computer.</p>
          </div>
          <button type="button" className="btn ghost sm" onClick={onClear} disabled={!history.length}>
            Clear history
          </button>
        </header>

        <div className="stat-grid">
          <Stat
            label="Decode"
            value={fmt(wh?.decode_tok_s ?? lastStats?.tokens_per_sec)}
            unit="tok/s"
            tone={engineState === "on" ? "good" : undefined}
            hint="Tokens generated per second in the last reply"
          />
          <Stat label="Prefill" value={fmt(wh?.prefill_tok_s, 0)} unit="tok/s" hint="Prompt tokens processed per second" />
          <Stat
            label="Time to first token"
            value={wh?.prefill_s != null ? fmt(wh.prefill_s * 1000, 0) : "—"}
            unit="ms"
            hint="Prefill wall time of the last turn"
          />
          <Stat
            label="Prefix cache"
            value={wh?.prompt_tokens ? `${wh.cached_tokens || 0}/${wh.prompt_tokens}` : "—"}
            unit="tok"
            tone={wh?.cached_tokens ? "good" : undefined}
            hint="Prompt tokens reused from the previous turn's KV cache"
          />
          <Stat label="Engine RSS" value={fmt(wh?.rss_gb ?? rssMb / 1024, 2)} unit="GB" />
          <Stat
            label="Bytes / token"
            value={wh?.bytes_per_tok != null ? fmt(wh.bytes_per_tok / 1e9, 2) : "—"}
            unit="GB"
            hint="Weight bytes streamed per decoded token"
          />
          <Stat label="FFN sparsity" value={fmt(wh?.sparsity_pct)} unit="%" hint="CATS rows skipped in the FFN" />
          <Stat label="AU hot hit" value={fmt(wh?.au_hit_pct)} unit="%" hint="Activation-unit hits in the resident tier" />
        </div>

        <div className="perf-row">
          <div className="card">
            <div className="card-head">
              <h2>Decode speed</h2>
              <span className="card-note">{avgDecode ? `avg ${avgDecode.toFixed(1)} tok/s` : "per turn"}</span>
            </div>
            <Sparkline values={decode} height={56} />
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Prefill speed</h2>
              <span className="card-note">per turn</span>
            </div>
            <Sparkline values={prefill} height={56} />
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Prefix-cache reuse</h2>
              <span className="card-note">{promptTotal ? `${hitRate.toFixed(0)}% of prompt tokens` : "this session"}</span>
            </div>
            <div className="meter" aria-label={`${hitRate.toFixed(0)} percent cached`}>
              <div className="meter-fill" style={{ width: `${Math.min(100, hitRate)}%` }} />
            </div>
            <p className="card-foot">
              Multi-turn chats only prefill the new tokens; earlier turns are served from the engine's KV cache.
            </p>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Recent turns</h2>
            <span className="card-note">
              {ramProfile?.label ? `${ramProfile.label} profile` : ""}
              {ramProfile?.ram_gb ? ` · cap ${ramProfile.ram_gb} GB` : ""}
            </span>
          </div>
          {history.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Model</th>
                    <th className="num">Prompt</th>
                    <th className="num">Cached</th>
                    <th className="num">Prefill</th>
                    <th className="num">Decode</th>
                    <th className="num">RSS</th>
                  </tr>
                </thead>
                <tbody>
                  {[...history].reverse().slice(0, 30).map((h) => (
                    <tr key={h.t}>
                      <td className="mono">{new Date(h.t).toLocaleTimeString()}</td>
                      <td className="trunc">{h.model}</td>
                      <td className="num mono">{h.prompt ?? "—"}</td>
                      <td className="num mono">{h.cached ?? "—"}</td>
                      <td className="num mono">{h.prefillS != null ? `${(h.prefillS * 1000).toFixed(0)} ms` : "—"}</td>
                      <td className="num mono">{h.decode != null ? `${h.decode.toFixed(1)} tok/s` : "—"}</td>
                      <td className="num mono">{h.rssGb != null ? `${h.rssGb.toFixed(2)} GB` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty-note">Send a chat message to start collecting telemetry.</p>
          )}
        </div>
      </div>
    </section>
  );
}
