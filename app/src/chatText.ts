/** Keep turn-end markers / gibberish cuts in sync with tools/chat_text.py. */

export function extractSSE(buffer: string) {
  const frames = buffer.split(/\r?\n\r?\n/);
  const rest = frames.pop() || "";
  const data = frames.flatMap((frame) =>
    frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
  );
  return { data, rest };
}

function isGibberishChunk(s: string): boolean {
  const t = (s || "").replace(/\s+/g, "");
  if (t.length < 14) return false;
  let letters = 0;
  let digits = 0;
  let punct = 0;
  let vowels = 0;
  for (const c of t) {
    if (/[A-Za-z]/.test(c)) {
      letters++;
      if ("aeiouAEIOU".includes(c)) vowels++;
    } else if (/[0-9]/.test(c)) digits++;
    else if (/[;'\\/_+=@#$%^&*`~|-]/.test(c)) punct++;
  }
  if (digits / t.length >= 0.22) return true;
  if (punct / t.length >= 0.12 && digits + letters > 8) return true;
  if (letters && vowels / letters < 0.18) return true;
  if (!s.trim().includes(" ") && t.length >= 18 && letters + digits >= 14) return true;
  return false;
}

function cutGibberishTail(text: string): string {
  if (!text || text.length < 20) return text;
  let s = text;
  const fence = s.match(/(?<=[.!?…"')\]])\s*```[\w+-]*\n([\s\S]*)$/);
  if (fence && fence.index != null && fence.index > 8) {
    const body = (fence[1] || "").replace(/```/g, "").trim();
    if (body && isGibberishChunk(body)) {
      const head = s.slice(0, fence.index).replace(/\s+$/, "");
      if (/[.!?…"')\]]\s*$/.test(head)) return head;
    }
  }
  const smash = s.match(
    /(?<=[.!?…"')\]])\s+([A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{14,}|(?:[A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{6,}\s+){2,}[A-Za-z0-9;'\\/_+=@#$%^&*`~|-]*)\s*$/
  );
  if (smash && smash.index != null && smash.index > 0 && isGibberishChunk(smash[1])) {
    return s.slice(0, smash.index).replace(/\s+$/, "");
  }
  const orphan = s.match(/\n{1,2}([A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{16,})\s*$/);
  if (orphan && orphan.index != null && orphan.index > 0 && isGibberishChunk(orphan[1])) {
    return s.slice(0, orphan.index).replace(/\s+$/, "");
  }
  return s;
}

function truncateRepetition(text: string): string {
  if (!text || text.length < 40) return text;
  const loop = text.match(/(.{12,120}?)(?:\s*\1){2,}/s);
  if (loop && loop.index != null) {
    return text.slice(0, loop.index + loop[1].length).replace(/\s+$/, "");
  }
  return text;
}

export function cleanChatText(text: string): string {
  let s = text;
  const markers = [
    "<|im_end|>",
    "<|im_start|>",
    "<|end|>",
    "<|eot_id|>",
    "<|eom_id|>",
    "<|endoftext|>",
    "<|user|>",
    "<|assistant|>",
    "<|system|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<end_of_turn>",
    "<start_of_turn>",
    "</s>",
    "<eos>",
  ];
  const cutAtMarkers = (input: string) => {
    let out = input;
    let cut: number | null = null;
    for (const m of markers) {
      const i = out.indexOf(m);
      if (i >= 0 && (cut === null || i < cut)) cut = i;
    }
    if (cut !== null) out = out.slice(0, cut);
    const role = out.match(
      /(?:^|\n)(?:user|assistant|system|human|Human|Assistant|User|System)\s*:\s*/
    );
    if (role && role.index != null && role.index > 0) {
      out = out.slice(0, role.index);
    }
    const gemma = out.match(/\n(?:user|model)\n/);
    if (gemma && gemma.index != null && gemma.index > 0) {
      out = out.slice(0, gemma.index);
    }
    const dump = out.search(
      /\n{2,}(?:###\s*(?:User|Human|Instruction|Response)|(?:User|Human|Instruction)\s*:)/i
    );
    if (dump >= 0) out = out.slice(0, dump);
    return out;
  };
  s = cutAtMarkers(s);
  s = s
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, "")
    .replace(/<thinking\b[^>]*>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<redacted_reasoning\b[^>]*>[\s\S]*?<\/redacted_reasoning>/gi, "")
    .replace(/<reason\b[^>]*>[\s\S]*?<\/reason>/gi, "")
    .replace(/<think\b[^>]*>[\s\S]*$/gi, "")
    .replace(/<thinking\b[^>]*>[\s\S]*$/gi, "")
    .replace(/<\/?(?:think|thinking|redacted_reasoning|reason)\s*>/gi, "")
    .replace(/^\[(?:wh|WH|CUDA|DSA|COLI|coli|windhover)\][^\n]*/gm, "")
    .replace(/^CATS sparsity[^\n]*/gim, "")
    .replace(/<\|[^|>]+?\|>/g, "")
    .replace(/<\/?s>/g, "")
    .replace(/<end_of_turn>/g, "")
    .replace(/<start_of_turn>\w*/g, "")
    .replace(/\[\/?INST\]/g, "")
    .replace(/<<SYS>>|<<\/SYS>>/g, "");
  s = cutAtMarkers(s);
  s = cutGibberishTail(s);
  s = truncateRepetition(s);
  s = cutGibberishTail(s);
  return s.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}
