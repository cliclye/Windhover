/** Keep turn-end markers in sync with tools/chat_text.py. */

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
  return s.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}
