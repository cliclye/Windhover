import type { CatalogModel, Installed } from "../modelMeta";
import {
  FAMILIES,
  familyLabel,
  isMacSmall,
  isNewModel,
  matchInstalled,
  releasedLabel,
} from "../modelMeta";
import type { PullProgress } from "../types";
import { DownloadIcon, InfoIcon, SearchIcon, SparkIcon, TrashIcon } from "./Icons";
import { Progress } from "./Primitives";

function fitLabel(m: CatalogModel, physGb: number | null) {
  if (!m.ram_gb || !physGb) return null;
  if (m.ram_gb <= physGb * 0.6) return { cls: "good", label: "Runs well here" };
  if (m.ram_gb <= physGb * 0.9) return { cls: "warn", label: "Tight fit" };
  return { cls: "bad", label: `Needs ${m.ram_gb} GB+` };
}

function ModelCard({
  m,
  inst,
  busy,
  progress,
  physGb,
  onOpenInfo,
  onPull,
  onUninstall,
  onOpenChat,
  onUseInAgent,
  featured,
}: {
  m: CatalogModel;
  inst?: Installed;
  busy: string | null;
  progress: PullProgress | null;
  physGb: number | null;
  onOpenInfo: (m: CatalogModel) => void;
  onPull: (m: CatalogModel, weights?: boolean) => void;
  onUninstall: (id: string, name?: string, path?: string) => void;
  onOpenChat: (id: string) => void;
  onUseInAgent: (id: string) => void;
  featured?: boolean;
}) {
  const got = !!inst;
  const impostor = !!inst?.impostor && !inst?.incomplete;
  const incomplete = !!inst?.incomplete;
  const rowProgress = progress?.id === m.id ? progress : null;
  const isBusy = busy === m.id;
  const fit = fitLabel(m, physGb);
  const unsupported = m.status === "soon" || m.chat === "blocked";
  const fresh = isNewModel(m);
  return (
    <article className={`mcard${featured ? " featured" : ""}${got && !incomplete ? " installed" : ""}`}>
      <div className="mcard-top">
        <div className="mcard-title">
          <h3>{m.name}</h3>
          <div className="mcard-badges">
            {m.recommended ? (
              <span className="badge accent">
                <SparkIcon size={11} /> Recommended
              </span>
            ) : fresh ? (
              <span className="badge accent-soft">New</span>
            ) : null}
            {m.legacy ? <span className="badge muted">Legacy</span> : null}
            {got && !incomplete && !impostor ? <span className="badge good">Installed</span> : null}
            {impostor ? <span className="badge bad">Fake stub</span> : null}
            {incomplete && !rowProgress ? <span className="badge bad">Incomplete</span> : null}
            {got && inst?.needs_prepare && !rowProgress && !incomplete ? (
              <span className="badge warn">Needs prepare</span>
            ) : null}
          </div>
        </div>
        <button type="button" className="icon-btn" aria-label={`About ${m.name}`} onClick={() => onOpenInfo(m)}>
          <InfoIcon />
        </button>
      </div>
      <p className="mcard-desc">{m.description}</p>
      <dl className="mcard-meta">
        <div>
          <dt>Family</dt>
          <dd>{familyLabel(m.family)}</dd>
        </div>
        {m.params_b ? (
          <div>
            <dt>Params</dt>
            <dd>{m.params_b >= 10 ? m.params_b.toFixed(0) : m.params_b.toFixed(1)}B</dd>
          </div>
        ) : null}
        <div>
          <dt>Download</dt>
          <dd>{m.size_gb >= 100 ? m.size_gb.toFixed(0) : m.size_gb} GB</dd>
        </div>
        {m.ram_gb ? (
          <div>
            <dt>RAM</dt>
            <dd>{m.ram_gb}+ GB</dd>
          </div>
        ) : null}
        {m.released ? (
          <div>
            <dt>Released</dt>
            <dd>{releasedLabel(m)}</dd>
          </div>
        ) : null}
      </dl>
      {rowProgress ? <Progress pct={rowProgress.pct} message={rowProgress.message} /> : null}
      <div className="mcard-foot">
        {fit ? <span className={`fit ${fit.cls}`}>{fit.label}</span> : <span />}
        <div className="mcard-actions">
          {rowProgress ? (
            <button type="button" className="btn primary sm" disabled>
              {Math.round(rowProgress.pct)}%
            </button>
          ) : impostor ? (
            <button
              type="button"
              className="btn ghost sm danger"
              disabled={isBusy}
              onClick={() => onUninstall(m.id, m.name, inst?.path ?? undefined)}
            >
              {isBusy ? "Removing…" : "Remove"}
            </button>
          ) : incomplete || !got ? (
            <button
              type="button"
              className="btn primary sm"
              disabled={isBusy || !!progress || unsupported}
              onClick={() => onPull(m, true)}
            >
              <DownloadIcon size={14} />
              {unsupported ? "Unsupported" : incomplete ? "Reinstall" : isMacSmall(m) ? "Install" : "Download"}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn ghost sm icon-only"
                aria-label={`Uninstall ${m.name}`}
                title="Uninstall"
                disabled={isBusy}
                onClick={() => onUninstall(m.id, m.name, inst?.path ?? undefined)}
              >
                <TrashIcon size={14} />
              </button>
              {inst?.chat_ok ? (
                <>
                  <button type="button" className="btn ghost sm" onClick={() => onUseInAgent(m.id)}>
                    Agent
                  </button>
                  <button type="button" className="btn primary sm" onClick={() => onOpenChat(m.id)}>
                    Chat
                  </button>
                </>
              ) : (
                <button type="button" className="btn ghost sm" disabled>
                  No chat
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </article>
  );
}

export function LibraryView({
  status,
  progress,
  family,
  onFamilyChange,
  query,
  onQueryChange,
  catalog,
  filtered,
  filteredOllama,
  installed,
  busy,
  physGb,
  onOpenInfo,
  onPull,
  onUninstall,
  onOpenChat,
  onUseInAgent,
}: {
  status: string;
  progress: PullProgress | null;
  family: string;
  onFamilyChange: (id: string) => void;
  query: string;
  onQueryChange: (q: string) => void;
  catalog: CatalogModel[];
  filtered: CatalogModel[];
  filteredOllama: Installed[];
  installed: Installed[];
  busy: string | null;
  physGb: number | null;
  onOpenInfo: (m: CatalogModel) => void;
  onPull: (m: CatalogModel, weights?: boolean) => void;
  onUninstall: (id: string, name?: string, path?: string) => void;
  onOpenChat: (id: string) => void;
  onUseInAgent: (id: string) => void;
}) {
  const card = (m: CatalogModel, featured = false) => (
    <ModelCard
      key={m.id}
      m={m}
      inst={matchInstalled(installed, m.id)}
      busy={busy}
      progress={progress}
      physGb={physGb}
      onOpenInfo={onOpenInfo}
      onPull={onPull}
      onUninstall={onUninstall}
      onOpenChat={onOpenChat}
      onUseInAgent={onUseInAgent}
      featured={featured}
    />
  );
  const recommended = catalog.filter(
    (m) => m.recommended && (!physGb || !m.ram_gb || m.ram_gb <= physGb * 0.9)
  );
  const installedModels = catalog.filter((m) => {
    const inst = matchInstalled(installed, m.id);
    return inst && !inst.incomplete;
  });
  const showFeatured = !query.trim() && (family === "mac" || family === "new");
  const rest = showFeatured ? filtered.filter((m) => !recommended.includes(m)) : filtered;
  const counts = new Map<string, number>();
  for (const m of catalog) counts.set(m.family || "other", (counts.get(m.family || "other") || 0) + 1);

  return (
    <section className="pane scroll-pane">
      <div className="page">
        <header className="page-head">
          <div>
            <h1>Models</h1>
            <p className="page-sub">
              {status ||
                `${catalog.length} open models · ${installedModels.length} installed${
                  physGb ? ` · this machine has ${Math.round(physGb)} GB RAM` : ""
                }`}
            </p>
          </div>
          <label className="search">
            <SearchIcon />
            <input
              type="search"
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Search models"
              aria-label="Search models"
            />
          </label>
        </header>

        <div className="chips" role="tablist" aria-label="Filter models">
          {FAMILIES.filter(
            (f) =>
              ["mac", "new", "all", "ollama"].includes(f.id) ||
              (counts.get(f.id) || 0) > 0
          ).map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={family === f.id}
              className={`chip-btn${family === f.id ? " on" : ""}`}
              onClick={() => onFamilyChange(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {progress && !catalog.some((m) => m.id === progress.id) ? (
          <Progress pct={progress.pct} message={progress.message} />
        ) : null}

        {showFeatured && recommended.length ? (
          <>
            <h2 className="section-title">Recommended for this computer</h2>
            <div className="mgrid featured-grid">{recommended.map((m) => card(m, true))}</div>
          </>
        ) : null}

        {filteredOllama.length ? (
          <>
            <h2 className="section-title">
              Ollama <span className="section-note">already on this machine — no re-download</span>
            </h2>
            <div className="mgrid">
              {filteredOllama.map((m) => (
                <article key={m.id} className="mcard installed">
                  <div className="mcard-top">
                    <div className="mcard-title">
                      <h3>{(m.name || m.id).replace(/^ollama\//, "")}</h3>
                      <div className="mcard-badges">
                        <span className="badge muted">Ollama</span>
                      </div>
                    </div>
                  </div>
                  <p className="mcard-desc">{m.description || "Served by your local Ollama."}</p>
                  <div className="mcard-foot">
                    <span className="fit good">{m.size_bytes ? `${(m.size_bytes / 1e9).toFixed(1)} GB` : "Ready"}</span>
                    <div className="mcard-actions">
                      <button type="button" className="btn ghost sm" onClick={() => onUseInAgent(m.id)}>
                        Agent
                      </button>
                      <button type="button" className="btn primary sm" onClick={() => onOpenChat(m.id)}>
                        Chat
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </>
        ) : family === "ollama" ? (
          <p className="empty-note">No Ollama models detected. Start Ollama and pull a model — it appears here automatically.</p>
        ) : null}

        {family !== "ollama" ? (
          <>
            {showFeatured && rest.length ? <h2 className="section-title">More models</h2> : null}
            {rest.length ? (
              <div className="mgrid">{rest.map((m) => card(m))}</div>
            ) : (
              <p className="empty-note">No models match “{query}”.</p>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
