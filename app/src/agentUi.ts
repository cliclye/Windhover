export type AgentToolResult = {
  tool?: string;
  ok?: boolean;
  error?: string;
  path?: string;
  summary?: string;
  entries?: unknown[];
};

/** Strip tool-call soup from assistant text so the thread shows prose only. */
export function agentVisibleReply(text: string, hasTools: boolean): string {
  let t = (text || "").trim();
  if (!t) return "";
  t = t.replace(/(?:^|\n)TOOL\s+\w+[\s\S]*?(?:\nEND\b)/gi, "\n");
  t = t.replace(/```(?:tool|json)\s*\n[\s\S]*?```/gi, "\n");
  t = t.replace(/<tool>[\s\S]*?<\/tool>/gi, "\n");
  t = t.replace(/\n{3,}/g, "\n\n").trim();
  if (hasTools && !t) return "";
  if (hasTools && /simple calculator|basic arithmetic operations/i.test(t) && t.length < 800) {
    return "";
  }
  return t;
}

/** Cursor-style one-liners for tool activity (collapsed by default). */
export function toolActivityLabel(tr: AgentToolResult): string {
  const tool = String(tr.tool || "tool");
  const path = tr.path ? String(tr.path) : "";
  if (tr.ok === false) return `${tool} failed${path ? ` · ${path}` : ""}`;
  if (tool.includes("read")) return path ? `Read ${path}` : "Read file";
  if (tool.includes("write") || tool.includes("edit") || tool.includes("create")) {
    return path ? `Edited ${path}` : "Edited file";
  }
  if (tool.includes("list") || tool.includes("tree") || tool.includes("glob")) {
    const n = Array.isArray(tr.entries) ? tr.entries.length : 0;
    if (n > 0) return `Explored ${n} item${n === 1 ? "" : "s"}${path ? ` in ${path}` : ""}`;
    return path ? `Listed ${path}` : "Listed folder";
  }
  if (tr.summary) return String(tr.summary);
  return path ? `${tool} · ${path}` : tool;
}

export function toolActivityGroup(results: AgentToolResult[]): string {
  if (!results.length) return "";
  const labels = results.map(toolActivityLabel);
  if (labels.length === 1) return labels[0];
  const reads = labels.filter((l) => l.startsWith("Read ")).length;
  const edits = labels.filter((l) => l.startsWith("Edited ")).length;
  const explores = labels.filter((l) => l.startsWith("Explored ") || l.startsWith("Listed ")).length;
  const parts: string[] = [];
  if (explores) parts.push(`Explored ${explores} path${explores === 1 ? "" : "s"}`);
  if (reads) parts.push(`Read ${reads} file${reads === 1 ? "" : "s"}`);
  if (edits) parts.push(`Edited ${edits} file${edits === 1 ? "" : "s"}`);
  const other = labels.length - explores - reads - edits;
  if (other > 0) parts.push(`${other} other`);
  return parts.join(", ");
}
