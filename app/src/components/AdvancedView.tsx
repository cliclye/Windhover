import type { ChatStats, EngineState } from "../types";

export function AdvancedView({
  appVersion,
  updateInfo,
  updateMsg,
  updateBusy,
  onCheckUpdate,
  onApplyUpdate,
  onRefresh,
  engineOk,
  enginePresent,
  engineState,
  lastStats,
  stats,
  activeModel,
  chatCapableCount,
}: {
  appVersion: string;
  updateInfo: {
    available?: boolean;
    current?: string;
    latest?: string;
    html_url?: string;
  } | null;
  updateMsg: string;
  updateBusy: boolean;
  onCheckUpdate: () => void;
  onApplyUpdate: () => void;
  onRefresh: () => void;
  engineOk: boolean | null;
  enginePresent: boolean | null;
  engineState: EngineState;
  lastStats: ChatStats | null;
  stats: {
    rss_mb?: number;
    engine?: string;
    chat_preview?: string;
  } | null;
  activeModel: string;
  chatCapableCount: number;
}) {
  return (
    <section className="advanced-pane library-scroll">
      <header className="page-head">
        <h1>Settings</h1>
        <p>Engine, updates, and last-turn routing.</p>
        <div className="page-actions">
          <button type="button" className="btn ghost" onClick={onRefresh}>
            Refresh
          </button>
          <button type="button" className="btn ghost" disabled={updateBusy} onClick={onCheckUpdate}>
            Check for updates
          </button>
        </div>
      </header>

      <div className="adv-block" id="adv-updates">
        <h2>Updates</h2>
        <p className="muted">
          Current <code>{appVersion || updateInfo?.current || "…"}</code>
          {updateInfo?.latest ? (
            <>
              {" "}
              · Latest <code>{updateInfo.latest}</code>
            </>
          ) : null}
        </p>
        {updateInfo?.available ? (
          <p>A newer build is ready. One click installs and restarts.</p>
        ) : (
          <p className="muted">{updateMsg || "Up to date."}</p>
        )}
        <div className="modal-actions" style={{ marginTop: "0.75rem" }}>
          {updateInfo?.available ? (
            <button type="button" className="btn primary" disabled={updateBusy} onClick={onApplyUpdate}>
              {updateBusy ? "Updating…" : "Update now"}
            </button>
          ) : null}
          {updateInfo?.html_url ? (
            <a className="btn ghost" href={updateInfo.html_url} target="_blank" rel="noreferrer">
              Releases
            </a>
          ) : null}
        </div>
      </div>

      <div className="metrics-grid" id="adv-engine">
        <div className={`metric ${engineState === "on" ? "on" : "off"}`}>
          <span className="metric-label">Engine</span>
          <strong className="metric-value">
            {engineOk === false ? "Off" : enginePresent === false ? "No binary" : engineOk ? "On" : "…"}
          </strong>
        </div>
        <div className="metric">
          <span className="metric-label">Process RSS</span>
          <strong className="metric-value">
            {Number(lastStats?.rss_mb ?? stats?.rss_mb ?? 0).toFixed(1)}
            <small> MB</small>
          </strong>
        </div>
        <div className="metric">
          <span className="metric-label">Latency</span>
          <strong className="metric-value">
            {lastStats?.latency_ms ?? "—"}
            <small> ms</small>
          </strong>
        </div>
        <div className="metric">
          <span className="metric-label">Speed</span>
          <strong className="metric-value">
            {lastStats?.tokens_per_sec ?? "—"}
            <small> tok/s</small>
          </strong>
        </div>
      </div>

      <div className="adv-block" id="adv-routing">
        <h2>Routing</h2>
        <dl className="kv">
          <div>
            <dt>Selected model</dt>
            <dd>{lastStats?.selected_model || activeModel || "—"}</dd>
          </div>
          <div>
            <dt>Backend</dt>
            <dd>{lastStats?.backend || "—"}</dd>
          </div>
          <div>
            <dt>Chat weights</dt>
            <dd>{lastStats?.preview_model || stats?.chat_preview || "windhover-engine SNAP"}</dd>
          </div>
          <div>
            <dt>Engine binary</dt>
            <dd className="mono">{stats?.engine || "—"}</dd>
          </div>
          <div>
            <dt>Chat-capable installs</dt>
            <dd>{chatCapableCount}</dd>
          </div>
        </dl>
      </div>

      {lastStats?.windhover ? (
        <div className="adv-block" id="adv-windhover">
          <h2>Windhover</h2>
          <dl className="kv">
            <div>
              <dt>Decode</dt>
              <dd>
                {lastStats.windhover.decode_tok_s != null ? `${lastStats.windhover.decode_tok_s} tok/s` : "—"}
              </dd>
            </div>
            <div>
              <dt>Prefill</dt>
              <dd>
                {lastStats.windhover.prefill_tok_s != null ? `${lastStats.windhover.prefill_tok_s} tok/s` : "—"}
              </dd>
            </div>
            <div>
              <dt>Working-set footprint</dt>
              <dd>
                {lastStats.windhover.footprint_gb != null ? `${lastStats.windhover.footprint_gb} GB` : "—"}
              </dd>
            </div>
            <div>
              <dt>FFN sparsity</dt>
              <dd>
                {lastStats.windhover.sparsity_pct != null ? `${lastStats.windhover.sparsity_pct}%` : "—"}
              </dd>
            </div>
            <div>
              <dt>Bytes / token</dt>
              <dd>
                {lastStats.windhover.bytes_per_tok != null
                  ? `${(lastStats.windhover.bytes_per_tok / 1e9).toFixed(2)} GB`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>AU hot hit</dt>
              <dd>{lastStats.windhover.au_hit_pct != null ? `${lastStats.windhover.au_hit_pct}%` : "—"}</dd>
            </div>
            <div>
              <dt>Forwards</dt>
              <dd>{lastStats.windhover.forwards ?? "—"}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <div className="adv-block" id="adv-windhover">
          <h2>Windhover</h2>
          <p className="muted">No engine telemetry yet. Send a chat turn to populate this section.</p>
        </div>
      )}
    </section>
  );
}
