import type { ChatStats, EngineState, RamProfileInfo } from "../types";
import { Segmented } from "./Primitives";

type UpdateInfo = {
  available?: boolean;
  current?: string;
  latest?: string;
  html_url?: string;
} | null;

const PROFILES: Array<{ value: string; label: string; blurb: string }> = [
  { value: "fast", label: "Fast", blurb: "Pins the full FFN in RAM (no ceiling). Highest tok/s, highest wired memory." },
  { value: "balanced", label: "Balanced", blurb: "Caps the engine at ~55% of RAM; cold FFN rows page from SSD. Default on 16 GB." },
  { value: "low", label: "Low-RAM", blurb: "Caps at ~40% of RAM with no mlock — leaves the most room for other apps." },
];

export function SettingsView({
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
  ramProfile,
  onRamProfile,
  theme,
  onTheme,
  busy,
}: {
  appVersion: string;
  updateInfo: UpdateInfo;
  updateMsg: string;
  updateBusy: boolean;
  onCheckUpdate: () => void;
  onApplyUpdate: () => void;
  onRefresh: () => void;
  engineOk: boolean | null;
  enginePresent: boolean | null;
  engineState: EngineState;
  lastStats: ChatStats | null;
  stats: { rss_mb?: number; engine?: string; chat_preview?: string } | null;
  activeModel: string;
  chatCapableCount: number;
  ramProfile?: RamProfileInfo | null;
  onRamProfile: (name: string) => void;
  theme: "light" | "dark" | "system";
  onTheme: (t: "light" | "dark" | "system") => void;
  busy: boolean;
}) {
  const cur = ramProfile?.name || "balanced";
  const curBlurb = PROFILES.find((p) => p.value === cur)?.blurb;
  return (
    <section className="pane scroll-pane">
      <div className="page narrow">
        <header className="page-head">
          <div>
            <h1>Settings</h1>
            <p className="page-sub">Memory, updates, appearance and engine routing.</p>
          </div>
          <button type="button" className="btn ghost sm" onClick={onRefresh}>
            Refresh
          </button>
        </header>

        <div className="card setting">
          <div className="setting-text">
            <h2>Memory profile</h2>
            <p>{ramProfile?.blurb || curBlurb}</p>
            {ramProfile?.physical_ram_gb ? (
              <p className="setting-meta">
                {Math.round(ramProfile.physical_ram_gb)} GB installed
                {ramProfile.ram_gb ? ` · engine cap ${ramProfile.ram_gb} GB` : " · no cap"}
              </p>
            ) : null}
          </div>
          <Segmented
            label="Memory profile"
            value={cur}
            disabled={busy}
            options={PROFILES.map((p) => ({ value: p.value, label: p.label, title: p.blurb }))}
            onChange={onRamProfile}
          />
        </div>

        <div className="card setting">
          <div className="setting-text">
            <h2>Appearance</h2>
            <p>Follow the system, or pin light or dark.</p>
          </div>
          <Segmented
            label="Theme"
            value={theme}
            options={[
              { value: "system", label: "System" },
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
            ]}
            onChange={onTheme}
          />
        </div>

        <div className="card setting">
          <div className="setting-text">
            <h2>Updates</h2>
            <p>
              Installed <code>{appVersion || updateInfo?.current || "…"}</code>
              {updateInfo?.latest ? (
                <>
                  {" "}
                  · latest <code>{updateInfo.latest}</code>
                </>
              ) : null}
            </p>
            <p className="setting-meta">
              {updateInfo?.available ? "A newer build is ready — installs and restarts in one click." : updateMsg || "Up to date."}
            </p>
          </div>
          <div className="setting-actions">
            {updateInfo?.html_url ? (
              <a className="btn ghost sm" href={updateInfo.html_url} target="_blank" rel="noreferrer">
                Release notes
              </a>
            ) : null}
            {updateInfo?.available ? (
              <button type="button" className="btn primary sm" disabled={updateBusy} onClick={onApplyUpdate}>
                {updateBusy ? "Updating…" : "Update now"}
              </button>
            ) : (
              <button type="button" className="btn ghost sm" disabled={updateBusy} onClick={onCheckUpdate}>
                Check now
              </button>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Engine</h2>
            <span className={`engine-pill ${engineState}`}>
              <i />
              {engineOk === false ? "Offline" : enginePresent === false ? "Binary missing" : engineOk ? "Ready" : "Checking"}
            </span>
          </div>
          <dl className="kv">
            <div>
              <dt>Selected model</dt>
              <dd>{lastStats?.selected_model || activeModel || "—"}</dd>
            </div>
            <div>
              <dt>Last backend</dt>
              <dd>{lastStats?.backend || "—"}</dd>
            </div>
            <div>
              <dt>Engine warm</dt>
              <dd>{lastStats?.engine_warm ? "Yes — weights mapped, prefix cache live" : "No (loads on next message)"}</dd>
            </div>
            <div>
              <dt>Chat weights</dt>
              <dd>{lastStats?.preview_model || (lastStats?.backend === "windhover-engine" ? "windhover-engine pack" : stats?.chat_preview) || "windhover-engine pack"}</dd>
            </div>
            <div>
              <dt>Engine binary</dt>
              <dd className="mono trunc" title={stats?.engine}>
                {stats?.engine || "—"}
              </dd>
            </div>
            <div>
              <dt>Chat-capable installs</dt>
              <dd>{chatCapableCount}</dd>
            </div>
            <div>
              <dt>API process RSS</dt>
              <dd>{Number(stats?.rss_mb ?? 0).toFixed(0)} MB</dd>
            </div>
          </dl>
        </div>
      </div>
    </section>
  );
}
