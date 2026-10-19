import { groupByDay } from "../conversations";
import type { Conversation, EngineState, Tab } from "../types";
import {
  AgentIcon,
  ChatIcon,
  GaugeIcon,
  GearIcon,
  LibraryIcon,
  MoonIcon,
  PlusIcon,
  SunIcon,
  TrashIcon,
} from "./Icons";

const NAV: Array<{ id: Tab; label: string; icon: JSX.Element; kbd: string }> = [
  { id: "chat", label: "Chat", icon: <ChatIcon />, kbd: "1" },
  { id: "library", label: "Models", icon: <LibraryIcon />, kbd: "2" },
  { id: "code", label: "Code", icon: <AgentIcon />, kbd: "3" },
  { id: "performance", label: "Performance", icon: <GaugeIcon />, kbd: "4" },
  { id: "settings", label: "Settings", icon: <GearIcon />, kbd: "5" },
];

export function Sidebar({
  tab,
  onTab,
  conversations,
  activeConv,
  onSelectConv,
  onDeleteConv,
  onNewChat,
  engineState,
  engineTitle,
  engineLabel,
  appVersion,
  installedCount,
  theme,
  onToggleTheme,
  updateLatest,
  onUpdate,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  conversations: Conversation[];
  activeConv: string;
  onSelectConv: (id: string) => void;
  onDeleteConv: (id: string) => void;
  onNewChat: () => void;
  engineState: EngineState;
  engineTitle: string;
  engineLabel: string;
  appVersion: string;
  installedCount: number;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  updateLatest?: string;
  onUpdate: () => void;
}) {
  const groups = groupByDay(conversations.filter((c) => c.messages.length > 0));
  return (
    <aside className="sidebar">
      <div className="sb-titlebar" data-drag aria-hidden="true" />
      <div className="sb-brand" data-drag>
        <img src="./windhover-icon.png" alt="" width={26} height={26} />
        <div className="sb-brand-text">
          <strong>Windhover</strong>
          <span>Local inference</span>
        </div>
      </div>

      <button type="button" className="sb-new" onClick={onNewChat}>
        <PlusIcon />
        <span>New chat</span>
        <kbd>⌘N</kbd>
      </button>

      <nav className="sb-nav" aria-label="Primary">
        {NAV.map((n) => (
          <button
            key={n.id}
            type="button"
            className={`sb-link${tab === n.id ? " on" : ""}`}
            aria-current={tab === n.id ? "page" : undefined}
            onClick={() => onTab(n.id)}
            title={`${n.label} (⌘${n.kbd})`}
          >
            {n.icon}
            <span>{n.label}</span>
            {n.id === "library" && installedCount ? <em className="sb-count">{installedCount}</em> : null}
          </button>
        ))}
      </nav>

      <div className="sb-history" aria-label="Recent chats">
        {groups.length === 0 ? (
          <p className="sb-empty">Your chats stay on this computer.</p>
        ) : (
          groups.map((g) => (
            <div key={g.label} className="sb-group">
              <div className="sb-group-label">{g.label}</div>
              {g.items.map((c) => (
                <div key={c.id} className={`sb-conv${c.id === activeConv && tab === "chat" ? " on" : ""}`}>
                  <button type="button" className="sb-conv-btn" onClick={() => onSelectConv(c.id)} title={c.title}>
                    {c.title}
                  </button>
                  <button
                    type="button"
                    className="sb-conv-del"
                    aria-label={`Delete ${c.title}`}
                    onClick={() => onDeleteConv(c.id)}
                  >
                    <TrashIcon size={14} />
                  </button>
                </div>
              ))}
            </div>
          ))
        )}
      </div>

      <div className="sb-foot">
        {updateLatest ? (
          <button type="button" className="sb-update" onClick={onUpdate}>
            Update to {updateLatest}
          </button>
        ) : null}
        <div className="sb-foot-row">
          <span className={`engine-pill ${engineState}`} title={engineTitle}>
            <i />
            {engineLabel}
          </span>
          <button
            type="button"
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title="Toggle theme"
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
        {appVersion ? <span className="sb-version">v{appVersion.replace(/^v/, "")}</span> : null}
      </div>
    </aside>
  );
}
