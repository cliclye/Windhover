import type { Conversation, Msg } from "./types";

const KEY = "wh.conversations.v1";
const MAX_CONVS = 60;
const MAX_MSG_CHARS = 24_000;

export function newConversation(model: string): Conversation {
  return {
    id: `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: "New chat",
    model,
    messages: [],
    updated: Date.now(),
  };
}

export function titleFrom(messages: Msg[]): string {
  const first = messages.find((m) => m.role === "user")?.content || "";
  const t = first.replace(/\s+/g, " ").trim();
  if (!t) return "New chat";
  return t.length > 52 ? `${t.slice(0, 50)}…` : t;
}

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as Conversation[];
    if (!Array.isArray(list)) return [];
    return list.filter((c) => c && typeof c.id === "string" && Array.isArray(c.messages));
  } catch {
    return [];
  }
}

export function saveConversations(list: Conversation[]) {
  try {
    const trimmed = [...list]
      .sort((a, b) => b.updated - a.updated)
      .slice(0, MAX_CONVS)
      .map((c) => ({
        ...c,
        messages: c.messages.map((m) => ({
          ...m,
          content: m.content.length > MAX_MSG_CHARS ? m.content.slice(0, MAX_MSG_CHARS) : m.content,
        })),
      }));
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch {
    /* storage full / private mode — history is a convenience */
  }
}

export function groupByDay(list: Conversation[]): Array<{ label: string; items: Conversation[] }> {
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86_400_000;
  const groups: Record<string, Conversation[]> = {};
  const order = ["Today", "Yesterday", "Previous 7 days", "Older"];
  for (const c of [...list].sort((a, b) => b.updated - a.updated)) {
    const label =
      c.updated >= startToday
        ? "Today"
        : c.updated >= startToday - day
          ? "Yesterday"
          : c.updated >= startToday - 7 * day
            ? "Previous 7 days"
            : "Older";
    (groups[label] ||= []).push(c);
  }
  return order.filter((l) => groups[l]?.length).map((label) => ({ label, items: groups[label] }));
}
