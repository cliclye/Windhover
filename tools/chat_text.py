"""Chat output cleanup and family-aware prompt formatting for Windhover."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Special-token / template markers that mean "assistant turn is over".
TURN_END_MARKERS = (
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
)


def strip_engine_noise(text: str) -> str:
    """Remove windhover-engine log lines that must never appear as chat answers."""
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append(line)
            continue
        if re.match(r"^\[(?:wh|WH|CUDA|DSA|COLI|coli|windhover)\]", s):
            continue
        if re.match(r"^CATS sparsity", s, re.I):
            continue
        if re.search(r"\btok/s\b", s) and re.search(r"\b(?:prefill|decode|RSS|MB)\b", s, re.I):
            continue
        if re.match(r"^@@WH_STATS@@", s):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def truncate_repetition(text: str) -> str:
    """Cut degenerate loops like 'How can I help you? How can I help you?'."""
    if not text or len(text) < 40:
        return text
    m = re.search(r"(.{12,120}?)(?:\s*\1){2,}", text, flags=re.DOTALL)
    if m:
        return text[: m.start() + len(m.group(1))].rstrip()
    m = re.search(r"((?:\|\\s*){8,})", text)
    if m:
        return text[: m.start()].rstrip()
    m = re.search(r"(\b\w{1,3}\b(?:\s+\b\w{1,3}\b){20,})", text)
    if m:
        return text[: m.start()].rstrip()
    return text


def _is_gibberish_chunk(s: str) -> bool:
    """True for keyboard-smash / high-entropy alnum tails (not normal prose)."""
    t = re.sub(r"\s+", "", s or "")
    if len(t) < 14:
        return False
    letters = sum(c.isalpha() for c in t)
    digits = sum(c.isdigit() for c in t)
    punct = sum(c in ";'\\/_+=-@#$%^&*`~|" for c in t)
    if digits / len(t) >= 0.22:
        return True
    if punct / len(t) >= 0.12 and digits + letters > 8:
        return True
    if letters:
        vowels = sum(c.lower() in "aeiou" for c in t if c.isalpha())
        if vowels / letters < 0.18:
            return True
    # Long run with almost no spaces in the original slice
    if " " not in s.strip() and len(t) >= 18 and letters + digits >= 14:
        return True
    return False


def cut_gibberish_tail(text: str) -> str:
    """Drop random alnum / code-fence junk after a finished sentence."""
    if not text or len(text) < 20:
        return text
    s = text
    # Code fence after a short finished reply — only smash insides, not real code.
    m = re.search(
        r'(?s)(?<=[.!?…"\'\)\]])\s*```[\w+-]*\n(.*)\Z',
        s,
    )
    if m and m.start() > 8:
        body = (m.group(1) or "").replace("```", "").strip()
        if body and _is_gibberish_chunk(body):
            head = s[: m.start()].rstrip()
            if re.search(r'[.!?…"\'\)\]]\s*$', head):
                return head
    # Alphanumeric smash after sentence punctuation
    m = re.search(
        r'(?s)(?<=[.!?…"\'\)\]])\s+'
        r"([A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{14,}"
        r"|(?:[A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{6,}\s+){2,}[A-Za-z0-9;'\\/_+=@#$%^&*`~|-]*)"
        r"\s*\Z",
        s,
    )
    if m and m.start() > 0:
        chunk = m.group(1) if m.lastindex else m.group(0)
        if _is_gibberish_chunk(chunk):
            return s[: m.start()].rstrip()
    # Orphan smash on its own line after a blank line
    m = re.search(
        r"(?m)\n{1,2}([A-Za-z0-9;'\\/_+=@#$%^&*`~|-]{16,})\s*\Z",
        s,
    )
    if m and m.start() > 0 and _is_gibberish_chunk(m.group(1)):
        return s[: m.start()].rstrip()
    return s


def cut_at_turn_boundary(text: str) -> str:
    """Trim everything from the first next-turn / EOS marker onward."""
    if not text:
        return text
    s = text
    cut = None
    for marker in TURN_END_MARKERS:
        idx = s.find(marker)
        if idx >= 0 and (cut is None or idx < cut):
            cut = idx
    if cut is not None:
        s = s[:cut]
    # Plain-text role headers the model invents after missing EOS
    # (only after some answer text so "ask the assistant:" mid-sentence survives).
    m = re.search(
        r"(?m)(?:^|\n)(?:user|assistant|system|human|Human|Assistant|User|System)\s*:\s*",
        s,
    )
    if m and m.start() > 0:
        s = s[: m.start()]
    # Gemma leftover after <start_of_turn> strip: lone "user" / "model" line
    m = re.search(r"(?m)\n(?:user|model)\n", s)
    if m and m.start() > 0:
        s = s[: m.start()]
    # ChatML / instruction dump after a blank line
    m = re.search(
        r"\n{2,}(?:###\s*(?:User|Human|Instruction|Response)|"
        r"(?:User|Human|Instruction)\s*:)",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        s = s[: m.start()]
    return s


def clean_chat_text(text: str, *, soft: bool = False) -> str:
    """Strip chat-template / control tokens and tidy layout for UI display.

    soft=True: keep incomplete trailing control tokens (safe for streaming
    deltas) but still cut at complete turn boundaries so junk after the
    answer never reaches the UI.
    """
    if not text:
        return text
    s = strip_engine_noise(text)
    s = cut_at_turn_boundary(s)
    s = re.sub(r"<think\b[^>]*>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<thinking\b[^>]*>.*?</thinking>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(
        r"<redacted_reasoning\b[^>]*>.*?</redacted_reasoning>",
        "",
        s,
        flags=re.DOTALL | re.IGNORECASE,
    )
    s = re.sub(r"<reason\b[^>]*>.*?</reason>", "", s, flags=re.DOTALL | re.IGNORECASE)
    if not soft:
        s = re.sub(r"<think\b[^>]*>.*\Z", "", s, flags=re.DOTALL | re.IGNORECASE)
        s = re.sub(r"<thinking\b[^>]*>.*\Z", "", s, flags=re.DOTALL | re.IGNORECASE)
        s = re.sub(r"<redacted_reasoning\b[^>]*>.*\Z", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"</(?:think|thinking|redacted_reasoning|reason)\s*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<\|[^|>]+?\|>", "", s)
    s = re.sub(r"</?s>", "", s)
    s = re.sub(r"<end_of_turn>", "", s)
    s = re.sub(r"<start_of_turn>\w*", "", s)
    s = re.sub(r"\[/?INST\]", "", s)
    s = re.sub(r"<<SYS>>|<</SYS>>", "", s)
    s = cut_at_turn_boundary(s)
    s = cut_gibberish_tail(s)
    if soft:
        return s
    s = truncate_repetition(s)
    s = cut_gibberish_tail(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def snap_model_type(snap: Path) -> str:
    cfg = snap / "config.json"
    if not cfg.is_file():
        kpk = snap / "kpk" / "config.json"
        cfg = kpk if kpk.is_file() else cfg
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return ""
    tc = data.get("text_config") if isinstance(data.get("text_config"), dict) else {}
    return str(tc.get("model_type") or data.get("model_type") or "").lower()


def fallback_chat_prompt(messages: list, model_type: str = "") -> str:
    """Family-aware chat formatting when transformers isn't available (packaged apps)."""
    mt = (model_type or "").lower()
    turns = []
    for m in messages:
        role = (m.get("role") or "user").strip()
        content = (m.get("content") or "").strip()
        if content and role in ("user", "assistant", "system"):
            turns.append((role, content))
    if not turns:
        return ""

    if "phi" in mt:
        parts = []
        for role, content in turns:
            if role == "system":
                parts.append(f"<|system|>\n{content}<|end|>")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}<|end|>")
            else:
                parts.append(f"<|user|>\n{content}<|end|>")
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    if "gemma" in mt:
        parts = []
        for role, content in turns:
            grole = "model" if role == "assistant" else role
            if role == "system":
                parts.append(f"<start_of_turn>user\n{content}<end_of_turn>")
            else:
                parts.append(f"<start_of_turn>{grole}\n{content}<end_of_turn>")
        parts.append("<start_of_turn>model\n")
        return "\n".join(parts)

    if mt.startswith("llama") and "llama4" not in mt:
        parts = []
        for role, content in turns:
            parts.append(
                f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
            )
        parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "".join(parts)

    parts = []
    for role, content in turns:
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def format_engine_prompt(snap: Path, messages: list | None, flat_prompt: str) -> str:
    """Apply HF chat template when available so dense/engine packs get instruct formatting."""
    model_type = snap_model_type(snap) if snap else ""
    if messages:
        try:
            from transformers import AutoTokenizer

            tok = AutoTokenizer.from_pretrained(str(snap), trust_remote_code=True)
            chat = []
            for m in messages:
                role = m.get("role") or "user"
                content = (m.get("content") or "").strip()
                if content and role in ("user", "assistant", "system"):
                    chat.append({"role": role, "content": content})
            if chat and hasattr(tok, "apply_chat_template") and tok.chat_template:
                kwargs = {"tokenize": False, "add_generation_prompt": True}
                try:
                    return tok.apply_chat_template(chat, enable_thinking=False, **kwargs)
                except TypeError:
                    return tok.apply_chat_template(chat, **kwargs)
        except Exception as e:
            sys.stderr.write(f"[windhover] chat template fallback: {e}\n")
        fb = fallback_chat_prompt(messages, model_type)
        if fb:
            return fb
    return flat_prompt
